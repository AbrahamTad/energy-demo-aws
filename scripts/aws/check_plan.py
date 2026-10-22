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
