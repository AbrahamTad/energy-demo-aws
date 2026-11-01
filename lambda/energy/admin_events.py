"""Trusted SNS delivery events; duplicate and out-of-order events are safe."""
import json
import os
import time

from botocore.exceptions import ClientError
from admin_common import client, control
from energy_validation import record_id

STATES = {"Send": (1, "accepted"), "DeliveryDelay": (2, "delayed"),
          "Delivery": (3, "delivered"), "Reject": (4, "rejected"),
          "Rendering Failure": (4, "failed"), "Bounce": (5, "bounced"), "Complaint": (6, "complaint")}


def lambda_handler(event, context):
    for record in event.get("Records", []):
        sns = record.get("Sns", {})
        if record.get("EventSource") != "aws:sns" or sns.get("TopicArn") != os.environ["ADMIN_EMAIL_TOPIC_ARN"]:
            raise ValueError("Untrusted event source")
        message = json.loads(sns["Message"])
        tags = message.get("mail", {}).get("tags", {})
        if tags.get("ses:configuration-set") != [os.environ["ADMIN_EMAIL_CONFIGURATION_SET"]]:
            raise ValueError("Untrusted configuration set")
        state = STATES.get(message.get("eventType"))
        if not state:
            continue
        identifier = record_id(tags.get("test_id", [None])[0])
        rank, status = state
        try:
            client("dynamodb").update_item(TableName=control(), Key={"pk": {"S": "EMAIL#" + identifier}},
                UpdateExpression="SET #state=:state, #rank=:rank, message_id=:message, updated_at=:now",
                ConditionExpression="attribute_exists(pk) AND expires > :time AND #rank < :rank",
                ExpressionAttributeNames={"#state": "status", "#rank": "rank"},
                ExpressionAttributeValues={":state": {"S": status}, ":rank": {"N": str(rank)},
                    ":message": {"S": message["mail"]["messageId"]}, ":now": {"S": str(int(time.time()))},
                    ":time": {"N": str(int(time.time()))}})
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
    return {"processed": True}
