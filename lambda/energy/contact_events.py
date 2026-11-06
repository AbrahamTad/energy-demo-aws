"""Trusted SES events only. No message bodies or addresses logged."""
import json
import os
import time
from botocore.exceptions import ClientError
from contact_common import db, digest, get, live
from energy_validation import record_id

RANK = {"Send": (1, "accepted"), "DeliveryDelay": (2, "delayed"), "Delivery": (3, "delivered"),
    "Reject": (4, "failed"), "Rendering Failure": (4, "failed"), "Bounce": (5, "bounced"), "Complaint": (6, "complaint")}


def parse_record(record):
    sns = record.get("Sns", {})
    if record.get("EventSource") != "aws:sns" or sns.get("TopicArn") != os.environ["CONTACT_TOPIC_ARN"]:
        raise ValueError("Untrusted event")
    value = json.loads(sns["Message"])
    tags = value.get("mail", {}).get("tags", {})
    if tags.get("ses:configuration-set") != [os.environ["CONTACT_SES_CONFIG"]]:
        raise ValueError("Untrusted configuration set")
    identifier = record_id(tags.get("contact_id", [None])[0])
    return value, identifier, tags.get("contact_kind", [None])[0]


def recovery_payload(body, source):
    """Offline normalization only; source queue provenance must be checked by the operator."""
    if source == "lambda":
        payload = body["requestPayload"]
    elif source == "sns":
        # SNS subscription DLQs retain the original published message, not a Lambda event.
        if body.get("Type") == "Notification":
            if body.get("TopicArn") != os.environ["CONTACT_TOPIC_ARN"]:
                raise ValueError("Untrusted recovery topic")
            body = json.loads(body["Message"])
        payload = {"Records": [{"EventSource": "aws:sns", "Sns": {
            "TopicArn": os.environ["CONTACT_TOPIC_ARN"], "Message": json.dumps(body)}}]}
    else:
        raise ValueError("Unsupported failure source")
    if not isinstance(payload, dict) or not payload.get("Records"):
        raise ValueError("Invalid recovery payload")
    for record in payload["Records"]:
        value, _, kind = parse_record(record)
        if kind not in ["customer", "admin"] or value.get("eventType") not in RANK:
            raise ValueError("Unsupported recovery event")
    return payload


def lambda_handler(event, context):
    for record in event["Records"]:
        value, identifier, kind = parse_record(record)
        if kind not in ["customer", "admin"] or value.get("eventType") not in RANK:
            continue
        pk, sk = "CONTACT#" + identifier, "JOB#" + kind
        if not live(get(pk, sk)):
            continue
        rank, status = RANK[value["eventType"]]
        try:
            db().update_item(Key={"pk": pk, "sk": sk},
                UpdateExpression="SET #s=:s, event_rank=:rank",
                ConditionExpression="attribute_exists(pk) AND expires > :now AND (attribute_not_exists(event_rank) OR event_rank < :rank)",
                ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": status, ":rank": rank, ":now": int(time.time())})
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
        # Temporary/undetermined bounces remain visible but do not block an address for 90 days.
        if status == "complaint" or (status == "bounced" and value.get("bounce", {}).get("bounceType") == "Permanent"):
            inquiry = get(pk)
            if live(inquiry):
                recipient = inquiry["email"] if kind == "customer" else os.environ["CONTACT_ADMIN_EMAIL"]
                db().put_item(Item={"pk": "SUPPRESS#" + digest(recipient), "sk": "SUPPRESS", "expires": int(time.time()) + 90 * 86400})
