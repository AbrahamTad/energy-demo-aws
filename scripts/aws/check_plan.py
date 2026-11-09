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
        if (address in {'aws_lambda_function.admin["email"]', 'aws_lambda_function.admin["events"]',
                        'aws_iam_role.admin["email"]', 'aws_iam_role.admin["events"]',
                        'aws_apigatewayv2_route.admin["email_get"]', 'aws_apigatewayv2_route.admin["email_post"]'}):
            raise ValueError("Admin email-test execution is excluded from this no-send deployment")
        if address.startswith("aws_apigatewayv2_route.admin["):
            name = address.removeprefix("aws_apigatewayv2_route.admin[").removesuffix("]").strip('"')
            authorizer = changes.get("aws_apigatewayv2_authorizer.users", {}).get("change", {}).get("after", {}).get("id")
            if (name not in admin_paths or after.get("route_key") != admin_paths[name]
                    or after.get("authorization_type") != "JWT" or not authorizer
                    or after.get("authorizer_id") != authorizer
                    or after.get("authorization_scopes") != ["aws.cognito.signin.user.admin"]):
                raise ValueError("Unprotected or unapproved admin route: " + address)
        contact_kinds = {"api", "relay", "worker", "admin", "events"}
        if address.startswith("aws_iam_role.contact["):
            if actions == ["create"]:
                raise ValueError("Contact CI requires operator-preprovisioned runtime roles")
            name = address.removeprefix('aws_iam_role.contact["').removesuffix('"]')
            expected_trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
                "Action": "sts:AssumeRole", "Principal": {"Service": "lambda.amazonaws.com"}}]}
            try:
                trust = json.loads(after.get("assume_role_policy", ""))
            except (TypeError, ValueError):
                raise ValueError("Unverifiable Contact runtime trust") from None
            if (name not in contact_kinds or after.get("name") != "contact-" + name
                    or after.get("path") != "/energy-demo-aws/"
                    or after.get("permissions_boundary") != "arn:aws:iam::628582070745:policy/energy-demo-bootstrap/contact-" + name + "-boundary"
                    or trust != expected_trust):
                raise ValueError("Contact runtime role must retain its exact boundary and Lambda-only trust")
        if address.startswith("aws_lambda_function.contact["):
            name = address.removeprefix('aws_lambda_function.contact["').removesuffix('"]')
            if name not in contact_kinds or after.get("role") != "arn:aws:iam::628582070745:role/energy-demo-aws/contact-" + name:
                raise ValueError("Contact function must use its intended runtime role")
        if address.startswith("aws_apigatewayv2_route.contact["):
            name = address.split('["', 1)[1].split('"', 1)[0]
            routes = {"submit": "POST /api/contact", "list": "GET /api/admin/messages",
                      "detail": "GET /api/admin/messages/{id}", "status": "POST /api/admin/messages/{id}/status"}
            authorizer = changes.get("aws_apigatewayv2_authorizer.users", {}).get("change", {}).get("after", {}).get("id")
            public = name == "submit"
            if (name not in routes or after.get("route_key") != routes[name]
                    or after.get("authorization_type") != ("NONE" if public else "JWT")
                    or (not public and (not authorizer or after.get("authorizer_id") != authorizer
                        or after.get("authorization_scopes") != ["aws.cognito.signin.user.admin"]))):
                raise ValueError("Unprotected or unapproved Contact route")
        if address == 'aws_lambda_function.contact["worker"]':
            env = (after.get("environment") or [{}])[0].get("variables", {})
            if after.get("reserved_concurrent_executions") != 0 or env.get("CONTACT_EMAIL_SENDING_ENABLED") != "false":
                raise ValueError("Contact readiness worker must remain disabled")
        if address == "aws_lambda_event_source_mapping.contact_queue[0]" and after.get("enabled") is not False:
            raise ValueError("Contact readiness queue consumer must remain disabled")
        if resource.get("type") == "aws_dynamodb_table":
            expected_tables = {"aws_dynamodb_table.public_energy": "energy-demo-aws-public-energy",
                               "aws_dynamodb_table.user_energy": "energy-demo-aws-user-energy",
                               "aws_dynamodb_table.admin_control[0]": "energy-demo-aws-admin-control",
                               "aws_dynamodb_table.contact[0]": "energy-demo-aws-contact"}
            after = resource["change"].get("after") or {}
            if (address not in expected_tables or after.get("name") != expected_tables[address]
                    or after.get("billing_mode") != "PAY_PER_REQUEST" or after.get("deletion_protection_enabled") is not True
                    or not (after.get("server_side_encryption") or [{}])[0].get("enabled")
                    or not (after.get("point_in_time_recovery") or [{}])[0].get("enabled")
                    or (after.get("on_demand_throughput") or [{}])[0] != {"max_read_request_units": 10,
                        "max_write_request_units": 10 if address in ["aws_dynamodb_table.admin_control[0]", "aws_dynamodb_table.contact[0]"] else 5}):
                raise ValueError("Unapproved or unprotected DynamoDB table: " + address)
            if address == "aws_dynamodb_table.contact[0]" and (after.get("hash_key") != "pk"
                    or after.get("range_key") != "sk" or after.get("stream_view_type") != "KEYS_ONLY"
                    or after.get("stream_enabled") is not True
                    or (after.get("ttl") or [{}])[0] != {"enabled": True, "attribute_name": "expires"}):
                raise ValueError("Contact requires reviewed keys, TTL and keys-only stream")
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
