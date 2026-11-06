"""Offline Turnstile contract tests: no HTTP, AWS, SES or SNS access."""
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lambda/energy"))
import contact_api as api
import contact_common as common

# Cloudflare's published always-pass secret, used ONLY behind HTTP/config mocks.
TEST_SECRET = "1x0000000000000000000000000000000AA"
HOST = "d2gfvw1j7itrwq.cloudfront.net"


class TurnstileTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, CONTACT_HOSTNAMES=json.dumps([HOST]),
                         CONTACT_SECRET_ARN="offline-fixture", CONTACT_EMAIL_SENDING_ENABLED="false",
                         CONTACT_CUSTOMER_EMAIL_ENABLED="false",
                         CONTACT_ORIGIN_TOKEN_SHA256=hashlib.sha256(("a" * 64).encode()).hexdigest())
        env.start()
        self.addCleanup(env.stop)
        # Fail immediately on accidental AWS access, including email/notification.
        self.aws = patch.object(common.boto3, "client", side_effect=AssertionError("Unexpected AWS access"))
        self.aws_mock = self.aws.start()
        self.addCleanup(self.aws.stop)
        resources = patch.object(common.boto3, "resource", side_effect=AssertionError("Unexpected AWS resource access"))
        resources.start()
        self.addCleanup(resources.stop)
        self.secrets = patch.object(api, "secrets", return_value={"turnstile_secret": TEST_SECRET})
        self.secrets.start()
        self.addCleanup(self.secrets.stop)
        self.http = patch.object(api.urllib.request, "urlopen")
        self.http_mock = self.http.start()
        self.addCleanup(self.http.stop)
        self.result = self.http_mock.return_value.__enter__.return_value
        self.result.read.return_value = json.dumps({"success": True, "hostname": HOST, "action": "contact"}).encode()
        self.data = {"id": "f402e590-3f85-42b5-957e-38fc7fa82695", "name": "Fixture",
                     "email": "fixture@example.invalid", "subject": "Fixture", "message": "Fixture",
                     "website": "", "botToken": "XXXX.DUMMY.TOKEN.XXXX"}
        self.event = {"routeKey": "POST /api/contact", "requestContext": {"http": {"method": "POST"}},
                      "headers": {"content-type": "application/json", "x-energy-contact-origin": "a" * 64,
                                  "x-energy-contact-ip": "192.0.2.1"}, "body": json.dumps(self.data)}

    def submit(self, data=None):
        with patch.object(api, "budget"), patch.object(api, "digest", return_value="fixture-hash"), \
                patch.object(api, "get", return_value={"expires": 9999999999, "fingerprint": "fixture-hash"}):
            return api.lambda_handler({**self.event, "body": json.dumps(self.data if data is None else data)}, None)

    def test_official_test_credentials_contract_and_no_email_or_sns(self):
        self.assertEqual(self.submit()["statusCode"], 202)
        request = self.http_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://challenges.cloudflare.com/turnstile/v0/siteverify")
        self.assertEqual(request.method, "POST")
        self.assertEqual(json.loads(request.data), {"secret": TEST_SECRET, "response": self.data["botToken"]})
        self.assertEqual(self.http_mock.call_args.kwargs["timeout"], 5)
        self.aws_mock.assert_not_called()

    def test_missing_empty_oversized_or_wrong_type_tokens_never_call_siteverify(self):
        for token in [None, "", "x" * 2049, 42, []]:
            with self.subTest(token_type=type(token).__name__):
                self.assertEqual(self.submit({**self.data, "botToken": token})["statusCode"], 400)
        self.assertEqual(self.submit({key: value for key, value in self.data.items() if key != "botToken"})["statusCode"], 400)
        self.http_mock.assert_not_called()

    def test_invalid_expired_and_replayed_tokens_rejected_before_storage(self):
        for code in ["invalid-input-response", "timeout-or-duplicate"]:
            self.result.read.return_value = json.dumps({"success": False, "error-codes": [code]}).encode()
            self.assertEqual(self.submit()["statusCode"], 400)
        # Siteverify owns single-use enforcement; even an idempotent contact retry
        # must call it again and cannot bypass a timeout-or-duplicate response.
        self.result.read.return_value = json.dumps({"success": True, "hostname": HOST, "action": "contact"}).encode()
        self.assertEqual(self.submit()["statusCode"], 202)
        self.result.read.return_value = b'{"success":false,"error-codes":["timeout-or-duplicate"]}'
        self.assertEqual(self.submit()["statusCode"], 400)
        self.assertEqual(self.http_mock.call_count, 4)
        self.aws_mock.assert_not_called()

    def test_success_hostname_action_must_match_exactly(self):
        for changes in [{"success": "true"}, {"success": 1}, {"success": False},
                        {"hostname": "attacker.invalid"}, {"hostname": HOST + ".attacker.invalid"},
                        {"hostname": None}, {"action": "other"}, {"action": None}]:
            self.result.read.return_value = json.dumps({"success": True, "hostname": HOST, "action": "contact", **changes}).encode()
            self.assertEqual(self.submit()["statusCode"], 400)
        self.aws_mock.assert_not_called()

    def test_cloudflare_timeout_http_failure_and_malformed_responses_fail_closed(self):
        for error in [TimeoutError("fixture"), URLError("fixture"), HTTPError("fixture", 503, "fixture", {}, None)]:
            if isinstance(error, HTTPError):
                self.addCleanup(error.close)
            self.http_mock.side_effect = error
            self.assertEqual(self.submit()["statusCode"], 503)
        self.http_mock.side_effect = None
        for body in [b"not json", b"null", b"[]", b"{}"]:
            self.result.read.return_value = body
            result = self.submit()
            self.assertIn(result["statusCode"], [400, 503])
            self.assertNotIn("fixture", result["body"])
        self.aws_mock.assert_not_called()

    def test_missing_secret_fails_closed_without_http(self):
        with patch.object(api, "secrets", return_value={}):
            self.assertEqual(self.submit()["statusCode"], 503)
        self.http_mock.assert_not_called()

    def test_invalid_hostname_configuration_fails_closed(self):
        for config in ['[]', '"' + HOST + '"', '{}', '[null]', 'not-json']:
            with patch.dict(os.environ, CONTACT_HOSTNAMES=config):
                self.assertEqual(self.submit()["statusCode"], 503)
        self.http_mock.assert_not_called()

    def test_real_secret_loader_rejects_missing_and_official_test_secrets(self):
        common.secrets.cache_clear()
        self.addCleanup(common.secrets.cache_clear)
        with patch.object(common.boto3, "client") as client:
            for secret in [None, "", TEST_SECRET]:
                config = {"rate_hmac_key": "fixture" * 6}
                if secret is not None:
                    config["turnstile_secret"] = secret
                client.return_value.get_secret_value.return_value = {"SecretString": json.dumps(config)}
                with self.assertRaises(RuntimeError):
                    common.secrets()
        self.http_mock.assert_not_called()
