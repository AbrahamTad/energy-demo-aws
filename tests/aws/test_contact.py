"""Offline only: all AWS and HTTP operations mocked."""
import importlib
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
import subprocess
import tempfile
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.exceptions import ReadTimeoutError
from botocore.awsrequest import AWSResponse
import boto3
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lambda/energy"))
import contact_api as api
import contact_jobs as jobs
import contact_admin as admin
import contact_events as events
from energy_validation import ApiError

ID = "f402e590-3f85-42b5-957e-38fc7fa82695"
PK = "CONTACT#" + ID

def failure(code, status=400):
    return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "mock")

class ContactTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, CONTACT_TABLE="contact", CONTACT_ADMIN_EMAIL="admin@example.invalid",
            CONTACT_SENDER="sender@example.invalid", CONTACT_REPLY_TO="", CONTACT_SENDER_DISPLAY_NAME="EnergyDemo Support", CONTACT_SES_CONFIG="contact-config",
            CONTACT_EMAIL_SENDING_ENABLED="true", CONTACT_ORIGIN_TOKEN_SHA256=hashlib.sha256(("a"*64).encode()).hexdigest(),
            CONTACT_CUSTOMER_EMAIL_ENABLED="false", CONTACT_HOSTNAMES='["energy.example.invalid"]',
            CONTACT_SITE_ORIGIN="https://energy.example.invalid",
            CONTACT_QUEUE_URL="queue", CONTACT_TOPIC_ARN="topic")
        self.env.start(); self.addCleanup(self.env.stop)
        self.data = {"id": ID, "name": "Reader", "email": "reader@example.invalid", "subject": "Question",
            "message": "Hello <script>not executable</script>", "website": "", "botToken": "test-token"}
        self.event = {"routeKey": "POST /api/contact", "requestContext": {"http": {"method": "POST", "sourceIp": "192.0.2.1"}},
            "headers": {"content-type": "application/json", "x-energy-contact-origin": "a"*64, "x-energy-contact-ip": "192.0.2.1"}, "body": json.dumps(self.data)}
        self.item = {"pk": PK, "sk": "META", "id": ID, "name": "Reader", "email": "reader@example.invalid",
            "subject": "Question", "message": "Hello", "created": 100, "expires": int(time.time()) + 100,
            "status": "new", "version": 1}
        self.job = {"pk": PK, "sk": "JOB#customer", "kind": "customer", "state": "pending", "expires": int(time.time()) + 100}

    def test_direct_api_and_forged_origin_rejected_before_limits_or_bot_check(self):
        for header in [{}, {"x-energy-contact-origin": "b"*64},
                       {"x-energy-contact-origin": "a"*64, "x-energy-contact-ip": "1.2.3.4,5.6.7.8"},
                       {"x-energy-contact-origin": "a"*64, "x-energy-contact-ip": "fe80::1%eth0"}]:
            with self.subTest(header=header), patch.object(api, "budget") as budget, patch.object(api, "verify_bot") as bot:
                with self.assertRaises(ApiError) as error:
                    api.submit({**self.event, "headers": {"content-type": "application/json", **header}})
                self.assertEqual(error.exception.status, 403)
                budget.assert_not_called()
                bot.assert_not_called()
        headers = {**self.event["headers"], "x-energy-contact-ip": "2001:0db8::1"}
        self.assertEqual(api.viewer_ip(headers), "2001:db8::1")
        headers["x-energy-contact-ip"] = "::ffff:192.0.2.1"
        self.assertEqual(api.viewer_ip(headers), "192.0.2.1")

    def test_no_send_flag_blocks_both_kinds_without_db_or_ses(self):
        for setting in ["", "false", "TRUE"]:
            for kind in ["admin", "customer"]:
                with self.subTest(setting=setting, kind=kind), patch.dict(os.environ, CONTACT_EMAIL_SENDING_ENABLED=setting), patch.object(jobs, "get") as get, patch.object(jobs, "ses_client") as client:
                    with self.assertRaises(RuntimeError): jobs.send(PK, "JOB#"+kind)
                    get.assert_not_called()
                    client.assert_not_called()
                    response = jobs.worker({"Records": [{"messageId": "fixture", "body": json.dumps({"pk": PK, "sk": "JOB#"+kind})}]}, None)
                    self.assertEqual(response, {"batchItemFailures": [{"itemIdentifier": "fixture"}]})

    def test_no_send_reconciliation_monitors_without_enqueueing(self):
        now = int(time.time())
        rows = [{**self.job, "created": now-901},
                {**self.job, "state": "accepted", "claimed_at": now-3601},
                {**self.job, "state": "delayed", "claimed_at": now-3601},
                {**self.job, "state": "accepted", "claimed_at": now-30},
                {**self.job, "state": "delivered", "claimed_at": now-3601}]
        with patch.dict(os.environ, CONTACT_EMAIL_SENDING_ENABLED="false"), patch.object(jobs, "get", return_value=None), patch.object(jobs, "db") as db, patch.object(jobs, "metrics") as metric, patch.object(jobs.boto3, "client") as client:
            db.return_value.scan.return_value = {"Items": rows}
            jobs.relay({"source": "aws.events"}, None)
            metric.assert_called_once_with(ReconcileSuccess=1, UncertainJobs=0, FailedJobs=0, PendingJobs=1, UnconfirmedJobs=2)
            client.assert_not_called()
            self.assertEqual(jobs.relay({"Records": []}, None), {"batchItemFailures": []})

    def test_sender_and_reply_to_apply_to_both_email_kinds(self):
        for kind in ["customer", "admin"]:
            with self.subTest(kind=kind), patch.dict(os.environ, CONTACT_CUSTOMER_EMAIL_ENABLED="true", CONTACT_REPLY_TO="support@example.invalid"), patch.object(jobs, "get", side_effect=[{**self.job, "kind": kind}, self.item, None]), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "db"), patch.object(jobs, "state"), patch.object(jobs, "ses_client") as client:
                client.return_value.send_email.return_value = {"MessageId": "fixture"}
                jobs.send(PK, "JOB#"+kind)
                sent = client.return_value.send_email.call_args.kwargs
                self.assertEqual(sent["FromEmailAddress"], "EnergyDemo Support <sender@example.invalid>")
                self.assertEqual(sent["ReplyToAddresses"], ["support@example.invalid"])
                self.assertEqual(sent["Destination"]["ToAddresses"], [self.item["email"] if kind == "customer" else "admin@example.invalid"])
                self.assertEqual(sent["ConfigurationSetName"], "contact-config")

    def test_approved_gmail_configuration_produces_requested_headers(self):
        with patch.dict(os.environ, CONTACT_SENDER="eshkim1@gmail.com", CONTACT_REPLY_TO="eshkim1@gmail.com"):
            self.assertEqual(jobs.email_headers(), ("EnergyDemo Support <eshkim1@gmail.com>", "eshkim1@gmail.com"))

    def test_verified_sandbox_acknowledgment_does_not_call_admin_dashboard(self):
        # Composition/worker independence only: deployment still requires the reviewed Admin prerequisites.
        with patch.dict(os.environ, CONTACT_SENDER="eshkim1@gmail.com", CONTACT_REPLY_TO="eshkim1@gmail.com",
                        CONTACT_ADMIN_EMAIL="karlcederqvist@gmail.com", CONTACT_CUSTOMER_EMAIL_ENABLED="false",
                        CONTACT_SITE_ORIGIN="", CONTACT_HOSTNAMES="[]"), \
                patch.object(jobs, "get", side_effect=[{**self.job, "kind": "customer"},
                                                      {**self.item, "email": "eshkim1@gmail.com"}, None]), \
                patch.object(jobs, "digest", return_value="fixture-hash"), \
                patch.object(jobs, "db"), patch.object(jobs, "state"), \
                patch.object(admin, "identity") as admin_identity, patch.object(jobs, "ses_client") as client:
            client.return_value.get_email_identity.return_value = {"VerifiedForSendingStatus": True}
            client.return_value.send_email.return_value = {"MessageId": "fixture-only"}
            jobs.send(PK, "JOB#customer")
            client.return_value.get_email_identity.assert_called_once_with(EmailIdentity="eshkim1@gmail.com")
            client.return_value.send_email.assert_called_once()
            sent = client.return_value.send_email.call_args.kwargs
            self.assertEqual(sent["FromEmailAddress"], "EnergyDemo Support <eshkim1@gmail.com>")
            self.assertEqual(sent["ReplyToAddresses"], ["eshkim1@gmail.com"])
            self.assertEqual(sent["Destination"]["ToAddresses"], ["eshkim1@gmail.com"])
            self.assertIn(ID, sent["Content"]["Simple"]["Body"]["Text"]["Data"])
            self.assertNotIn(self.item["message"], sent["Content"]["Simple"]["Body"]["Text"]["Data"])
            admin_identity.assert_not_called()

    def test_reply_to_defaults_to_configured_sender_and_display_name_is_quoted_safely(self):
        self.assertEqual(jobs.email_headers(), ("EnergyDemo Support <sender@example.invalid>", "sender@example.invalid"))
        from email.utils import parseaddr
        with patch.dict(os.environ, CONTACT_SENDER="alternate@example.invalid", CONTACT_SENDER_DISPLAY_NAME='EnergyDemo, "Support"'):
            sender, reply = jobs.email_headers()
            self.assertEqual(parseaddr(sender), ('EnergyDemo, "Support"', 'alternate@example.invalid'))
            self.assertEqual(reply, "alternate@example.invalid")
            self.assertNotIn("\n", sender)

    def test_header_injection_and_multiple_mailboxes_fail_before_claim_or_ses(self):
        for key in ["CONTACT_SENDER", "CONTACT_REPLY_TO", "CONTACT_SENDER_DISPLAY_NAME"]:
            invalid = ["support@example.invalid\r\nBcc: victim@example.invalid", "bad\nheader", "bad\x00header", "bad\x7fheader", "bad\u2028header"]
            if key != "CONTACT_SENDER_DISPLAY_NAME":
                invalid += ["Person <support@example.invalid>", "one@example.invalid,two@example.invalid", "one@example.invalid;two@example.invalid", "support@example.invalid (comment)", "one@@example.invalid", "support@example.invalid ", "support@localhost", ""]
                if key == "CONTACT_REPLY_TO": invalid.remove("")  # Empty selects the configured sender.
            else:
                invalid += ["", "   ", "x"*81]
            for value in invalid:
                with self.subTest(key=key, value=repr(value)), patch.object(jobs.os, "environ", {**os.environ, key: value}), patch.object(jobs, "get", side_effect=[{**self.job, "kind": "admin"}, self.item]), patch.object(jobs, "db") as db, patch.object(jobs, "ses_client") as client:
                    with self.assertRaises(ValueError): jobs.send(PK, "JOB#admin")
                    db.assert_not_called()
                    client.assert_not_called()

    def test_validation_rejects_headers_extra_fields_size_and_honeypot(self):
        for field, value in [("email", "victim@example.invalid\r\nBcc:other@example.invalid"), ("name", ""),
                             ("message", "x" * 5001), ("website", "spam"), ("id", "bad")]:
            with self.subTest(field=field):
                data = {**self.data, field: value}
                with self.assertRaises(ApiError): api.validate({**self.event, "body": json.dumps(data)})
        with self.assertRaises(ApiError): api.validate({**self.event, "body": json.dumps({**self.data, "owner": "spoof"})})

    def test_turnstile_requires_success_hostname_and_action(self):
        with patch.object(api, "secrets", return_value={"turnstile_secret": "mock"}), patch.object(api.urllib.request, "urlopen") as call:
            for result in [{"success": False}, {"success": True, "hostname": "attacker", "action": "contact"},
                           {"success": True, "hostname": "energy.example.invalid", "action": "other"}]:
                call.return_value.__enter__.return_value.read.return_value = json.dumps(result).encode()
                with self.assertRaises(ApiError): api.verify_bot("token")
            call.return_value.__enter__.return_value.read.return_value = json.dumps({"success": True, "hostname": "energy.example.invalid", "action": "contact"}).encode()
            api.verify_bot("token")

    def test_atomic_inquiry_and_two_outbox_jobs_no_send(self):
        with patch.object(api, "budget"), patch.object(api, "verify_bot"), patch.object(api, "digest", return_value="hash"), patch.object(api, "get", return_value=None), patch.object(api.boto3, "client") as client:
            result = api.submit(self.event)
            self.assertEqual(result["statusCode"], 202)
            tx = client.return_value.transact_write_items.call_args.kwargs["TransactItems"]
            self.assertEqual(len(tx), 3)
            self.assertTrue(all(x["Put"]["ConditionExpression"] == "attribute_not_exists(pk)" for x in tx))
            client.return_value.send_email.assert_not_called()

    def test_idempotency_and_conflict(self):
        with patch.object(api, "budget"), patch.object(api, "verify_bot"), patch.object(api, "digest", return_value="hash"), patch.object(api, "get", return_value={**self.item, "fingerprint": "hash"}), patch.object(api.boto3, "client") as c:
            self.assertEqual(api.submit(self.event)["statusCode"], 202)
            c.assert_not_called()
        with patch.object(api, "budget"), patch.object(api, "verify_bot"), patch.object(api, "digest", return_value="hash"), patch.object(api, "get", return_value={**self.item, "fingerprint": "different"}):
            with self.assertRaises(ApiError) as error: api.submit(self.event)
            self.assertEqual(error.exception.status, 409)

    def test_atomic_budget_fails_closed(self):
        with patch.object(api, "db") as db:
            db.return_value.update_item.side_effect = failure("ConditionalCheckFailedException")
            with self.assertRaises(ApiError) as error: api.budget("IP#hash", 10, 3600)
            self.assertEqual(error.exception.status, 429)
            self.assertIn("ConditionExpression", db.return_value.update_item.call_args.kwargs)

    def test_unknown_exception_is_sanitized(self):
        with patch.object(api, "budget", side_effect=RuntimeError("private details")), patch.object(api, "digest", return_value="hash"):
            result = api.lambda_handler(self.event, None)
            self.assertEqual(result["statusCode"], 503)
            self.assertNotIn("private details", result["body"])

    def test_relay_only_job_keys_no_pii(self):
        event = {"Records": [{"eventName": "INSERT", "dynamodb": {"Keys": {"pk": {"S": PK}, "sk": {"S": "JOB#customer"}}, "SequenceNumber": "1"}}]}
        with patch.object(jobs.boto3, "client") as c:
            self.assertEqual(jobs.relay(event, None)["batchItemFailures"], [])
            sent = c.return_value.send_message.call_args.kwargs
            self.assertEqual(json.loads(sent["MessageBody"]), {"pk": PK, "sk": "JOB#customer"})
            self.assertNotIn("email", sent["MessageBody"])

    def test_relay_failure_checkpoint(self):
        event = {"Records": [{"eventName": "INSERT", "dynamodb": {"Keys": {"pk": {"S": PK}, "sk": {"S": "JOB#admin"}}, "SequenceNumber": "1"}}]}
        with patch.object(jobs.boto3, "client") as c:
            c.return_value.send_message.side_effect = RuntimeError()
            self.assertEqual(jobs.relay(event, None)["batchItemFailures"], [{"itemIdentifier": "1"}])

    def test_sandbox_unverified_does_not_send_or_drop_inquiry(self):
        with patch.object(jobs, "get", side_effect=[self.job, self.item, None]), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "db") as db, patch.object(jobs.boto3, "client") as c:
            c.return_value.get_email_identity.side_effect = failure("NotFoundException")
            jobs.send(PK, "JOB#customer")
            c.return_value.send_email.assert_not_called()
            self.assertEqual(db.return_value.update_item.call_args.kwargs["ExpressionAttributeValues"][":s"], "sandbox_blocked")

    def test_fixed_templates_and_ambiguous_send_not_retried(self):
        with patch.object(jobs, "get", side_effect=[{**self.job, "kind": "admin"}, self.item, None]), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "db"), patch.object(jobs, "state") as state, patch.object(jobs.boto3, "client") as c:
            c.return_value.send_email.side_effect = EndpointConnectionError(endpoint_url="mock")
            jobs.send(PK, "JOB#admin")
            state.assert_called_once_with(PK, "JOB#admin", "unknown")
            sent = c.return_value.send_email.call_args.kwargs
            self.assertEqual(sent["FromEmailAddress"], "EnergyDemo Support <sender@example.invalid>")
            self.assertEqual(sent["Destination"], {"ToAddresses": ["admin@example.invalid"]})
            body = sent["Content"]["Simple"]["Body"]["Text"]["Data"]
            self.assertNotIn("Hello", body)
            self.assertIn("https://energy.example.invalid/#/admin/messages", body)
        with patch.object(jobs, "get", side_effect=[{**self.job, "state": "sending"}, self.item]), patch.object(jobs.boto3, "client") as c:
            jobs.send(PK, "JOB#customer")
            c.assert_not_called()

    def test_worker_acknowledgment_excludes_customer_message(self):
        with patch.dict(os.environ, CONTACT_CUSTOMER_EMAIL_ENABLED="true"), patch.object(jobs, "get", side_effect=[self.job, self.item, None]), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "db"), patch.object(jobs, "state"), patch.object(jobs.boto3, "client") as c:
            c.return_value.send_email.return_value = {"MessageId": "mock"}
            jobs.send(PK, "JOB#customer")
            text = c.return_value.send_email.call_args.kwargs["Content"]["Simple"]["Body"]["Text"]["Data"]
            for key in ["name", "email", "subject", "message"]:
                self.assertNotIn(self.item[key], text)
            self.assertIn(ID, text)

    def test_contact_templates_use_only_safe_reference_and_fixed_admin_link(self):
        customer_subject, customer_body = jobs.email_content(ID, "customer")
        self.assertEqual(customer_subject, "EnergyDemo — We received your inquiry")
        self.assertIn("Thank you for contacting EnergyDemo.", customer_body)
        self.assertIn("We have received your inquiry", customer_body)
        self.assertIn(ID, customer_body)
        self.assertNotIn("https://", customer_body)
        self.assertNotIn("within", customer_body.lower())
        self.assertEqual(jobs.email_content(ID, "admin"), ("EnergyDemo — New inquiry",
            f"Inquiry reference: {ID}\nEnergyDemo admin messages: https://energy.example.invalid/#/admin/messages"))
        with patch.dict(os.environ, CONTACT_SITE_ORIGIN="https://energy.example.invalid/"):
            self.assertEqual(jobs.email_content(ID, "admin")[1].splitlines()[1],
                "EnergyDemo admin messages: https://energy.example.invalid/#/admin/messages")

    def test_admin_notification_does_not_copy_customer_fields_or_put_reference_in_url(self):
        private = {**self.item, "name": "PRIVATE_NAME", "email": "private-address@example.invalid",
            "subject": "PRIVATE_SUBJECT", "message": "PRIVATE_BODY access_token=PRIVATE_TOKEN"}
        with patch.object(jobs, "get", side_effect=[{**self.job, "kind": "admin"}, private, None]), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "db"), patch.object(jobs, "state"), patch.object(jobs, "ses_client") as client:
            client.return_value.send_email.return_value = {"MessageId": "mock"}
            jobs.send(PK, "JOB#admin")
            sent = client.return_value.send_email.call_args.kwargs
            content = json.dumps(sent["Content"])
            for value in [private[k] for k in ["name", "email", "subject", "message"]] + ["PRIVATE_TOKEN"]:
                self.assertNotIn(value, content)
            self.assertEqual(sent["Destination"], {"ToAddresses": ["admin@example.invalid"]})
            url = sent["Content"]["Simple"]["Body"]["Text"]["Data"].splitlines()[1].split(": ", 1)[1]
            self.assertEqual(url, "https://energy.example.invalid/#/admin/messages")
            self.assertNotIn(ID, url)
            self.assertNotIn("?", url)

    def test_admin_link_rejects_unsafe_configuration_before_job_claim(self):
        for origin in ["", "http://energy.example.invalid", "https://attacker.invalid",
                       "https://energy.example.invalid.attacker.invalid", "https://user:token@energy.example.invalid",
                       "https://energy.example.invalid:443", "https://energy.example.invalid/private",
                       "https://energy.example.invalid?token=secret", "https://energy.example.invalid?",
                       "https://energy.example.invalid#secret", "https://energy.example.invalid#",
                       "https://energy.example.invalid\r\nInjected: yes"]:
            with self.subTest(origin=origin), patch.dict(os.environ, CONTACT_SITE_ORIGIN=origin), patch.object(jobs, "get", side_effect=[{**self.job, "kind": "admin"}, self.item]), patch.object(jobs, "db") as db, patch.object(jobs, "ses_client") as client:
                with self.assertRaises(ValueError): jobs.send(PK, "JOB#admin")
                db.assert_not_called()
                client.assert_not_called()

    def test_email_reference_rejects_template_injection(self):
        for kind in ["customer", "admin"]:
            for reference in ["not-a-reference", ID+"\nBcc: victim@example.invalid", "<script>private</script>"]:
                with self.subTest(kind=kind, reference=reference), self.assertRaises(ApiError):
                    jobs.email_content(reference, kind)

    def test_admin_denied_before_database_access(self):
        with patch.object(admin, "identity", side_effect=ApiError(403, "denied")), patch.object(admin, "db") as db:
            result = admin.lambda_handler({"routeKey": "GET /api/admin/messages"}, None)
            self.assertEqual(result["statusCode"], 403); db.assert_not_called()

    def test_admin_list_paginates_and_redacts_pii(self):
        with patch.object(admin, "identity", return_value=({"sub": "operator"}, None)), patch.object(admin, "db") as db, patch.object(admin, "get", return_value=self.item):
            db.return_value.query.return_value = {"Items": [{"pk": PK}], "LastEvaluatedKey": {"order": "1000000000#" + ID}}
            result = json.loads(admin.manage({"routeKey": "GET /api/admin/messages"})["body"])
            self.assertNotIn("email", result["messages"][0]); self.assertNotIn("message", result["messages"][0])
            self.assertTrue(result["next_cursor"])

    def test_admin_status_version_conflict(self):
        with patch.object(admin, "identity", return_value=({"sub": "operator"}, None)), patch.object(admin, "get", return_value=self.item), patch.object(admin, "db") as db:
            db.return_value.update_item.side_effect = failure("ConditionalCheckFailedException")
            result = admin.lambda_handler({"routeKey": "POST /api/admin/messages/{id}/status", "pathParameters": {"id": ID}, "body": json.dumps({"status": "resolved", "version": 1})}, None)
            self.assertEqual(result["statusCode"], 409)

    def test_delivery_events_reject_untrusted_source(self):
        with patch.object(events, "db") as db:
            with self.assertRaises(ValueError): events.lambda_handler({"Records": [{"EventSource": "aws:sns", "Sns": {"TopicArn": "other"}}]}, None)
            db.assert_not_called()

    def test_delivery_duplicate_condition_and_suppression(self):
        value = {"eventType": "Bounce", "bounce": {"bounceType": "Permanent"}, "mail": {"tags": {"ses:configuration-set": ["contact-config"], "contact_id": [ID], "contact_kind": ["customer"]}}}
        with patch.object(events, "get", side_effect=[self.job, self.item]), patch.object(events, "digest", return_value="hash"), patch.object(events, "db") as db:
            events.lambda_handler({"Records": [{"EventSource": "aws:sns", "Sns": {"TopicArn": "topic", "Message": json.dumps(value)}}]}, None)
            self.assertIn("event_rank < :rank", db.return_value.update_item.call_args.kwargs["ConditionExpression"])
            self.assertEqual(db.return_value.put_item.call_args.kwargs["Item"]["pk"], "SUPPRESS#hash")


    def ses_event(self, event_type="Bounce", bounce_type="Permanent"):
        value = {"eventType": event_type, "bounce": {"bounceType": bounce_type}, "mail": {"tags": {
            "ses:configuration-set": ["contact-config"], "contact_id": [ID], "contact_kind": ["customer"]}}}
        return {"Records": [{"EventSource": "aws:sns", "Sns": {"TopicArn": "topic", "Message": json.dumps(value)}}]}

    def test_transient_and_undetermined_bounces_do_not_suppress(self):
        for kind in ["Transient", "Undetermined", ""]:
            with self.subTest(kind=kind), patch.object(events, "get", return_value=self.job), patch.object(events, "db") as db:
                events.lambda_handler(self.ses_event(bounce_type=kind), None)
                db.return_value.put_item.assert_not_called()
                self.assertEqual(db.return_value.update_item.call_args.kwargs["ExpressionAttributeValues"][":s"], "bounced")

    def test_complaints_suppress_and_partial_failure_is_recoverable(self):
        payload = self.ses_event("Complaint")
        with patch.object(events, "get", side_effect=[self.job, self.item] * 2), patch.object(events, "digest", return_value="hash"), patch.object(events, "db") as db:
            db.return_value.put_item.side_effect = [failure("InternalServerError", 500), {}]
            with self.assertRaises(ClientError): events.lambda_handler(payload, None)
            # First attempt stored the rank before suppression failed. Retry must still suppress.
            db.return_value.update_item.side_effect = failure("ConditionalCheckFailedException")
            events.lambda_handler(payload, None)
            self.assertEqual(db.return_value.put_item.call_count, 2)

    def test_dlq_formats_recover_through_same_trust_and_idempotency_checks(self):
        payload = self.ses_event()
        original = json.loads(payload["Records"][0]["Sns"]["Message"])
        envelope = {"Type": "Notification", "TopicArn": "topic", "Message": json.dumps(original)}
        for source, body in [("sns", original), ("sns", envelope), ("lambda", {"requestPayload": payload})]:
            with self.subTest(source=source), patch.object(events, "get", side_effect=[self.job, self.item]), patch.object(events, "digest", return_value="hash"), patch.object(events, "db") as db:
                recovered = events.recovery_payload(body, source)
                events.lambda_handler(recovered, None)
                db.return_value.put_item.assert_called_once()
        with self.assertRaises(ValueError):
            events.recovery_payload({"requestPayload": {"Records": [{"EventSource": "aws:sns", "Sns": {"TopicArn": "other"}}]}}, "lambda")
        with self.assertRaises(ValueError): events.recovery_payload({}, "sns")
        with self.assertRaises(ValueError): events.recovery_payload({**envelope, "TopicArn": "other"}, "sns")

    def test_recovery_cli_is_local_private_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/"body.json", Path(directory)/"replay.json"
            source.write_text(self.ses_event()["Records"][0]["Sns"]["Message"])
            command = [sys.executable, "-B", str(Path(__file__).resolve().parents[2]/"scripts/aws/contact_recover_events.py"),
                "--source", "sns", "--input", str(source), "--output", str(target), "--topic-arn", "topic", "--configuration-set", "contact-config"]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertNotIn(ID, result.stdout)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            original = target.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(target.read_bytes(), original)

    def test_accepted_email_followed_by_persistence_failure_is_not_sent_again(self):
        with mock_aws(), patch.dict(os.environ, AWS_DEFAULT_REGION="eu-north-1"):
            table = boto3.resource("dynamodb").create_table(TableName="contact",
                KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST")
            table.put_item(Item={**self.job, "kind": "admin"})
            table.put_item(Item=self.item)
            def read(pk, sk="META"):
                return table.get_item(Key={"pk": pk, "sk": sk}).get("Item")
            with patch.object(jobs, "get", side_effect=read), patch.object(jobs, "db", return_value=table), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "ses_client") as client:
                client.return_value.send_email.return_value = {"MessageId": "accepted-but-not-persisted"}
                update = table.update_item
                def throttle_acceptance_write(**kwargs):
                    if kwargs.get("ExpressionAttributeValues", {}).get(":state") == "accepted":
                        raise failure("ThrottlingException")
                    return update(**kwargs)
                with patch.object(table, "update_item", side_effect=throttle_acceptance_write):
                    with self.assertRaises(ClientError): jobs.send(PK, "JOB#customer")
                claimed = read(PK, "JOB#customer")
                self.assertEqual(claimed["state"], "sending")
                self.assertIn("claimed_at", claimed)
                jobs.send(PK, "JOB#customer")
                client.return_value.send_email.assert_called_once()
            # A stale worker that saw pending before the claim must not erase uncertainty.
            table.update_item(Key={"pk": PK, "sk": "JOB#customer"},
                UpdateExpression="SET #s=:s", ExpressionAttributeNames={"#s": "state"},
                ExpressionAttributeValues={":s": "unknown"})
            with patch.object(jobs, "get", side_effect=[self.job, self.item, {"expires": int(time.time())+100}]), patch.object(jobs, "db", return_value=table), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "ses_client") as client:
                jobs.send(PK, "JOB#customer")
                self.assertEqual(read(PK, "JOB#customer")["state"], "unknown")
                client.assert_not_called()

    def test_reconciler_recovers_only_pending_and_reports_stuck_jobs_without_pii(self):
        now = int(time.time())
        rows = [{**self.job, "pk": PK, "sk": "JOB#customer", "state": state, "claimed_at": claimed}
            for state, claimed in [("pending", now), ("sending", now-301), ("unknown", now), ("sending", now)]]
        rows.append({**rows[0], "expires": now-1})
        with patch.object(jobs, "get", return_value=None), patch.object(jobs, "db") as db, patch.object(jobs.boto3, "client") as client, patch("builtins.print") as output:
            db.return_value.scan.return_value = {"Items": rows}
            jobs.relay({"source": "aws.events"}, None)
            client.return_value.send_message.assert_called_once()
            metric = json.loads(output.call_args.args[0])
            self.assertEqual(metric["UncertainJobs"], 2)
            self.assertEqual(metric["FailedJobs"], 0)
            self.assertEqual(metric["ReconcileSuccess"], 1)
            self.assertNotIn(ID, output.call_args.args[0])
            self.assertNotIn("email", output.call_args.args[0])

    def test_reconciliation_failure_does_not_advance_cursor_or_emit_success(self):
        with patch.object(jobs, "get", return_value={"cursor": {"pk": "cursor", "sk": "META"}}), patch.object(jobs, "db") as db, patch.object(jobs, "metrics") as metric:
            db.return_value.scan.side_effect = failure("InternalServerError", 500)
            with self.assertRaises(ClientError): jobs.relay({"source": "aws.events"}, None)
            db.return_value.put_item.assert_not_called()
            metric.assert_not_called()

    def test_partial_sweep_carries_uncertainty_and_never_clears_alarm(self):
        cursor = {"pk": "cursor", "sk": "META"}
        with patch.object(jobs, "get", return_value={"cursor": cursor, "uncertain": 2}), patch.object(jobs, "db") as db, patch.object(jobs, "metrics") as metric:
            db.return_value.scan.return_value = {"Items": [], "LastEvaluatedKey": cursor}
            jobs.relay({"source": "aws.events"}, None)
            metric.assert_called_once_with(UncertainJobs=2, ReconcileSuccess=1)
            self.assertEqual(db.return_value.put_item.call_args.kwargs["Item"]["uncertain"], 2)
        with patch.object(jobs, "get", return_value=None), patch.object(jobs, "db") as db, patch.object(jobs, "metrics") as metric:
            db.return_value.scan.return_value = {"Items": [], "LastEvaluatedKey": cursor}
            jobs.relay({"source": "aws.events"}, None)
            metric.assert_called_once_with(ReconcileSuccess=1)

    def test_reconciler_checkpoints_before_time_budget_is_exhausted(self):
        cursor = {"pk": "cursor", "sk": "META"}
        context = MagicMock()
        context.get_remaining_time_in_millis.return_value = 7000
        with patch.object(jobs, "get", return_value=None), patch.object(jobs, "db") as db, patch.object(jobs, "metrics"):
            db.return_value.scan.return_value = {"Items": [], "LastEvaluatedKey": cursor}
            jobs.relay({"source": "aws.events"}, context)
            db.return_value.scan.assert_called_once()
            self.assertEqual(db.return_value.put_item.call_args.kwargs["Item"]["cursor"], cursor)

    def test_uncertain_jobs_are_never_automatically_sent(self):
        for status in ["sending", "unknown"]:
            with self.subTest(status=status), patch.object(jobs, "get", side_effect=[{**self.job, "state": status}, self.item]), patch.object(jobs, "ses_client") as client:
                jobs.send(PK, "JOB#customer")
                client.assert_not_called()

    def test_accepted_email_persistence_errors_are_not_ses_rejections(self):
        for error in [failure("ThrottlingException"), failure("ProvisionedThroughputExceededException"),
                      EndpointConnectionError(endpoint_url="mock"), RuntimeError("persistence interruption")]:
            with self.subTest(error=type(error).__name__), patch.object(jobs, "get", side_effect=[{**self.job, "kind": "admin"}, self.item, None]), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "db"), patch.object(jobs, "ses_client") as client, patch.object(jobs, "state", side_effect=error) as state:
                client.return_value.send_email.return_value = {"MessageId": "accepted"}
                with self.assertRaises(type(error)): jobs.send(PK, "JOB#admin")
                state.assert_called_once_with(PK, "JOB#admin", "accepted", "accepted")
                client.return_value.send_email.assert_called_once()

    def test_failed_delivery_sweep_excludes_expired_and_successful_jobs(self):
        rows = [{**self.job, "pk": PK, "sk": "JOB#customer", "state": status}
            for status in ["failed", "bounced", "complaint", "delivered", "suppressed", "sandbox_blocked"]]
        rows.append({**rows[0], "expires": int(time.time())-1})
        with patch.object(jobs, "get", return_value=None), patch.object(jobs, "db") as db, patch.object(jobs, "metrics") as metric, patch.object(jobs, "ses_client") as client:
            db.return_value.scan.return_value = {"Items": rows}
            jobs.relay({"source": "aws.events"}, None)
            metric.assert_called_once_with(UncertainJobs=0, FailedJobs=3, PendingJobs=0, UnconfirmedJobs=0, ReconcileSuccess=1)
            self.assertEqual(db.return_value.put_item.call_args.kwargs["Item"]["failed"], 0)
            client.assert_not_called()

    def test_failed_count_survives_partial_sweep_and_clean_pages_do_not_clear_alarm(self):
        cursor = {"pk": "cursor", "sk": "META"}
        with patch.object(jobs, "get", return_value={"cursor": cursor, "failed": 2}), patch.object(jobs, "db") as db, patch.object(jobs, "metrics") as metric:
            db.return_value.scan.return_value = {"Items": [], "LastEvaluatedKey": cursor}
            jobs.relay({"source": "aws.events"}, None)
            metric.assert_called_once_with(FailedJobs=2, ReconcileSuccess=1)
            self.assertEqual(db.return_value.put_item.call_args.kwargs["Item"]["failed"], 2)

    def test_terminal_send_rejection_emits_aggregate_failure_metric(self):
        with patch.object(jobs, "db"), patch.object(jobs, "metrics") as metric:
            jobs.state(PK, "JOB#customer", "failed")
            metric.assert_called_once_with(FailedJobs=1)

    def test_newer_ses_event_prevents_stale_worker_failure_alarms(self):
        for status in ["unknown", "failed"]:
            with self.subTest(status=status), patch.object(jobs, "db") as db, patch.object(jobs, "metrics") as metric:
                db.return_value.update_item.side_effect = failure("ConditionalCheckFailedException")
                jobs.state(PK, "JOB#customer", status)
                metric.assert_not_called()

    def test_rate_windows_limits_and_key_isolation_with_dynamodb(self):
        with mock_aws(), patch.dict(os.environ, AWS_DEFAULT_REGION="eu-north-1"):
            table = boto3.resource("dynamodb").create_table(TableName="contact",
                KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST")
            for key, limit, period in [("IP#one", 10, 3600), ("ADDRESS#one", 3, 86400), ("SUBMISSIONS", 30, 86400)]:
                with self.subTest(key=key), patch.object(api, "db", return_value=table):
                    with patch.object(api.time, "time", return_value=1700000000):
                        for _ in range(limit): api.budget(key, limit, period)
                        with self.assertRaises(ApiError) as error: api.budget(key, limit, period)
                        self.assertEqual(error.exception.status, 429)
                        api.budget(key+"#independent", limit, period)
                    with patch.object(api.time, "time", return_value=1700000000+period):
                        api.budget(key, limit, period)  # New window works before old TTL rows are deleted.

    def test_submission_ignores_forwarded_ip_and_normalizes_address_for_limits(self):
        data = {**self.data, "email": "Reader@Example.Invalid"}
        event = {**self.event, "body": json.dumps(data), "headers": {**self.event["headers"], "x-forwarded-for": "203.0.113.99"}}
        with patch.object(api, "budget") as budget, patch.object(api, "verify_bot"), patch.object(api, "digest", side_effect=lambda value: "hash:"+value), patch.object(api, "get", return_value=None), patch.object(api.boto3, "client"):
            api.submit(event)
            self.assertEqual(budget.call_args_list[0].args, ("IP#hash:192.0.2.1", 10, 3600))
            self.assertEqual(budget.call_args_list[1].args, ("ADDRESS#hash:reader@example.invalid", 3, 86400))
            self.assertEqual(budget.call_args_list[2].args, ("SUBMISSIONS", 30, 86400))

    def test_explicit_throttle_returns_to_pending_for_queue_retry(self):
        with patch.object(jobs, "get", side_effect=[{**self.job, "kind": "admin"}, self.item, None]), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "db"), patch.object(jobs, "state") as state, patch.object(jobs, "ses_client") as client:
            client.return_value.send_email.side_effect = failure("TooManyRequestsException", 429)
            with self.assertRaises(RuntimeError): jobs.send(PK, "JOB#admin")
            state.assert_called_once_with(PK, "JOB#admin", "pending")

    def test_real_sdk_transport_never_retries_5xx_or_uncertain_acceptance(self):
        session = boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing", region_name="eu-north-1")
        with patch.object(jobs.boto3, "client", side_effect=session.client):
            client = jobs.ses_client()
        self.assertEqual(client.meta.config.retries["total_max_attempts"], 1)
        self.assertEqual((client.meta.config.connect_timeout, client.meta.config.read_timeout), (2, 5))

        class Raw:
            def stream(self, amt=None, decode_content=False):
                yield b'{"message":"simulated server error"}'

        for transport in [AWSResponse("https://mock.invalid", 500, {"content-type": "application/json"}, Raw()),
                          ReadTimeoutError(endpoint_url="https://mock.invalid")]:
            with self.subTest(transport=type(transport).__name__), patch.object(client._endpoint.http_session, "send") as http, patch.object(jobs, "ses_client", return_value=client), patch.object(jobs, "get", side_effect=[{**self.job, "kind": "admin"}, self.item, None]), patch.object(jobs, "digest", return_value="hash"), patch.object(jobs, "db"), patch.object(jobs, "state") as state:
                if isinstance(transport, Exception): http.side_effect = transport
                else: http.return_value = transport
                jobs.send(PK, "JOB#admin")
                self.assertEqual(http.call_count, 1)
                state.assert_called_once_with(PK, "JOB#admin", "unknown")

if __name__ == "__main__": unittest.main()
