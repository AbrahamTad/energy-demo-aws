"""Contact-only offline deployment and edge boundary regression tests."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
from test_deployment import gate, plan_guard, artifact

ROOT = Path(__file__).resolve().parents[2]

class ContactDeploymentTests(unittest.TestCase):
    def test_cloudfront_replaces_spoofed_headers_and_preserves_other_requests(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for edge function regression tests")
        code = (ROOT / "infrastructure/terraform-aws/contact-viewer.js").read_text()
        event = {"viewer": {"ip": "2001:db8::1"}, "request": {"uri": "/api/contact", "method": "POST",
            "headers": {"x-energy-contact-ip": {"value": "attacker", "multiValue": [{"value": "spoof"} ]},
                        "x-energy-contact-origin": {"value": "spoof"}, "authorization": {"value": "keep"}}}}
        for uri in ["/api/contact", "/api/admin/session", "/api/energy", "/api/contact/"]:
            event["request"]["uri"] = uri
            result = subprocess.run([node, "-e", code + "\nprocess.stdout.write(JSON.stringify(handler(" + json.dumps(event) + ")));"], capture_output=True, text=True, check=True)
            request = json.loads(result.stdout)
            self.assertNotIn("x-energy-contact-origin", request["headers"])
            self.assertEqual(request["headers"]["authorization"], {"value": "keep"})
            if uri == "/api/contact":
                self.assertEqual(request["headers"]["x-energy-contact-ip"], {"value": "2001:db8::1"})
            else:
                self.assertNotIn("x-energy-contact-ip", request["headers"])

    def configuration(self):
        return {"TF_VAR_account_id": "123456789012", "TF_VAR_budget_email": "budget@example.invalid",
            "AWS_REGION": "eu-north-1", "AWS_DEFAULT_REGION": "eu-north-1", "AWS_API_ID": "fixture",
            "AWS_CLOUDFRONT_DISTRIBUTION_ID": "FIXTURE", "AWS_CLOUDFRONT_OAC_ID": "FIXTUREOAC",
            "TF_VAR_enable_admin": "true", "TF_VAR_enable_contact": "true",
            "TF_VAR_contact_site_origin": "https://fixture.cloudfront.net",
            "TF_VAR_contact_hostnames": '["fixture.cloudfront.net"]', "TF_VAR_contact_origin_token": "a"*64,
            "TF_VAR_contact_sender": "sender@example.invalid", "TF_VAR_contact_admin_email": "admin@example.invalid",
            "TF_VAR_contact_alarm_topic_arn": "arn:aws:sns:eu-north-1:123456789012:operator",
            "VITE_TURNSTILE_SITE_KEY": "0xFIXTUREONLY000000000000"}

    def test_gate_requires_reviewed_configuration_and_binds_public_widget_key(self):
        with patch.dict(os.environ, self.configuration(), clear=True):
            original = gate.configuration()
            for key, value in [("TF_VAR_contact_site_origin", "https://attacker.invalid"),
                    ("TF_VAR_contact_hostnames", '["attacker.invalid"]'), ("TF_VAR_contact_origin_token", ""),
                    ("VITE_TURNSTILE_SITE_KEY", "1x00000000000000000000AA"),
                    ("TF_VAR_contact_email_sending_enabled", "true"),
                    ("TF_VAR_contact_customer_email_enabled", "true"),
                    ("TF_VAR_admin_email_testing_enabled", "true"),
                    ("TF_VAR_contact_alarm_topic_arn", "arn:aws:sns:eu-north-1:999999999999:operator")]:
                with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaises(ValueError):
                    gate.configuration()
            with patch.dict(os.environ, VITE_TURNSTILE_SITE_KEY="0xDIFFERENT00000000000000"):
                self.assertNotEqual(original, gate.configuration())

    def test_saved_plan_rejects_enabling_contact_worker_or_unprotecting_admin(self):
        worker = {"address": 'aws_lambda_function.contact["worker"]', "change": {"actions": ["create"],
            "after": {"role": "arn:aws:iam::628582070745:role/energy-demo-aws/contact-worker", "reserved_concurrent_executions": 0, "environment": [{"variables": {"CONTACT_EMAIL_SENDING_ENABLED": "false"}}]}}}
        queue = {"address": "aws_lambda_event_source_mapping.contact_queue[0]", "change": {"actions": ["create"], "after": {"enabled": False}}}
        plan_guard.verify({"resource_changes": [worker, queue]}, {})
        for resource, key, value in [(worker, "reserved_concurrent_executions", 1), (queue, "enabled", True)]:
            bad = copy.deepcopy(resource); bad["change"]["after"][key] = value
            with self.assertRaises(ValueError): plan_guard.verify({"resource_changes": [bad]}, {})
        route = {"address": 'aws_apigatewayv2_route.contact["detail"]', "change": {"actions": ["create"],
            "after": {"route_key": "GET /api/admin/messages/{id}", "authorization_type": "NONE"}}}
        with self.assertRaises(ValueError): plan_guard.verify({"resource_changes": [route]}, {})

    def test_widget_build_configuration_mismatch_is_rejected_before_files(self):
        import tempfile
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "manifest.json").write_text(json.dumps({"commit": "fixture", "sha256": {},
                "contact_site_key_sha256": hashlib.sha256(b"other-key").hexdigest()}))
            with patch.dict(os.environ, TF_VAR_enable_contact="true", VITE_TURNSTILE_SITE_KEY="reviewed-key"):
                with self.assertRaisesRegex(ValueError, "widget key"):
                    artifact.verify(output, "fixture")

    def test_contact_workflow_inputs_are_present_and_build_receives_only_public_key(self):
        import yaml
        plan = yaml.safe_load((ROOT / ".github/workflows/plan-aws.yml").read_text())
        deploy = yaml.safe_load((ROOT / ".github/workflows/deploy-aws.yml").read_text())
        build = yaml.safe_load((ROOT / ".github/workflows/build-aws.yml").read_text())
        for key in ["admin_email_testing_enabled", "enable_contact", "contact_sender", "contact_admin_email", "contact_hostnames",
                    "contact_site_origin", "contact_origin_token", "contact_alarm_topic_arn", "contact_sender_display_name", "contact_reply_to",
                    "contact_email_sending_enabled", "contact_customer_email_enabled"]:
            self.assertIn("TF_VAR_"+key, plan["env"])
            self.assertEqual(plan["env"]["TF_VAR_"+key], deploy["env"]["TF_VAR_"+key])
        self.assertEqual(build["jobs"]["build"]["env"]["VITE_TURNSTILE_SITE_KEY"], plan["env"]["VITE_TURNSTILE_SITE_KEY"])
        self.assertNotIn("AWS_CONTACT_ORIGIN_TOKEN", (ROOT / ".github/workflows/build-aws.yml").read_text())

    def test_saved_plan_rejects_admin_email_execution_in_no_send_rollout(self):
        for address in ['aws_lambda_function.admin["email"]', 'aws_lambda_function.admin["events"]',
                        'aws_iam_role.admin["email"]', 'aws_apigatewayv2_route.admin["email_post"]']:
            with self.subTest(address=address), self.assertRaises(ValueError):
                plan_guard.verify({"resource_changes": [{"address": address, "change": {"actions": ["create"], "after": {}}}]}, {})
