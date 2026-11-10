"""Durable outbox relay and bounded SES worker; SQS contains keys only."""
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.utils import formataddr
import json
import os
import re
import time
from urllib.parse import urlsplit
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError
from contact_common import db, get, live, digest
from energy_validation import record_id


def email_content(reference, kind):
    # Only a canonical UUID enters the templates; customer fields are never interpolated.
    reference = record_id(reference)
    if kind == "customer":
        return "EnergyDemo — We received your inquiry", (
            "Thank you for contacting EnergyDemo.\n\n"
            "We have received your inquiry, and our team will review it.\n\n"
            f"Your inquiry reference: {reference}\n\n"
            "Please keep this reference for any follow-up. For your privacy, your original "
            "message is not included in this email. Please do not send passwords or other "
            "sensitive information.\n\nThe EnergyDemo team")
    if kind != "admin":
        raise ValueError("Invalid Contact email kind")
    origin = os.environ.get("CONTACT_SITE_ORIGIN", "")
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or parsed.netloc != parsed.hostname
            or not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", parsed.hostname or "")
            or parsed.hostname not in json.loads(os.environ["CONTACT_HOSTNAMES"])
            or origin not in [f"https://{parsed.hostname}", f"https://{parsed.hostname}/"]
            or parsed.path not in ["", "/"] or parsed.query or parsed.fragment
            or any(ord(c) <= 32 or ord(c) == 127 for c in origin)):
        raise ValueError("Invalid Contact site origin")
    return "EnergyDemo — New inquiry", (
        f"Inquiry reference: {reference}\n"
        f"EnergyDemo admin messages: {origin.rstrip('/')}/#/admin/messages")


def email_headers():
    # Configuration contains bare ASCII mailboxes only; never parse user input as headers.
    sender = os.environ.get("CONTACT_SENDER", "")
    reply_to = os.environ.get("CONTACT_REPLY_TO", "") or sender
    display_name = os.environ.get("CONTACT_SENDER_DISPLAY_NAME", "EnergyDemo Support")
    if (not 1 <= len(display_name) <= 80 or not display_name.strip()
            or any(ord(c) < 32 or ord(c) > 126 for c in display_name)):
        raise ValueError("Invalid Contact sender display name")
    for value in [sender, reply_to]:
        try:
            if (not 3 <= len(value) <= 254 or any(ord(c) <= 32 or ord(c) > 126 for c in value)
                    or Address(addr_spec=value).addr_spec != value
                    or not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value.rsplit("@", 1)[-1])):
                raise ValueError()
        except (ValueError, IndexError, HeaderParseError):
            raise ValueError("Invalid Contact sender or Reply-To mailbox") from None
    return formataddr((display_name, sender)), reply_to


def ses_client():
    # SendEmail has no idempotency token. Never retry uncertain HTTP acceptance.
    return boto3.client("sesv2", config=Config(connect_timeout=2, read_timeout=5,
        retries={"mode": "standard", "total_max_attempts": 1}))


def metrics(**values):
    # EMF contains aggregate counts only: no addresses, inquiry IDs or bodies.
    print(json.dumps({"_aws": {"Timestamp": int(time.time() * 1000), "CloudWatchMetrics": [{
        "Namespace": "EnergyDemo/Contact", "Dimensions": [["Service"]],
        "Metrics": [{"Name": name, "Unit": "Count"} for name in values]}]},
        "Service": "Contact", **values}))


def relay(event, context):
    if event.get("source") == "aws.events":
        # Periodic bounded pages recover outbox jobs after stream/DLQ interruptions.
        from boto3.dynamodb.conditions import Attr
        checkpoint = get("RECONCILE", "CURSOR") or {}
        cursor = checkpoint.get("cursor")
        uncertain = int(checkpoint.get("uncertain", 0))
        failed = int(checkpoint.get("failed", 0))
        pending = int(checkpoint.get("pending", 0))
        unconfirmed = int(checkpoint.get("unconfirmed", 0))
        for _ in range(10):
            options = {"FilterExpression": Attr("sk").begins_with("JOB#"), "Limit": 100,
                "ProjectionExpression": "pk, sk, expires, #s, claimed_at, created",
                "ExpressionAttributeNames": {"#s": "state"}}
            if cursor:
                options["ExclusiveStartKey"] = cursor
            page = db().scan(**options)
            for item in page.get("Items", []):
                if not live(item):
                    continue
                if item["state"] == "unknown" or (item["state"] == "sending"
                        and int(item.get("claimed_at", item.get("created", 0))) <= int(time.time()) - 300):
                    uncertain += 1
                if item["state"] in ["failed", "bounced", "complaint"]:
                    failed += 1
                age = int(time.time()) - int(item.get("claimed_at", item.get("created", 0)))
                if item["state"] in ["accepted", "delayed"] and age >= 3600:
                    unconfirmed += 1
                if item["state"] == "pending" and age >= 900:
                    pending += 1
                if item["state"] == "pending" and sending_enabled():
                    boto3.client("sqs").send_message(QueueUrl=os.environ["CONTACT_QUEUE_URL"],
                        MessageBody=json.dumps({"pk": item["pk"], "sk": item["sk"]}),
                        MessageGroupId="contact-email", MessageDeduplicationId=item["pk"] + item["sk"])
            cursor = page.get("LastEvaluatedKey")
            # Persist each completed page so a later timeout cannot restart a whole sweep.
            db().put_item(Item={"pk": "RECONCILE", "sk": "CURSOR", "cursor": cursor,
                "uncertain": uncertain if cursor else 0, "failed": failed if cursor else 0,
                "pending": pending if cursor else 0, "unconfirmed": unconfirmed if cursor else 0,
                "expires": int(time.time()) + 86400})
            if not cursor:
                break
            if context is not None and context.get_remaining_time_in_millis() < 8000:
                break
        # Only a completed sweep can clear an uncertainty alarm. Partial pages may raise it.
        values = {"ReconcileSuccess": 1}
        if uncertain or not cursor:
            values["UncertainJobs"] = uncertain
        if failed or not cursor:
            values["FailedJobs"] = failed
        if pending or not cursor:
            values["PendingJobs"] = pending
        if unconfirmed or not cursor:
            values["UnconfirmedJobs"] = unconfirmed
        metrics(**values)
        return {}
    if not sending_enabled():
        return {"batchItemFailures": []}  # Durable pending rows are recovered by reconciliation.
    failures = []
    for record in event["Records"]:
        try:
            if record.get("eventName") != "INSERT":
                continue
            keys = record["dynamodb"]["Keys"]
            pk, sk = keys["pk"]["S"], keys["sk"]["S"]
            if not pk.startswith("CONTACT#") or sk not in ["JOB#customer", "JOB#admin"]:
                continue
            boto3.client("sqs").send_message(QueueUrl=os.environ["CONTACT_QUEUE_URL"],
                MessageBody=json.dumps({"pk": pk, "sk": sk}), MessageGroupId="contact-email",
                MessageDeduplicationId=pk + sk)
        except Exception:
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
            break  # preserve stream ordering; checkpoint retries remaining records
    return {"batchItemFailures": failures}


