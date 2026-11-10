"""Public contact acceptance: durable atomic inquiry/outbox, never sends email."""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import re
import time
import urllib.request
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
import boto3
from contact_common import RETENTION, db, digest, get, live, secrets, safe_handler
from energy_validation import ApiError, record_id, response


def validate(event):
    try:
        raw = event.get("body", "")
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True).decode()
        if len(raw.encode()) > 10000:
            raise ValueError()
        data = json.loads(raw)
        if set(data) != {"id", "name", "email", "subject", "message", "website", "botToken"}:
            raise ValueError()
        record_id(data["id"])
        for key, maximum in [("name", 100), ("email", 254), ("subject", 150), ("message", 5000)]:
            value = data[key]
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
                raise ValueError()
            if any(ord(c) < 32 and (key != "message" or c not in "\n\t\r") for c in value):
                raise ValueError()
            data[key] = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", data["email"]):
            raise ValueError()
        data["email"] = data["email"].lower()
        if not isinstance(data["botToken"], str) or not 1 <= len(data["botToken"]) <= 2048:
            raise ValueError()
        if data["website"] != "":
            raise ValueError()
        return data
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ApiError(400, "Check all fields and complete the bot check. No attachments are accepted.") from None


def verify_bot(token):
    if not isinstance(token, str) or not 1 <= len(token.strip()) <= 2048:
        raise ApiError(400, "Bot verification failed. Complete a new check and try again.")
    hostnames = json.loads(os.environ["CONTACT_HOSTNAMES"])
    if not isinstance(hostnames, list) or not hostnames or any(not isinstance(host, str) or not host for host in hostnames):
        raise RuntimeError("Contact configuration unavailable")
    request = urllib.request.Request("https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=json.dumps({"secret": secrets()["turnstile_secret"], "response": token}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=5) as result:
        value = json.loads(result.read(8192))
    if (not isinstance(value, dict) or value.get("success") is not True
            or value.get("action") != "contact" or value.get("hostname") not in hostnames):
        raise ApiError(400, "Bot verification failed. Complete a new check and try again.")


def budget(key, limit, period):
    now = int(time.time())
    try:
        db().update_item(Key={"pk": key + "#" + str(now // period), "sk": "LIMIT"},
            UpdateExpression="SET expires=:expiry ADD attempts :one",
            ConditionExpression="attribute_not_exists(attempts) OR attempts < :limit",
            ExpressionAttributeValues={":expiry": now + period * 2, ":one": 1, ":limit": limit})
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        raise ApiError(429, "Contact limit reached. Please try later.") from None


def viewer_ip(headers):
    # CloudFront replaces the viewer header and overwrites the origin credential.
    # API Gateway sourceIp is an edge address; XFF is client-controlled.
    token = headers.get("x-energy-contact-origin", "")
    expected = os.environ.get("CONTACT_ORIGIN_TOKEN_SHA256", "")
    if (not re.fullmatch(r"[a-f0-9]{64}", token)
            or not re.fullmatch(r"[a-f0-9]{64}", expected)
            or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)):
        raise ApiError(403, "Contact must use the EnergyDemo website.")
    try:
        raw = headers.get("x-energy-contact-ip", "")
        if "%" in raw:
            raise ValueError()
        address = ipaddress.ip_address(raw)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return str(address)
    except ValueError:
        raise ApiError(403, "Invalid Contact request path.") from None


def submit(event):
    if event.get("routeKey") != "POST /api/contact" or event.get("requestContext", {}).get("http", {}).get("method") != "POST":
        raise ApiError(404, "Route not found.")
    if event.get("queryStringParameters"):
        raise ApiError(400, "Query parameters are not supported.")
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    if headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise ApiError(415, "Use application/json.")
    ip = viewer_ip(headers)
    data = validate(event)
    budget("IP#" + digest(ip), 10, 3600)
    verify_bot(data["botToken"])
    fingerprint = digest(json.dumps({k: data[k] for k in ["name", "email", "subject", "message"]}, sort_keys=True))
    pk = "CONTACT#" + data["id"]
    old = get(pk)
    if live(old):
        if old["fingerprint"] != fingerprint:
            raise ApiError(409, "Request ID already used. Start a new inquiry.")
        return response(202, {"id": data["id"], "status": "saved"})
    budget("ADDRESS#" + digest(data["email"]), 3, 86400)
    budget("SUBMISSIONS", 30, 86400)
    now = int(time.time())
    inquiry = {"pk": pk, "sk": "META", "id": data["id"], "fingerprint": fingerprint,
        **{k: data[k] for k in ["name", "email", "subject", "message"]},
        "created": now, "expires": now + RETENTION, "status": "new", "version": 1,
        "inbox": "INBOX", "order": f"{now:010d}#{data['id']}"}
    items = [inquiry] + [{"pk": pk, "sk": "JOB#" + kind, "kind": kind, "state": "pending",
        "created": now, "expires": now + RETENTION} for kind in ["customer", "admin"]]
    serializer = TypeSerializer()
    try:
        boto3.client("dynamodb").transact_write_items(TransactItems=[{"Put": {
            "TableName": os.environ["CONTACT_TABLE"], "Item": {k: serializer.serialize(v) for k, v in item.items()},
            "ConditionExpression": "attribute_not_exists(pk)"}} for item in items])
    except ClientError as error:
        if error.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        existing = get(pk)
        if not live(existing) or existing["fingerprint"] != fingerprint:
            raise ApiError(409, "Submission conflicted. Retry with the same request ID.") from None
    return response(202, {"id": data["id"], "status": "saved"})


def lambda_handler(event, context):
    return safe_handler(submit, event)
