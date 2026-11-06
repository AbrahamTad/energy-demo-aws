"""Contact-only storage/configuration. Never log requests, tokens or inquiry data."""
import functools
import hashlib
import hmac
import json
import os
import time
import boto3
from energy_validation import ApiError, response

RETENTION = 90 * 86400

def db():
    return boto3.resource("dynamodb").Table(os.environ["CONTACT_TABLE"])

@functools.lru_cache(maxsize=1)
def secrets():
    value = json.loads(boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["CONTACT_SECRET_ARN"])["SecretString"])
    if len(value.get("rate_hmac_key", "")) < 32 or not value.get("turnstile_secret"):
        raise RuntimeError("Contact configuration unavailable")
    if value["turnstile_secret"].startswith(("1x", "2x", "3x")):
        raise RuntimeError("Test credentials are forbidden in deployed handlers")
    return value

def digest(value):
    return hmac.new(secrets()["rate_hmac_key"].encode(), value.encode(), hashlib.sha256).hexdigest()

def get(pk, sk="META"):
    return db().get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")

def live(item):
    return bool(item) and int(item["expires"]) > int(time.time())

def safe_handler(function, event):
    try:
        return function(event)
    except ApiError as error:
        return response(error.status, {"error": error.message})
    except Exception:
        return response(503, {"error": "Contact service is unavailable. Retry later with the same request ID."})
