"""Offline preparation checks: all GitHub reads/writes are mocked."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/aws"))
compat = importlib.import_module("github_compatibility")


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.value = {"kind": "github-only-compatibility", "run_id": "123", "commit": "a" * 40, "nonce": "b" * 32}
        self.checksum = "c" * 64
        self.env = patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_SHA": "a" * 40,
            "PLAN_SHA256": self.checksum}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.record = {"id": 81, "payload": {"plan_run_id": "123", "apply_run_id": "123", "sha256": self.checksum}}

    def test_missing_invalid_approval_before_any_api_or_fixture(self):
        for value in ["", "wrong"]:
            with patch.dict(os.environ, {"COMPAT_CONFIRMATION": value}), patch.object(compat.gate, "get") as api:
                with self.assertRaises(ValueError): compat.context()
                api.assert_not_called()

    def test_aws_and_oidc_capabilities_are_rejected_before_api(self):
        for key in ["AWS_ACCESS_KEY_ID", "AWS_PROFILE", "AWS_WEB_IDENTITY_TOKEN_FILE", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"]:
            with patch.dict(os.environ, {"COMPAT_CONFIRMATION": compat.CONFIRMATION, "GITHUB_RUN_ATTEMPT": "1", key: "forbidden"}), \
                    patch.object(compat.gate, "get") as api:
                with self.assertRaises(ValueError): compat.context()
                api.assert_not_called()

    def test_namespace_cannot_target_production_or_another_run(self):
        environment, task = compat.identifiers(self.value, "normal")
        self.assertEqual(environment, "energy-demo-ci-compatibility-test-123")
        self.assertTrue(task.startswith("energy-demo-compat-123-"))
        for key, value in [("run_id", "999"), ("nonce", "../production"), ("commit", "d" * 40), ("kind", "production")]:
            with self.subTest(key=key), patch.object(compat.gate, "api") as api:
                with self.assertRaises(ValueError): compat.create_record({**self.value, key: value}, "normal", self.checksum)
                api.assert_not_called()
        with self.assertRaises(ValueError): compat.identifiers(self.value, "production")

    def test_record_payload_cannot_merge_or_select_production(self):
        with patch.object(compat.gate, "api", return_value=self.record) as api:
            compat.create_record(self.value, "normal", self.checksum)
            path, payload = api.call_args.args
            self.assertEqual(path, compat.gate.BASE + "/deployments")
            self.assertFalse(payload["auto_merge"])
            self.assertFalse(payload["production_environment"])
            self.assertTrue(payload["transient_environment"])
            self.assertEqual(payload["environment"], "energy-demo-ci-compatibility-test-123")
            self.assertNotIn("energy-demo-plan-", payload["task"])

    def test_test_ledger_queries_are_isolated(self):
        with patch.object(compat.gate, "pages", return_value=[]) as pages:
            compat.records(self.value, "normal")
            path = pages.call_args.args[0]
            self.assertIn("task=energy-demo-compat-123-", path)
            self.assertIn("environment=energy-demo-ci-compatibility-test-123", path)
            self.assertNotIn("energy-demo-plan-consumption", path)

    def test_consumption_and_replay_use_real_validator(self):
        with patch.object(compat, "records", side_effect=[[], [self.record]]), \
                patch.object(compat, "create_record", return_value=self.record) as create:
            compat.consume(self.value, "normal", self.checksum)
            create.assert_called_once()
        with patch.object(compat, "records", return_value=[self.record]), patch.object(compat, "create_record") as create:
            with self.assertRaises(ValueError): compat.consume(self.value, "normal", self.checksum)
            create.assert_not_called()

    def test_interruption_leaves_record_and_blocks_replay(self):
        with patch.object(compat, "records", return_value=[]), patch.object(compat, "create_record", return_value=self.record):
            with self.assertRaises(compat.SimulatedInterruption):
                compat.consume(self.value, "interrupted", self.checksum, interrupted=True)
        with patch.object(compat, "records", return_value=[self.record]):
            compat.replay_must_reject(self.value, "interrupted", self.checksum)

    def test_replay_probe_cannot_create_extra_records_on_stale_reads(self):
        with patch.object(compat, "records", return_value=[]), patch.object(compat.gate, "api") as api:
            with self.assertRaises(AssertionError): compat.replay_must_reject(self.value, "normal", self.checksum)
            api.assert_not_called()

    def test_read_write_errors_and_bad_acknowledgement_fail_closed(self):
        with patch.object(compat, "records", side_effect=URLError("injected")), patch.object(compat, "create_record") as create:
            with self.assertRaises(URLError): compat.consume(self.value, "normal", self.checksum)
            create.assert_not_called()
        with patch.object(compat, "records", return_value=[]), patch.object(compat, "create_record", side_effect=URLError("ambiguous")):
            with self.assertRaises(URLError): compat.consume(self.value, "normal", self.checksum)
        with patch.object(compat, "records", return_value=[]), patch.object(compat, "create_record", return_value={}):
            with self.assertRaises(ValueError): compat.consume(self.value, "normal", self.checksum)

    def test_runtime_negative_probes_do_not_call_github(self):
        with patch.object(compat.gate, "api") as api:
            compat.negative_checks(self.value, self.checksum)
            api.assert_not_called()

    def test_complete_verify_uses_only_two_test_records(self):
        import io
        import tempfile
        from urllib.parse import parse_qs, urlsplit
        import zipfile
        content = json.dumps(self.value, sort_keys=True).encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("fixture.json", content)
        blob = buffer.getvalue()
        artifact = {"id": 9, "name": "github-compat-fixture-123-1", "expired": False,
            "expires_at": "2035-01-01T00:00:00Z", "digest": "sha256:" + hashlib.sha256(blob).hexdigest(),
            "workflow_run": {"id": 123, "head_sha": "a" * 40, "head_branch": "main",
                             "repository_id": 10, "head_repository_id": 10}}
        ledger = []
        def read(path):
            if "/artifacts?" in path:
                return {"artifacts": [artifact]}
            query = parse_qs(urlsplit(path).query)
            return [r for r in ledger if r["task"] == query["task"][0] and r["environment"] == query["environment"][0]]
        def write(path, payload):
            self.assertEqual(path, compat.gate.BASE + "/deployments")
            self.assertTrue(payload["task"].startswith("energy-demo-compat-"))
            record = {**payload, "id": len(ledger) + 1}
            ledger.append(record)
            return record
        with tempfile.TemporaryDirectory() as tmp, patch.object(compat, "ROOT", Path(tmp)), \
                patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary")}), \
                patch.object(compat, "context", return_value=({"id": 10}, {"id": 123, "head_sha": "a" * 40})), \
                patch.object(compat.gate, "get", side_effect=read), patch.object(compat.gate, "api", side_effect=write), \
                patch.object(compat.gate, "download", side_effect=lambda a, d: compat.gate.extract_archive(blob, a["digest"], d)):
            compat.verify()
            self.assertIn("compatibility PASS", (Path(tmp) / "summary").read_text())
        self.assertEqual(len(ledger), 2)
        self.assertNotEqual(ledger[0]["task"], ledger[1]["task"])

    def test_workflow_is_manual_isolated_and_oidc_denied(self):
        import yaml
        source = (ROOT / ".github/workflows/github-compatibility.yml").read_text()
        workflow = yaml.safe_load(source)
        self.assertEqual(set(workflow.get("on", workflow.get(True))), {"workflow_dispatch"})
        self.assertEqual(workflow["concurrency"]["group"], "energy-demo-github-compatibility")
        self.assertEqual(workflow["jobs"]["verify"]["permissions"], {"contents": "read", "actions": "read", "deployments": "write"})
        for job in workflow["jobs"].values():
            self.assertNotIn("environment", job)
            self.assertNotIn("id-token", job["permissions"])
            self.assertIn("refs/heads/main", job.get("if", workflow["jobs"]["fixture"]["if"]))
        self.assertNotIn("terraform", source.lower())
        self.assertNotIn("configure-aws-credentials", source)
        self.assertIn("retention-days: 1", source)
        steps = workflow["jobs"]["fixture"]["steps"]
        self.assertIn("github_compatibility.py fixture", steps[1]["run"])
        self.assertTrue(steps[2]["uses"].startswith("actions/upload-artifact@"))
