import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


seed = load("seed", "scripts/aws/seed_public_energy.py")
smoke = load("smoke", "scripts/aws/publish_frontend.py")
guard = load("database_guard", "scripts/aws/check_plan.py")


class PublishingSmokeTests(unittest.TestCase):
    def publish(self, email_enabled, email_status, admin_status=401):
        site = "https://fixture.cloudfront.net"
        outputs = {"frontend_bucket": {"value": "fixture-bucket"},
                   "cloudfront_distribution_id": {"value": "FIXTURE"},
                   "site_url": {"value": site}, "admin_enabled": {"value": True},
                   "admin_email_testing_enabled": {"value": email_enabled}}
        requested = []

        def open_url(url, timeout):
            requested.append(url)
            if url in {site, site + "/admin"}:
                body = b'<div id="root"></div>'
            elif url == site + "/api/energy":
                body = json.dumps({"project": "EnergyDemo", "status": "working", "records": []}).encode()
            else:
                code = 401 if url.endswith("/api/me/energy") else (
                    email_status if url.endswith("/api/admin/email") else admin_status)
                if code != 200:
                    raise HTTPError(url, code, "fixture denial", {}, None)
                body = b"{}"
            response = io.BytesIO(body)
            response.status = 200
            return response

        with patch.object(smoke.subprocess, "check_output", side_effect=[json.dumps(outputs),
                json.dumps({"Invalidation": {"Id": "FIXTURE"}})]), \
                patch.object(smoke.subprocess, "run"), patch.object(smoke, "urlopen", side_effect=open_url), \
                patch.object(smoke.time, "sleep"):
            smoke.main()
        return requested

    def test_no_send_publish_accepts_missing_email_route_and_checks_admin_auth(self):
        requested = self.publish(False, 404)
        self.assertIn("https://fixture.cloudfront.net/api/admin/email", requested)
        self.assertIn("https://fixture.cloudfront.net/api/admin/users", requested)
        self.assertIn("https://fixture.cloudfront.net/api/admin/records/mine", requested)

    def test_email_enabled_publish_requires_authentication_denial(self):
        for status in [401, 403]:
            with self.subTest(status=status):
                self.publish(True, status)

    def test_publish_rejects_unexpected_or_public_admin_email_route(self):
        for enabled, status in [(False, 200), (False, 401), (True, 200), (True, 404)]:
            with self.subTest(enabled=enabled, status=status), self.assertRaises((HTTPError, ValueError)):
                self.publish(enabled, status)

    def test_no_send_publish_still_rejects_missing_protected_admin_routes(self):
        with self.assertRaises(HTTPError):
            self.publish(False, 404, admin_status=404)


class MigrationTests(unittest.TestCase):
    def test_plan_rejects_unprotected_admin_routes(self):
        authorizer = {"address": "aws_apigatewayv2_authorizer.users", "type": "aws_apigatewayv2_authorizer",
                      "change": {"actions": ["no-op"], "after": {"id": "reviewed-authorizer"}}}
        after = {"route_key": "GET /api/admin/users", "authorization_type": "JWT", "authorizer_id": "reviewed-authorizer",
                 "authorization_scopes": ["aws.cognito.signin.user.admin"]}
        def plan(values):
            return {"resource_changes": [authorizer, {"address": 'aws_apigatewayv2_route.admin["users"]',
                "type": "aws_apigatewayv2_route", "change": {"actions": ["create"], "after": values}}]}
        guard.verify(plan(after), {})
        for changed in [{"authorization_type": "NONE"}, {"authorizer_id": "wrong"}, {"authorization_scopes": []}, {"route_key": "GET /api/admin/records/all"}]:
            with self.subTest(changed=changed), self.assertRaises(ValueError): guard.verify(plan({**after, **changed}), {})

    def test_seed_defaults_to_dry_run_without_aws_calls(self):
        with patch("sys.argv", ["seed_public_energy.py", "--file", str(ROOT / "scripts/aws/public_energy_seed.json"), "--account-id", "123456789012"]), patch("boto3.Session") as session:
            seed.main()
            session.assert_not_called()

    def test_seed_rejects_private_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "seed.json"
            path.write_text(json.dumps({"records": [{"source": "Solar", "production": 1, "unit": "kWh", "user_sub": "private"}]}))
            with self.assertRaises(ValueError): seed.load_records(path)

    def test_public_smoke_accepts_empty_database_but_rejects_private_and_invalid_data(self):
        payload = {"project": "EnergyDemo", "status": "working", "records": []}
        smoke.verify_public_payload(payload)
        for record in [{"source": "Solar", "production": 1, "unit": "kWh", "user_sub": "private"},
                       {"source": "Solar", "production": float("nan"), "unit": "kWh"}]:
            with self.assertRaises(ValueError): smoke.verify_public_payload({**payload, "records": [record]})

    def test_plan_rejects_unapproved_table_names_and_disabled_protections(self):
        after = {"name": "energy-demo-aws-public-energy", "billing_mode": "PAY_PER_REQUEST", "deletion_protection_enabled": True,
                 "server_side_encryption": [{"enabled": True}], "point_in_time_recovery": [{"enabled": True}],
                 "on_demand_throughput": [{"max_read_request_units": 10, "max_write_request_units": 5}]}
        def plan(values): return {"resource_changes": [{"address": "aws_dynamodb_table.public_energy", "type": "aws_dynamodb_table", "change": {"actions": ["create"], "after": values}}]}
        guard.verify(plan(after), {})
        for changed in [{"name": "another-table"}, {"deletion_protection_enabled": False}, {"billing_mode": "PROVISIONED"},
                        {"server_side_encryption": [{"enabled": False}]}, {"point_in_time_recovery": [{"enabled": False}]}, {"on_demand_throughput": []}]:
            with self.subTest(changed=changed), self.assertRaises(ValueError): guard.verify(plan({**after, **changed}), {})
