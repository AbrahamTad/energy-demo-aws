"""Security boundaries with signed JWTs and real Moto DynamoDB transactions; no AWS calls."""
import json
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import boto3
from botocore.exceptions import EndpointConnectionError
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lambda/energy"))
import admin_common as common
import admin_handler as admin
import admin_email as email
import admin_events as events
import energy_auth
import energy_store
from energy_validation import ApiError

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
POOL, CLIENT = "eu-north-1_OfflineFixture", "fixtureclient"
TOPIC = "arn:aws:sns:eu-north-1:123456789012:energy-demo-aws-admin-email"


class AdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.env = patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_DEFAULT_REGION": "eu-north-1", "AWS_EC2_METADATA_DISABLED": "true",
            "COGNITO_USER_POOL_ID": POOL, "COGNITO_CLIENT_ID": CLIENT,
            "ADMIN_COGNITO_CLIENT_ID": "adminclient", "ADMIN_CONTROL_TABLE": "admin-control",
            "ADMIN_EMAIL_TESTING_ENABLED": "true", "ADMIN_EMAIL_SENDER": "sender@example.invalid", "ADMIN_EMAIL_RECIPIENTS": '["test@example.invalid"]',
            "ADMIN_EMAIL_CONFIGURATION_SET": "energy-demo-aws-admin", "ADMIN_EMAIL_TOPIC_ARN": TOPIC,
            "PUBLIC_ENERGY_TABLE": "public", "USER_ENERGY_TABLE": "private",
            "ADMIN_PRIVATE_ROLE_ARN": "arn:aws:iam::123456789012:role/energy-demo-aws/admin-private"})
        self.env.start(); self.addCleanup(self.env.stop)
        self.aws = mock_aws(); self.aws.start(); self.addCleanup(self.aws.stop)
        common.client.cache_clear(); energy_auth.settings.cache_clear(); energy_store.table.cache_clear()
        self.addCleanup(common.client.cache_clear); self.addCleanup(energy_auth.settings.cache_clear)
        self.addCleanup(energy_store.table.cache_clear)
        db = boto3.resource("dynamodb")
        self.db = db.Table("admin-control")
        db.create_table(TableName="admin-control", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}])
        for name, pk, sk in [("public", "dataset", "source"), ("private", "user_sub", "record_id")]:
            db.create_table(TableName=name, BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}, {"AttributeName": sk, "KeyType": "RANGE"}],
                AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}, {"AttributeName": sk, "AttributeType": "S"}])
        self.keys = patch.object(energy_auth.PyJWKClient, "get_signing_key_from_jwt", return_value=SimpleNamespace(key=self.key.public_key()))
        self.keys.start(); self.addCleanup(self.keys.stop)
        self.cognito = MagicMock()
        self.cognito.get_user.return_value = {"UserAttributes": [{"Name": "sub", "Value": OWNER}]}
        self.cognito.admin_get_user.return_value = {"Enabled": True, "Username": "canonical-user",
            "UserAttributes": [{"Name": "sub", "Value": OWNER}], "UserMFASettingList": ["SOFTWARE_TOKEN_MFA"],
            "PreferredMfaSetting": "SOFTWARE_TOKEN_MFA"}
        self.cognito.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": "energy-demo-admin"}]}
        self.ses = MagicMock()
        self.ses.get_email_identity.return_value = {"VerifiedForSendingStatus": True}
        self.ses.send_email.return_value = {"MessageId": "ses-message"}
        original = common.client
        def clients(name):
            if name == "cognito-idp": return self.cognito
            if name == "sesv2": return self.ses
            return original(name)
        for module in [common, admin, email, events]:
            patcher = patch.object(module, "client", side_effect=clients)
            patcher.start(); self.addCleanup(patcher.stop)
        self.token = self.jwt()
        self.prove()

    def jwt(self, **changes):
        now = int(time.time())
        claims = {"iss": "https://cognito-idp.eu-north-1.amazonaws.com/" + POOL, "sub": OWNER,
            "client_id": CLIENT, "token_use": "access", "iat": now - 1, "exp": now + 900,
            "scope": "aws.cognito.signin.user.admin", "cognito:groups": ["energy-demo-admin"]}
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "fixture"})

    def event(self, route="GET /api/admin/session", values=None, query=None):
        return {"routeKey": route, "requestContext": {"http": {"method": route.split()[0]}},
                "headers": {"Authorization": "Bearer " + self.token},
                "body": json.dumps(values) if values is not None else None, "queryStringParameters": query}

    def prove(self):
        common.put("PROOF#" + common.token_key(self.event()), {"subject": OWNER}, int(time.time()) + 900)

    def call(self, route="GET /api/admin/session", values=None, query=None):
        handler = email if route.endswith("/email") else admin
        result = handler.lambda_handler(self.event(route, values, query), None)
        return result["statusCode"], json.loads(result["body"])

    def test_signature_expiry_client_and_token_use(self):
        for changes in [{"exp": 1}, {"client_id": "other"}, {"token_use": "id"}, {"iss": "https://untrusted.invalid"}]:
            self.token = self.jwt(**changes)
            self.assertEqual(self.call()[0], 401)
        self.token = self.token[:-12] + "X" * 12
        self.assertEqual(self.call()[0], 401)

    def test_anonymous_and_non_admin_cannot_read_or_send(self):
        self.token = ""
        self.assertEqual(self.call()[0], 401)
        self.token = self.jwt(**{"cognito:groups": []})
        self.assertEqual(self.call()[0], 403)
        self.assertEqual(self.call("POST /api/admin/email", {"id": str(uuid4()), "recipient": "test@example.invalid"})[0], 403)
        self.ses.send_email.assert_not_called()

    def test_live_group_removal_disabled_user_and_disabled_mfa(self):
        self.assertEqual(self.call()[0], 200)
        self.cognito.admin_list_groups_for_user.return_value = {"Groups": []}
        self.assertEqual(self.call()[0], 403)

        self.cognito.admin_list_groups_for_user.return_value = {"Groups": [{"GroupName": "energy-demo-admin"}]}
        self.cognito.admin_get_user.return_value["Enabled"] = False
        self.assertEqual(self.call()[0], 403)
        self.cognito.admin_get_user.return_value["Enabled"] = True
        self.cognito.admin_get_user.return_value["PreferredMfaSetting"] = ""
        self.assertEqual(self.call()[0], 403)

    def test_revoked_primary_token_cannot_reuse_valid_mfa_proof(self):
        self.cognito.get_user.side_effect = ClientError({"Error": {"Code": "NotAuthorizedException", "Message": "revoked"}}, "GetUser")
        self.assertEqual(self.call()[0], 401)
        self.assertEqual(self.call("GET /api/admin/email")[0], 401)
        self.cognito.admin_list_groups_for_user.assert_not_called()

    def test_membership_pagination(self):
        self.cognito.admin_list_groups_for_user.side_effect = [
            {"Groups": [], "NextToken": "next"}, {"Groups": [{"GroupName": "energy-demo-admin"}]}]
        self.assertEqual(self.call()[0], 200)
        self.assertEqual(self.cognito.admin_list_groups_for_user.call_args.kwargs["NextToken"], "next")

    def test_proof_is_token_bound_and_expires_without_ttl_cleanup(self):
        self.token = self.jwt(iat=int(time.time()) - 10)
        self.assertEqual(self.call()[0], 428)
        common.put("PROOF#" + common.token_key(self.event()), {}, 1)
        self.assertEqual(self.call()[0], 428)

    def test_step_up_requires_actual_cognito_totp_challenge(self):
        self.db.delete_item(Key={"pk": "PROOF#" + common.token_key(self.event())})
        self.assertEqual(self.call()[0], 428)
        self.cognito.admin_initiate_auth.return_value = {"AuthenticationResult": {"AccessToken": self.token}}
        self.assertEqual(self.call("POST /api/admin/session", {"password": "secret"})[0], 403)
        self.cognito.admin_initiate_auth.return_value = {"ChallengeName": "SOFTWARE_TOKEN_MFA", "Session": "opaque-session"}
        status, value = self.call("POST /api/admin/session", {"password": "secret"})
        self.assertEqual(status, 200)
        self.cognito.admin_respond_to_auth_challenge.return_value = {"AuthenticationResult": {"AccessToken": self.jwt(client_id="adminclient")}}
        fields = {"challenge": value["challenge"], "code": "123456"}
        self.assertEqual(self.call("POST /api/admin/session", fields)[0], 200)
        self.assertEqual(self.call()[0], 200)
        self.assertEqual(self.call("POST /api/admin/session", fields)[0], 403)
        self.cognito.admin_respond_to_auth_challenge.assert_called_once()
        self.assertNotIn("secret", json.dumps(self.db.scan()["Items"], default=str))

    def test_totp_result_for_different_subject_is_rejected(self):
        self.cognito.admin_initiate_auth.return_value = {"ChallengeName": "SOFTWARE_TOKEN_MFA", "Session": "opaque"}
        _, value = self.call("POST /api/admin/session", {"password": "secret"})
        self.cognito.admin_respond_to_auth_challenge.return_value = {"AuthenticationResult": {"AccessToken": self.jwt(client_id="adminclient", sub=OTHER)}}
        self.assertEqual(self.call("POST /api/admin/session", {"challenge": value["challenge"], "code": "123456"})[0], 403)

    def test_challenge_cannot_be_used_with_another_primary_token(self):
        self.cognito.admin_initiate_auth.return_value = {"ChallengeName": "SOFTWARE_TOKEN_MFA", "Session": "opaque"}
        _, value = self.call("POST /api/admin/session", {"password": "secret"})
        self.token = self.jwt(iat=int(time.time()) - 20)
        self.assertEqual(self.call("POST /api/admin/session", {"challenge": value["challenge"], "code": "123456"})[0], 403)
        self.cognito.admin_respond_to_auth_challenge.assert_not_called()

    def test_user_directory_redacts_pii_and_wraps_cursor(self):
        self.cognito.list_users.return_value = {"Users": [{"Username": "private@example.invalid", "Enabled": True,
            "Attributes": [{"Name": "sub", "Value": OTHER}, {"Name": "email", "Value": "private@example.invalid"}], "UserStatus": "CONFIRMED"}], "PaginationToken": "sensitive-upstream-token"}
        status, value = self.call("GET /api/admin/users")
        self.assertEqual(status, 200)
        self.assertEqual(set(value["users"][0]), {"id", "status", "enabled"})
        self.assertNotIn("private@example.invalid", json.dumps(value))
        self.assertNotIn("sensitive-upstream-token", json.dumps(value))
        cursor = value["next_cursor"]
        self.assertEqual(self.call("GET /api/admin/users", query={"cursor": cursor})[0], 200)
        self.assertEqual(self.cognito.list_users.call_args.kwargs["PaginationToken"], "sensitive-upstream-token")
        self.assertEqual(self.call("GET /api/admin/records/public", query={"cursor": cursor})[0], 400)
        self.assertEqual(self.call("GET /api/admin/users", query={"cursor": str(uuid4())})[0], 400)
        self.db.update_item(Key={"pk": "CURSOR#" + cursor}, UpdateExpression="SET #owner=:other",
            ExpressionAttributeNames={"#owner": "owner"}, ExpressionAttributeValues={":other": OTHER})
        self.assertEqual(self.call("GET /api/admin/users", query={"cursor": cursor})[0], 400)

    def test_reject_owner_selection_and_all_user_record_routes(self):
        for query in [{"user_sub": OTHER}, {"owner": OTHER}, {"limit": "10000"}]:
            self.assertEqual(self.call("GET /api/admin/records/mine", query=query)[0], 400)
        self.assertEqual(self.call("GET /api/admin/records/all")[0], 404)

    def test_private_records_are_own_only_with_subject_tagged_role(self):
        table = boto3.resource("dynamodb").Table("private")
        for owner in [OWNER, OTHER]:
            table.put_item(Item={"user_sub": owner, "record_id": str(uuid4()), "source": owner,
                "production": 1, "unit": "kWh", "measured_at": "2026-10-29T00:00:00Z", "updated_at": "2026-10-29T00:00:00Z"})
        sts = common.client("sts")
        with patch.object(sts, "assume_role", wraps=sts.assume_role) as assume:
            status, value = self.call("GET /api/admin/records/mine")
        self.assertEqual(assume.call_args.kwargs["Tags"], [{"Key": "user_sub", "Value": OWNER}])
        self.assertEqual(status, 200)
        self.assertEqual([r["source"] for r in value["records"]], [OWNER])
        self.assertNotIn("user_sub", json.dumps(value))

    def test_public_records_paginate_without_personal_data(self):
        table = boto3.resource("dynamodb").Table("public")
        for index in range(26):
            table.put_item(Item={"dataset": "PUBLIC", "source": f"Source {index:02d}", "production": 1, "unit": "kWh", "email": "hidden"})
        status, value = self.call("GET /api/admin/records/public")
        self.assertEqual(status, 200); self.assertEqual(len(value["records"]), 25)
        second = self.call("GET /api/admin/records/public", query={"cursor": value["next_cursor"]})[1]
        self.assertEqual(len(second["records"]), 1); self.assertIsNone(second["next_cursor"])
        self.assertNotIn("hidden", json.dumps(value))

    def test_disabled_email_cannot_read_reserve_or_send_even_when_called_directly(self):
        for value in [None, "false", "TRUE", "1", ""]:
            with self.subTest(value=value), patch.dict(os.environ):
                if value is None:
                    os.environ.pop("ADMIN_EMAIL_TESTING_ENABLED", None)
                else:
                    os.environ["ADMIN_EMAIL_TESTING_ENABLED"] = value
                with patch.object(email, "client") as client, patch.object(email, "get") as get:
                    with self.assertRaises(ApiError) as error:
                        email.send({}, OWNER)
                    self.assertEqual(error.exception.status, 503)
                    client.assert_not_called()
                    get.assert_not_called()
                self.assertEqual(self.call("POST /api/admin/email", {"id": str(uuid4()), "recipient": "test@example.invalid"})[0], 503)
                self.ses.send_email.assert_not_called()

    def test_email_requires_verified_allowlist_and_fixed_content(self):
        identifier = str(uuid4())
        self.assertEqual(self.call("POST /api/admin/email", {"id": identifier, "recipient": "other@example.invalid"})[0], 400)
        self.ses.get_email_identity.return_value = {"VerifiedForSendingStatus": False}
        self.assertEqual(self.call("POST /api/admin/email", {"id": identifier, "recipient": "test@example.invalid"})[0], 409)
        self.ses.send_email.assert_not_called()
        self.ses.get_email_identity.return_value = {"VerifiedForSendingStatus": True}
        values = {"id": identifier, "recipient": "test@example.invalid"}
        self.assertEqual(self.call("POST /api/admin/email", {**values, "subject": "injected"})[0], 400)
        self.assertEqual(self.call("POST /api/admin/email", values)[1]["status"], "accepted")
        sent = self.ses.send_email.call_args.kwargs
        self.assertEqual(sent["FromEmailAddress"], "sender@example.invalid")
        self.assertEqual(sent["Destination"], {"ToAddresses": ["test@example.invalid"]})

    def test_duplicate_send_and_minute_limit_are_atomic(self):
        values = {"id": str(uuid4()), "recipient": "test@example.invalid"}
        for _ in range(3): self.assertEqual(self.call("POST /api/admin/email", values)[0], 200)
        self.ses.send_email.assert_called_once()
        self.assertEqual(self.call("POST /api/admin/email", {**values, "id": str(uuid4())})[0], 429)
        self.assertEqual(common.get("SENDDAY#" + str(int(time.time()) // 86400))["attempts"]["N"], "1")

    def test_overlapping_duplicate_observes_reservation_before_send(self):
        values = {"id": str(uuid4()), "recipient": "test@example.invalid"}
        dynamo = common.client("dynamodb")
        transaction = dynamo.transact_write_items
        duplicates = []
        def interleave(**kwargs):
            result = transaction(**kwargs)
            # A second request arrives after reservation, before SES is called.
            duplicates.append(self.call("POST /api/admin/email", values))
            return result
        with patch.object(dynamo, "transact_write_items", side_effect=interleave):
            self.assertEqual(self.call("POST /api/admin/email", values)[1]["status"], "accepted")
        self.assertEqual(duplicates[0][1]["status"], "sending")
        self.ses.send_email.assert_called_once()

    def test_daily_limit_is_enforced_even_with_stale_ttl_items(self):
        self.db.put_item(Item={"pk": "SENDDAY#" + str(int(time.time()) // 86400), "attempts": 10, "expires": 1})
        self.assertEqual(self.call("POST /api/admin/email", {"id": str(uuid4()), "recipient": "test@example.invalid"})[0], 429)
        self.ses.send_email.assert_not_called()

    def test_minute_boundary_does_not_bypass_sixty_second_cooldown(self):
        now = int(time.time())
        self.db.put_item(Item={"pk": "SENDMIN#" + OWNER, "next_send_at": now + 60, "expires": 1})
        values = {"id": str(uuid4()), "recipient": "test@example.invalid"}
        with patch.object(email.time, "time", return_value=now + 59):
            self.assertEqual(self.call("POST /api/admin/email", values)[0], 429)
        with patch.object(email.time, "time", return_value=now + 60):
            self.assertEqual(self.call("POST /api/admin/email", values)[0], 200)
        self.ses.send_email.assert_called_once()

    def test_ambiguous_ses_failure_never_resends_same_id(self):
        self.ses.send_email.side_effect = EndpointConnectionError(endpoint_url="https://offline.invalid")
        values = {"id": str(uuid4()), "recipient": "test@example.invalid"}
        self.assertEqual(self.call("POST /api/admin/email", values)[1]["status"], "unknown")
        self.assertEqual(self.call("POST /api/admin/email", values)[1]["status"], "unknown")
        self.ses.send_email.assert_called_once()

    def test_email_status_requires_same_owner(self):
        identifier = str(uuid4())
        common.put("EMAIL#" + identifier, {"owner": OTHER, "status": "delivered"}, int(time.time()) + 900)
        self.assertEqual(self.call("GET /api/admin/email", query={"id": identifier})[0], 404)
        self.assertEqual(self.call("POST /api/admin/email", {"id": identifier, "recipient": "test@example.invalid"})[0], 409)

    def event_notification(self, identifier, kind="Delivery", topic=TOPIC):
        return {"Records": [{"EventSource": "aws:sns", "Sns": {"TopicArn": topic, "Message": json.dumps({
            "eventType": kind, "mail": {"messageId": "ses-message", "tags": {
                "test_id": [identifier], "ses:configuration-set": ["energy-demo-aws-admin"]}}})}}]}

    def test_events_are_trusted_idempotent_and_do_not_regress(self):
        identifier = str(uuid4())
        self.call("POST /api/admin/email", {"id": identifier, "recipient": "test@example.invalid"})
        for kind in ["Delivery", "Send", "DeliveryDelay", "Delivery"]:
            events.lambda_handler(self.event_notification(identifier, kind), None)
        self.assertEqual(common.field(common.get("EMAIL#" + identifier), "status"), "delivered")
        events.lambda_handler(self.event_notification(identifier, "Bounce"), None)
        self.assertEqual(common.field(common.get("EMAIL#" + identifier), "status"), "bounced")
        with self.assertRaises(ValueError): events.lambda_handler(self.event_notification(identifier, topic=TOPIC + "-untrusted"), None)

    def test_audit_records_exclude_tokens_and_pii(self):
        self.call()
        audit = [i for i in self.db.scan()["Items"] if i["pk"].startswith("AUDIT#")]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["actor"], OWNER)
        self.assertNotIn(self.token, json.dumps(audit, default=str))

    def test_bad_input_and_method_mismatch(self):
        event = self.event("POST /api/admin/session"); event["body"] = "[1]"
        self.assertEqual(admin.lambda_handler(event, None)["statusCode"], 400)
        event = self.event(); event["requestContext"]["http"]["method"] = "POST"
        self.assertEqual(admin.lambda_handler(event, None)["statusCode"], 404)
