"""Shared admin boundary. No trust in browser groups, subjects or MFA flags."""
import hashlib
import json
import os
import time
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from energy_auth import verified_claims
from energy_validation import ApiError


@lru_cache(maxsize=8)
def client(service):
    return boto3.client(service, config=Config(connect_timeout=2, read_timeout=3,
        retries={"mode": "standard", "total_max_attempts": 1}))


def control():
    return os.environ["ADMIN_CONTROL_TABLE"]


def get(key):
    return client("dynamodb").get_item(TableName=control(), Key={"pk": {"S": key}},
        ConsistentRead=True).get("Item", {})


def put(key, values, expires, **kwargs):
    item = {"pk": {"S": key}, "expires": {"N": str(expires)}}
    item.update({k: {"S": str(v)} for k, v in values.items()})
    client("dynamodb").put_item(TableName=control(), Item=item, **kwargs)


def field(item, key, default=""):
    return item.get(key, {}).get("S", default)


def live(item):
    return int(item.get("expires", {}).get("N", "0")) > int(time.time())


def token_key(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    return hashlib.sha256(headers.get("authorization", "").encode()).hexdigest()


def identity(event, step_up=True):
    claims = verified_claims(event)
    if "energy-demo-admin" not in claims.get("cognito:groups", []):
        raise ApiError(403, "Administrator membership is required.")
    pool, owner = os.environ["COGNITO_USER_POOL_ID"], claims["sub"]
    cognito = client("cognito-idp")
    # JWT signature checks alone cannot detect GlobalSignOut/RevokeToken.
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    try:
        current = cognito.get_user(AccessToken=headers["authorization"][7:])
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "NotAuthorizedException":
            raise ApiError(401, "Your Cognito session was revoked. Sign in again.") from None
        raise
    if next((a["Value"] for a in current.get("UserAttributes", []) if a["Name"] == "sub"), None) != owner:
        raise ApiError(401, "The current Cognito identity did not match.")
    user = cognito.admin_get_user(UserPoolId=pool, Username=owner)
    attributes = {a["Name"]: a["Value"] for a in user.get("UserAttributes", [])}
    if not user.get("Enabled") or attributes.get("sub") != owner:
        raise ApiError(403, "Administrator access is disabled.")
    # Paginate current membership, never cache it across requests.
    options = {"UserPoolId": pool, "Username": user["Username"], "Limit": 60}
    while True:
        page = cognito.admin_list_groups_for_user(**options)
        if any(g["GroupName"] == "energy-demo-admin" for g in page.get("Groups", [])):
            break
        if not page.get("NextToken"):
            raise ApiError(403, "Administrator membership was removed.")
        options["NextToken"] = page["NextToken"]
    if ("SOFTWARE_TOKEN_MFA" not in user.get("UserMFASettingList", [])
            or user.get("PreferredMfaSetting") != "SOFTWARE_TOKEN_MFA"):
        raise ApiError(403, "Enable and prefer authenticator MFA in Settings before using admin.")
    if step_up and not live(get("PROOF#" + token_key(event))):
        raise ApiError(428, "Confirm your password and authenticator code for admin access.")
    return claims, user


def payload(event, allowed):
    try:
        raw = event.get("body") or "{}"
        if event.get("isBase64Encoded") or not isinstance(raw, str) or len(raw.encode()) > 4096:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != set(allowed):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ApiError(400, "Invalid request fields or body size.") from None


def text(value, maximum=2048):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ApiError(400, "Invalid request value.")
    return value


def reserve(key, limit, expires):
    # Explicit expiry in keys; TTL cleanup is never used as a rate-limit clock.
    client("dynamodb").update_item(TableName=control(), Key={"pk": {"S": key}},
        UpdateExpression="SET expires=:expiry ADD attempts :one",
        ConditionExpression="attribute_not_exists(attempts) OR attempts < :limit",
        ExpressionAttributeValues={":expiry": {"N": str(expires)}, ":one": {"N": "1"},
                                   ":limit": {"N": str(limit)}})
