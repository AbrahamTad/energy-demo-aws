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
    admin_paths = {"session_get": "GET /api/admin/session", "session_post": "POST /api/admin/session",
                   "users": "GET /api/admin/users", "public": "GET /api/admin/records/public",
                   "mine": "GET /api/admin/records/mine", "status": "GET /api/admin/status",
                   "email_get": "GET /api/admin/email", "email_post": "POST /api/admin/email"}
    for address, resource in changes.items():
        actions = resource["change"]["actions"]
        if resource.get("mode", "managed") != "managed" or actions not in (
            ["no-op"], ["update"], ["create"]
        ):
            raise ValueError("Destructive or unsupported plan action: " + address)
        after = resource["change"].get("after") or {}
        if address.startswith("aws_apigatewayv2_route.admin["):
            name = address.removeprefix("aws_apigatewayv2_route.admin[").removesuffix("]").strip('"')
            authorizer = changes.get("aws_apigatewayv2_authorizer.users", {}).get("change", {}).get("after", {}).get("id")
            if (name not in admin_paths or after.get("route_key") != admin_paths[name]
                    or after.get("authorization_type") != "JWT" or not authorizer
                    or after.get("authorizer_id") != authorizer
                    or after.get("authorization_scopes") != ["aws.cognito.signin.user.admin"]):
                raise ValueError("Unprotected or unapproved admin route: " + address)
        if resource.get("type") == "aws_dynamodb_table":
            expected_tables = {"aws_dynamodb_table.public_energy": "energy-demo-aws-public-energy",
                               "aws_dynamodb_table.user_energy": "energy-demo-aws-user-energy",
                               "aws_dynamodb_table.admin_control[0]": "energy-demo-aws-admin-control"}
            after = resource["change"].get("after") or {}
            if (address not in expected_tables or after.get("name") != expected_tables[address]
                    or after.get("billing_mode") != "PAY_PER_REQUEST" or after.get("deletion_protection_enabled") is not True
                    or not (after.get("server_side_encryption") or [{}])[0].get("enabled")
                    or not (after.get("point_in_time_recovery") or [{}])[0].get("enabled")
                    or (after.get("on_demand_throughput") or [{}])[0] != {"max_read_request_units": 10,
                        "max_write_request_units": 10 if address == "aws_dynamodb_table.admin_control[0]" else 5}):
                raise ValueError("Unapproved or unprotected DynamoDB table: " + address)
            if address == "aws_dynamodb_table.admin_control[0]" and (after.get("hash_key") != "pk"
                    or not (after.get("ttl") or [{}])[0].get("enabled")
                    or (after.get("ttl") or [{}])[0].get("attribute_name") != "expires"):
                raise ValueError("Admin control table must have its reviewed key and TTL")
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