def state(pk, sk, value, message_id=""):
    try:
        db().update_item(Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #state=:state, message_id=:mid",
            ConditionExpression="#state=:sending",
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues={":state": value, ":mid": message_id, ":sending": "sending"})
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return  # A newer SES event already owns the state; do not emit a stale failure alarm.
    if value == "unknown":
        metrics(UncertainJobs=1)
    elif value == "failed":
        metrics(FailedJobs=1)


def sending_enabled():
    return os.environ.get("CONTACT_EMAIL_SENDING_ENABLED") == "true"


def send(pk, sk):
    if not sending_enabled():
        # Fail, rather than acknowledge a queued job. No DB claims or SES calls.
        raise RuntimeError("Contact email sending is disabled")
    job, inquiry = get(pk, sk), get(pk)
    if not live(job) or not live(inquiry) or job["state"] != "pending":
        return  # sending after interruption is ambiguous: never automatically resend
    # Validate configuration before claiming the job, so a bad link cannot strand a send.
    subject, body = email_content(inquiry["id"], job["kind"])
    sender, reply_to = email_headers()
    recipient = inquiry["email"] if job["kind"] == "customer" else os.environ["CONTACT_ADMIN_EMAIL"]
    if live(get("SUPPRESS#" + digest(recipient), "SUPPRESS")):
        try:
            db().update_item(Key={"pk": pk, "sk": sk}, UpdateExpression="SET #s=:s",
                ConditionExpression="#s=:pending", ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues={":s": "suppressed", ":pending": "pending"})
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
        return
    # Local rollout is sandbox-only. No dynamic recipient send until explicit production enable.
    if os.environ.get("CONTACT_CUSTOMER_EMAIL_ENABLED") != "true" and job["kind"] == "customer":
        try:
            verified = ses_client().get_email_identity(EmailIdentity=recipient).get("VerifiedForSendingStatus")
        except ClientError as e:
            if e.response["Error"]["Code"] != "NotFoundException":
                raise
            verified = False
        if not verified:
            db().update_item(Key={"pk": pk, "sk": sk}, UpdateExpression="SET #s=:s",
                ConditionExpression="#s=:pending", ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues={":s": "sandbox_blocked", ":pending": "pending"})
            return
    now = int(time.time())
    try:
        db().update_item(Key={"pk": "SES_RATE", "sk": "LIMIT"},
            UpdateExpression="SET next_send=:next, expires=:expiry",
            ConditionExpression="attribute_not_exists(next_send) OR next_send <= :now",
            ExpressionAttributeValues={":next": now + 2, ":now": now, ":expiry": now + 86400})
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise RuntimeError("Retry rate-limited job") from None
        raise
    try:
        db().update_item(Key={"pk": pk, "sk": sk}, UpdateExpression="SET #s=:sending, claimed_at=:now",
            ConditionExpression="#s=:pending", ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":pending": "pending", ":sending": "sending", ":now": now})
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return
        raise
    reference = inquiry["id"]
    try:
        result = ses_client().send_email(FromEmailAddress=sender, ReplyToAddresses=[reply_to],
            Destination={"ToAddresses": [recipient]}, ConfigurationSetName=os.environ["CONTACT_SES_CONFIG"],
            Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}}}},
            EmailTags=[{"Name": "contact_id", "Value": reference}, {"Name": "contact_kind", "Value": job["kind"]}])
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ["TooManyRequestsException", "ThrottlingException"]:
            state(pk, sk, "pending")
            raise RuntimeError("Retry throttled email") from None
        state(pk, sk, "unknown" if e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 500) >= 500 else "failed")
    except BotoCoreError:
        state(pk, sk, "unknown")
    else:
        # A failed persistence write is not an SES rejection. Leave the claim intact;
        # queue retries must never send an already accepted email again.
        state(pk, sk, "accepted", result["MessageId"])


def worker(event, context):
    failures = []
    for record in event["Records"]:
        try:
            value = json.loads(record["body"])
            if set(value) != {"pk", "sk"} or value["sk"] not in ["JOB#customer", "JOB#admin"]:
                raise ValueError()
            send(value["pk"], value["sk"])
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
            break
    return {"batchItemFailures": failures}
