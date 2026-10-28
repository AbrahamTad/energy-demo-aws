"""Separate repositories/tables prevent public reads from reaching user data."""
from functools import lru_cache
import os
from uuid import uuid4
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError

from energy_validation import ApiError, private_record, public_record


@lru_cache(maxsize=2)
def table(environment_key):
    return boto3.resource("dynamodb", config=Config(connect_timeout=1, read_timeout=1,
                          retries={"mode": "standard", "total_max_attempts": 1})).Table(os.environ[environment_key])


class PublicRepository:
    def list(self):
        result = table("PUBLIC_ENERGY_TABLE").query(
            KeyConditionExpression=Key("dataset").eq("PUBLIC"), Limit=101)
        if result.get("LastEvaluatedKey") or len(result.get("Items", [])) > 100:
            raise ApiError(503, "Public snapshot exceeds its supported size.")
        return [public_record(item) for item in result.get("Items", [])]


class UserRepository:
    def list(self, subject, after=None):
        options = {"KeyConditionExpression": Key("user_sub").eq(subject),
                   "ConsistentRead": True, "Limit": 25}
        if after:
            # Cursor contains only a record ID; the partition always comes from JWT.
            options["ExclusiveStartKey"] = {"user_sub": subject, "record_id": after}
        result = table("USER_ENERGY_TABLE").query(**options)
        return {"records": [private_record(item) for item in result.get("Items", [])],
                "next_cursor": result.get("LastEvaluatedKey", {}).get("record_id")}

    def get(self, subject, identifier):
        item = table("USER_ENERGY_TABLE").get_item(
            Key={"user_sub": subject, "record_id": identifier}, ConsistentRead=True).get("Item")
        if not item:
            raise ApiError(404, "Record not found.")
        return private_record(item)

    def create(self, subject, values):
        identifier = str(uuid4())
        item = {**values, "user_sub": subject, "record_id": identifier,
                "updated_at": datetime.now(timezone.utc).isoformat()}
        table("USER_ENERGY_TABLE").put_item(Item=item,
            ConditionExpression="attribute_not_exists(user_sub) AND attribute_not_exists(record_id)")
        return private_record(item)

    def update(self, subject, identifier, values):
        try:
            result = table("USER_ENERGY_TABLE").update_item(
                Key={"user_sub": subject, "record_id": identifier},
                UpdateExpression="SET #source=:source, production=:production, #unit=:unit, measured_at=:measured, updated_at=:updated",
                ExpressionAttributeNames={"#source": "source", "#unit": "unit"},
                ExpressionAttributeValues={":source": values["source"], ":production": values["production"],
                    ":unit": values["unit"], ":measured": values["measured_at"],
                    ":updated": datetime.now(timezone.utc).isoformat()},
                ConditionExpression="attribute_exists(user_sub) AND attribute_exists(record_id)",
                ReturnValues="ALL_NEW")
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ApiError(404, "Record not found.") from None
            raise
        return private_record(result["Attributes"])

    def delete(self, subject, identifier):
        try:
            table("USER_ENERGY_TABLE").delete_item(
                Key={"user_sub": subject, "record_id": identifier},
                ConditionExpression="attribute_exists(user_sub) AND attribute_exists(record_id)")
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ApiError(404, "Record not found.") from None
            raise
