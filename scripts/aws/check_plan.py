"""Offline saved-plan guard: CI cannot create/replace/delete bootstrap resources."""
import json
import os
import re
import subprocess


def expected_ids(environment):
    keys = {
        "aws_apigatewayv2_api.energy": ("AWS_API_ID", r"[a-z0-9]{1,32}"),
        "aws_cloudfront_distribution.frontend": ("AWS_CLOUDFRONT_DISTRIBUTION_ID", r"[A-Z0-9]{1,64}"),
        "aws_cloudfront_origin_access_control.frontend": ("AWS_CLOUDFRONT_OAC_ID", r"[A-Z0-9]{1,64}"),
    }
    result = {}
    for address, (key, pattern) in keys.items():
        value = environment.get(key, "")
        if not re.fullmatch(pattern, value):
            raise ValueError("Missing or invalid administrator-verified resource ID: " + key)
        result[address] = value
    return result


def verify(plan, ids):
    changes = {r["address"]: r for r in plan.get("resource_changes", [])}
    for address, resource in changes.items():
        actions = resource["change"]["actions"]
        if resource.get("mode", "managed") != "managed" or actions not in (
            ["no-op"], ["update"], ["create"]
        ):
            raise ValueError("Destructive or unsupported plan action: " + address)
        if resource.get("type") == "aws_dynamodb_table":
            expected_tables = {"aws_dynamodb_table.public_energy": "energy-demo-aws-public-energy",
                               "aws_dynamodb_table.user_energy": "energy-demo-aws-user-energy"}
            after = resource["change"].get("after") or {}
            if (address not in expected_tables or after.get("name") != expected_tables[address]
                    or after.get("billing_mode") != "PAY_PER_REQUEST" or after.get("deletion_protection_enabled") is not True
                    or not (after.get("server_side_encryption") or [{}])[0].get("enabled")
                    or not (after.get("point_in_time_recovery") or [{}])[0].get("enabled")
                    or (after.get("on_demand_throughput") or [{}])[0] != {"max_read_request_units": 10, "max_write_request_units": 5}):
                raise ValueError("Unapproved or unprotected DynamoDB table: " + address)
    for address, expected in ids.items():
        resource = changes.get(address, {})
        change = resource.get("change", {})
        if (change.get("actions") not in (["no-op"], ["update"])
                or (change.get("before") or {}).get("id") != expected
                or (change.get("after") or {}).get("id") != expected):
            raise ValueError("Resource missing, replaced or not administrator-approved: " + address)


if __name__ == "__main__":
    ids = expected_ids(os.environ)
    plan = json.loads(subprocess.check_output([
        "terraform", "-chdir=infrastructure/terraform-aws", "show", "-json", "reviewed.tfplan"
    ], text=True))
    verify(plan, ids)
    print("Saved plan preserves exact bootstrap IDs and contains no deletions or replacements.")
