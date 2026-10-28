"""Small shared request/response boundary; no identity comes from JSON input."""
import base64
from datetime import datetime, timezone
from decimal import Decimal, DecimalException, InvalidOperation
import json
import math
import uuid


class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def response(status, payload=None):
    return {"statusCode": status, "headers": {
        "Content-Type": "application/json", "Cache-Control": "no-store, private",
        "X-Content-Type-Options": "nosniff",
    }, "body": "" if payload is None else json.dumps(payload, allow_nan=False)}


def record_id(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise ApiError(400, "Invalid record ID.") from None


def body(event):
    try:
        raw = event.get("body") or ""
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True).decode("utf-8")
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > 4096:
            raise ValueError()
        value = json.loads(raw, parse_float=Decimal, parse_int=Decimal,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, DecimalException):
        raise ApiError(400, "Supply a JSON object smaller than 4 KB.") from None
    if not isinstance(value, dict) or set(value) != {"source", "production", "unit", "measured_at"}:
        raise ApiError(400, "Supply only source, production, unit and measured_at; ownership is assigned by the server.")
    source = value["source"]
    if not isinstance(source, str) or not source.strip() or len(source.strip()) > 64 or any(ord(c) < 32 for c in source):
        raise ApiError(400, "Source must contain 1–64 printable characters.")
    production = value["production"]
    if not isinstance(production, Decimal) or not production.is_finite() or not 0 <= production <= 1_000_000_000 or not -3 <= production.as_tuple().exponent <= 9:
        raise ApiError(400, "Production must be a number between 0 and 1,000,000,000 with at most three decimal places.")
    if value["unit"] != "kWh":
        raise ApiError(400, "Unit must be kWh.")
    try:
        timestamp = datetime.fromisoformat(value["measured_at"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or not 2000 <= timestamp.year <= 2100:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ApiError(400, "measured_at must be an ISO timestamp with a timezone (years 2000–2100).") from None
    return {"source": source.strip(), "production": production, "unit": "kWh",
            "measured_at": timestamp.astimezone(timezone.utc).isoformat()}


def public_record(item):
    # Explicit allowlist: never serialize table keys, ownership or private fields.
    source, amount = item.get("source"), item.get("production")
    if not isinstance(source, str) or not source or len(source) > 64 or item.get("unit") != "kWh":
        raise ApiError(503, "Stored energy data is invalid.")
    try:
        amount = float(amount)
        if not math.isfinite(amount) or not 0 <= amount <= 1_000_000_000:
            raise ValueError()
    except (ValueError, TypeError, OverflowError, InvalidOperation):
        raise ApiError(503, "Stored energy data is invalid.") from None
    return {"source": source, "production": amount, "unit": "kWh"}


def private_record(item):
    return {**public_record(item), "id": item["record_id"],
            "measured_at": item["measured_at"], "updated_at": item["updated_at"]}
