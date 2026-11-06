"""Admin-only inquiries. No public read/status endpoints."""
import json
import time
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from admin_common import identity
from contact_common import db, get, live, safe_handler
from energy_validation import ApiError, record_id, response


def manage(event):
    claims, _ = identity(event)  # current membership, revocation, preferred MFA and step-up
    route = event.get("routeKey")
    if route == "GET /api/admin/messages":
        query = event.get("queryStringParameters") or {}
        if set(query) - {"before"}:
            raise ApiError(400, "Invalid pagination.")
        before = query.get("before", "9999999999#ffffffff-ffff-ffff-ffff-ffffffffffff")
        if len(before) != 47 or before[10] != "#" or not before[:10].isdigit():
            raise ApiError(400, "Invalid pagination.")
        record_id(before[11:])
        result = db().query(IndexName="inbox", KeyConditionExpression=Key("inbox").eq("INBOX") & Key("order").lt(before),
            ScanIndexForward=False, Limit=20)
        values = []
        for key in result.get("Items", []):
            item = get(key["pk"])
            if live(item):
                values.append({k: int(item[k]) if k in ["created", "version"] else item[k] for k in ["id", "subject", "status", "created", "version"]})
        return response(200, {"messages": values,
            "next_cursor": result.get("LastEvaluatedKey", {}).get("order")})
    identifier = record_id((event.get("pathParameters") or {}).get("id"))
    pk = "CONTACT#" + identifier
    item = get(pk)
    if not live(item):
        raise ApiError(404, "Inquiry not found.")
    if route == "POST /api/admin/messages/{id}/status":
        try:
            raw = event.get("body", "")
            if event.get("isBase64Encoded") or len(raw.encode()) > 256:
                raise ValueError()
            values = json.loads(raw)
            if set(values) != {"status", "version"} or values["status"] not in ["new", "in_progress", "resolved", "spam"] or type(values["version"]) is not int:
                raise ValueError()
        except (ValueError, TypeError):
            raise ApiError(400, "Invalid status update.") from None
        try:
            db().update_item(Key={"pk": pk, "sk": "META"},
                UpdateExpression="SET #s=:s, version=version+:one, updated=:now, updated_by=:by",
                ConditionExpression="version=:version AND expires>:now",
                ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": values["status"],
                    ":one": 1, ":version": values["version"], ":now": int(time.time()), ":by": claims["sub"]})
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            raise ApiError(409, "Inquiry changed. Reload before updating.") from None
        return response(200, {"status": values["status"], "version": values["version"] + 1})
    if route != "GET /api/admin/messages/{id}":
        raise ApiError(404, "Route not found.")
    jobs = {kind: get(pk, "JOB#" + kind) for kind in ["customer", "admin"]}
    return response(200, {**{k: int(item[k]) if k in ["created", "version"] else item[k] for k in ["id", "name", "email", "subject", "message", "created", "status", "version"]},
        "email_status": {k: "unknown" if (v or {}).get("state") == "sending" else (v or {}).get("state", "unknown") for k, v in jobs.items()}})


def lambda_handler(event, context):
    return safe_handler(manage, event)
