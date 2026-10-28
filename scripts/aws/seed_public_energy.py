"""Dry-run by default. Only an explicitly authorized admin may execute this."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


def load_records(path):
    raw = path.read_bytes()
    if len(raw) > 64000:
        raise ValueError("Seed input must be smaller than 64 KB")
    data = json.loads(raw, parse_float=Decimal, parse_int=Decimal)
    records = data.get("records")
    if not isinstance(records, list) or not 1 <= len(records) <= 100:
        raise ValueError("Supply 1–100 reviewed public records")
    seen = set()
    for r in records:
        if (not isinstance(r, dict) or set(r) != {"source", "production", "unit"}
                or not isinstance(r["source"], str) or not 1 <= len(r["source"]) <= 64
                or r["source"] != r["source"].strip() or any(ord(c) < 32 for c in r["source"])
                or r["source"] in seen or r["unit"] != "kWh" or not isinstance(r["production"], Decimal)
                or not r["production"].is_finite() or not 0 <= r["production"] <= 1_000_000_000):
            raise ValueError("Invalid or potentially private seed record")
        seen.add(r["source"])
    return records, hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--profile", default="energy-demo-admin")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9]{12}", args.account_id) or args.account_id == "000000000000":
        raise ValueError("An approved real AWS account is required")
    records, digest = load_records(args.file)
    print(f"Reviewed input SHA256: {digest}; {len(records)} PUBLIC-only records; target energy-demo-aws-public-energy in eu-north-1.")
    if not args.execute:
        print("Dry run only. No AWS calls or writes. Use --execute only after approval.")
        return
    import boto3
    from botocore.config import Config
    session = boto3.Session(profile_name=args.profile, region_name="eu-north-1")
    config = Config(ignore_configured_endpoint_urls=True)
    if session.client("sts", config=config).get_caller_identity()["Account"] != args.account_id:
        raise ValueError("Account mismatch; no writes attempted")
    table = session.resource("dynamodb", config=config).Table("energy-demo-aws-public-energy")
    from botocore.exceptions import ClientError
    inserted = skipped = 0
    for record in records:
        try:
            table.put_item(Item={**record, "dataset": "PUBLIC"},
                           ConditionExpression="attribute_not_exists(dataset) AND attribute_not_exists(#source)",
                           ExpressionAttributeNames={"#source": "source"})
            inserted += 1
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            skipped += 1
    print(f"Inserted {inserted}; skipped {skipped} existing sources without overwriting. Verify the public snapshot before switching handlers. No private table was accessed.")


if __name__ == "__main__":
    main()
