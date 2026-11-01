"""Bounded SES test sending; ambiguous sends are never retried automatically."""
import json
import os
import time

from botocore.exceptions import BotoCoreError, ClientError
from admin_common import client, control, field, get, identity, live, payload
from energy_validation import ApiError, record_id, response


def recipients():
    return json.loads(os.environ["ADMIN_EMAIL_RECIPIENTS"])


def view(item):
    status = field(item, "status")
    if status == "sending" and int(field(item, "updated_at", "0")) < int(time.time()) - 60:
        status = "unknown"
    return {"id": field(item, "id"), "status": status,
            "recipient": field(item, "recipient"), "message_id": field(item, "message_id"),
            "updated_at": field(item, "updated_at")}


def update(key, state, message_id=""):
    # Events may arrive before SendEmail returns. Do not overwrite their result.
    try:
        client("dynamodb").update_item(TableName=control(), Key={"pk": {"S": key}},
            UpdateExpression="SET #state=:state, message_id=:message, updated_at=:now",
            ConditionExpression="#state=:pending",
            ExpressionAttributeNames={"#state": "status"},
            ExpressionAttributeValues={":state": {"S": state}, ":message": {"S": message_id},
                ":now": {"S": str(int(time.time()))}, ":pending": {"S": "sending"}})
    except ClientError as error:
        if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


def send(event, owner):
    values = payload(event, ["id", "recipient"])
    identifier = record_id(values["id"])
    recipient = values["recipient"]
    if recipient not in recipients():
        raise ApiError(400, "Select an approved verified test recipient.")
    key, now = "EMAIL#" + identifier, int(time.time())
    existing = get(key)
    if existing:
        if field(existing, "owner") != owner or field(existing, "recipient") != recipient:
            raise ApiError(409, "This request ID is already in use.")
        return view(existing)
    ses = client("sesv2")
    for address in (os.environ["ADMIN_EMAIL_SENDER"], recipient):
        if not ses.get_email_identity(EmailIdentity=address).get("VerifiedForSendingStatus"):
            raise ApiError(409, "Sender and recipient must both be verified in this SES region.")
    table = control()
    transactions = []
    for counter, limit, expiry in [("SENDDAY#" + str(now // 86400), 10, now + 172800)]:
        transactions.append({"Update": {"TableName": table, "Key": {"pk": {"S": counter}},
            "UpdateExpression": "SET expires=:expiry ADD attempts :one",
            "ConditionExpression": "attribute_not_exists(attempts) OR attempts < :limit",
            "ExpressionAttributeValues": {":expiry": {"N": str(expiry)}, ":one": {"N": "1"}, ":limit": {"N": str(limit)}}}})
    transactions.append({"Update": {"TableName": table, "Key": {"pk": {"S": "SENDMIN#" + owner}},
        "UpdateExpression": "SET expires=:expiry, next_send_at=:next",
        "ConditionExpression": "attribute_not_exists(next_send_at) OR next_send_at <= :now",
        "ExpressionAttributeValues": {":expiry": {"N": str(now + 120)}, ":next": {"N": str(now + 60)}, ":now": {"N": str(now)}}}})
    item = {"pk": {"S": key}, "owner": {"S": owner}, "id": {"S": identifier},
            "recipient": {"S": recipient}, "status": {"S": "sending"}, "rank": {"N": "0"},
            "updated_at": {"S": str(now)}, "expires": {"N": str(now + 30 * 86400)}}
    transactions.append({"Put": {"TableName": table, "Item": item,
                                "ConditionExpression": "attribute_not_exists(pk)"}})
    try:
        client("dynamodb").transact_write_items(TransactItems=transactions)
    except ClientError as error:
        if error.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        existing = get(key)
        if existing and field(existing, "owner") == owner and field(existing, "recipient") == recipient:
            return view(existing)
        raise ApiError(429, "Email limit reached: one per admin/minute and ten per account/UTC day.") from None
    try:
        result = ses.send_email(FromEmailAddress=os.environ["ADMIN_EMAIL_SENDER"],
            Destination={"ToAddresses": [recipient]},
            Content={"Simple": {"Subject": {"Data": "EnergyDemo admin email test", "Charset": "UTF-8"},
                "Body": {"Text": {"Data": "This is an approved EnergyDemo administration email delivery test. No action is required.", "Charset": "UTF-8"}}}},
            ConfigurationSetName=os.environ["ADMIN_EMAIL_CONFIGURATION_SET"],
            EmailTags=[{"Name": "test_id", "Value": identifier}])
        update(key, "accepted", result["MessageId"])
    except ClientError as error:
        # 5xx and network errors can mean SES accepted the message: never resend.
        state = "unknown" if error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500) >= 500 else "failed"
        update(key, state)
    except BotoCoreError:
        update(key, "unknown")
    return view(get(key))


def lambda_handler(event, context):
    try:
        route = event.get("routeKey")
        method = event.get("requestContext", {}).get("http", {}).get("method")
        if route not in {"GET /api/admin/email", "POST /api/admin/email"} or not route.startswith(str(method) + " "):
            raise ApiError(404, "Route not found.")
        claims, _ = identity(event)
        owner = claims["sub"]
        if method == "POST":
            if event.get("queryStringParameters"):
                raise ApiError(400, "Query parameters are not supported here.")
            result = send(event, owner)
        else:
            query = event.get("queryStringParameters") or {}
            if not query:
                result = {"recipients": recipients(), "daily_limit": 10, "per_admin_minute": 1}
            elif set(query) == {"id"}:
                item = get("EMAIL#" + record_id(query["id"]))
                if not live(item) or field(item, "owner") != owner:
                    raise ApiError(404, "Email test not found.")
                result = view(item)
            else:
                raise ApiError(400, "Only id is supported.")
        return response(200, result)
    except ApiError as error:
        return response(error.status, {"error": error.message})
    except (ClientError, BotoCoreError, KeyError, ValueError, TypeError, RuntimeError):
        return response(503, {"error": "Email testing is unavailable. A pending request must not be resent with a new ID."})
