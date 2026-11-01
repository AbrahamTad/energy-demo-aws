"""Offline tests for the sample Lambda and deployment security boundaries."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lambda/energy"))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load("gate", "scripts/aws/check_environment.py")
backend = load("backend", "scripts/aws/init_backend.py")
artifact = load("artifact", "scripts/aws/verify_artifact.py")
plan_guard = load("plan_guard", "scripts/aws/check_plan.py")
sample = load("sample", "lambda/energy/handler.py")


class SampleLambdaTests(unittest.TestCase):
    def test_http_api_v2_event_returns_four_records(self):
        records = [{"source": source, "production": value, "unit": "kWh"}
                   for source, value in [("Solar", 125), ("Wind", 80), ("Hydro", 150), ("Battery", 45)]]
        with patch.object(sample.PublicRepository, "list", return_value=records):
            result = sample.lambda_handler({"version": "2.0", "routeKey": "GET /api/energy"}, None)
        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])
        self.assertEqual(body["project"], "EnergyDemo")
        self.assertEqual(body["status"], "working")
        self.assertEqual(body["records"], [
            {"source": source, "production": value, "unit": "kWh"}
            for source, value in [("Solar", 125), ("Wind", 80), ("Hydro", 150), ("Battery", 45)]
        ])



class GateTests(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timezone
        self.now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
        self.repo = {"id": 10, "full_name": gate.REPOSITORY, "owner": {"id": 20, "login": gate.OWNER, "type": "User"},
                     "archived": False, "disabled": False, "default_branch": "main"}
        self.environment = {"id": 42, "name": "aws-production", "can_admins_bypass": False,
            "protection_rules": [{"type": "branch_policy"}],
            "deployment_branch_policy": {"custom_branch_policies": True, "protected_branches": False}}
        self.policies = {"branch_policies": [{"name": "main", "type": "branch"}]}
        self.env = {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REPOSITORY": gate.REPOSITORY,
            "GITHUB_REPOSITORY_OWNER": gate.OWNER, "GITHUB_REPOSITORY_OWNER_ID": "20", "GITHUB_REPOSITORY_ID": "10",
            "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_ACTOR": gate.OWNER,
            "GITHUB_TRIGGERING_ACTOR": gate.OWNER, "GITHUB_ACTOR_ID": "20", "GITHUB_RUN_ID": "200",
            "GITHUB_SHA": "a" * 40, "GITHUB_WORKFLOW_SHA": "a" * 40,
            "GITHUB_WORKFLOW_REF": f"{gate.REPOSITORY}/{gate.APPLY_WORKFLOW}@refs/heads/main",
            "TF_VAR_account_id": "123456789012", "TF_VAR_budget_email": "test@example.invalid",
            "AWS_REGION": "eu-north-1", "AWS_DEFAULT_REGION": "eu-north-1", "AWS_API_ID": "fixture123",
            "AWS_CLOUDFRONT_DISTRIBUTION_ID": "FIXTUREDIST", "AWS_CLOUDFRONT_OAC_ID": "FIXTUREOAC",
            "PLAN_RUN_ID": "100", "REVIEWED_COMMIT": "a" * 40, "PLAN_SHA256": "b" * 64,
            "APPLY_CONFIRMATION": gate.CONFIRMATION}
        self.patch = patch.dict(os.environ, self.env, clear=True)
        self.patch.start(); self.addCleanup(self.patch.stop)
        actor = {"id": 20, "login": gate.OWNER, "type": "User"}
        self.run = {"id": 200, "run_attempt": 1, "head_sha": "a" * 40, "event": "workflow_dispatch",
            "head_branch": "main", "repository": self.repo, "head_repository": self.repo,
            "path": gate.APPLY_WORKFLOW, "workflow_id": 30, "actor": actor, "triggering_actor": actor,
            "created_at": "2026-10-31T11:00:00Z"}
        self.plan = {**self.run, "id": 100, "path": gate.PLAN_WORKFLOW, "workflow_id": 31,
            "status": "completed", "conclusion": "success", "created_at": "2026-10-31T10:00:00Z",
            "updated_at": "2026-10-31T10:10:00Z"}
        self.artifact = {"id": 80, "name": "aws-plan-100-1", "expired": False,
            "expires_at": "2026-11-01T10:00:00Z", "digest": "sha256:" + "c" * 64,
            "workflow_run": {"id": 100, "repository_id": 10, "head_repository_id": 10,
                             "head_branch": "main", "head_sha": "a" * 40}}

    def test_owner_context_and_configuration_pass(self):
        gate.validate_repository(self.repo)
        gate.validate_run(self.run, "200", "a" * 40, gate.APPLY_WORKFLOW, self.repo)
        gate.validate_environment(self.environment, self.policies)
        self.assertEqual(len(gate.configuration()), 64)

    def test_non_owner_fork_workflow_and_rerun_rejected(self):
        for key, value in [("actor", {"id": 21, "login": "other", "type": "User"}),
                           ("triggering_actor", {"id": 21, "login": gate.OWNER, "type": "User"}),
                           ("head_repository", {"id": 11, "full_name": gate.REPOSITORY}),
                           ("path", gate.PLAN_WORKFLOW), ("run_attempt", 2),
                           ("event", "push"), ("head_branch", "topic"), ("head_sha", "b" * 40)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.validate_run({**self.run, key: value}, "200", "a" * 40, gate.APPLY_WORKFLOW, self.repo)

    def test_owner_repository_and_account_identity_mismatch(self):
        for key, value in [("GITHUB_REPOSITORY_OWNER_ID", "21"), ("GITHUB_REPOSITORY_ID", "11")]:
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaises(ValueError):
                gate.validate_repository(self.repo)
        for key, value in [("TF_VAR_account_id", "000000000000"), ("AWS_REGION", "us-east-1"), ("AWS_API_ID", "*")]:
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaises(ValueError):
                gate.configuration()

    def test_context_rejects_untrusted_values_before_api(self):
        for key, value in [("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_REF", "refs/heads/other"),
                           ("GITHUB_ACTOR", "other"), ("GITHUB_ACTOR_ID", "21"), ("GITHUB_ACTIONS", "false"),
                           ("GITHUB_EVENT_NAME", "push"), ("GITHUB_WORKFLOW_REF", "other"),
                           ("GITHUB_WORKFLOW_SHA", "b" * 40)]:
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), patch.object(gate, "get") as api:
                with self.assertRaises(ValueError): gate.context(gate.APPLY_WORKFLOW)
                api.assert_not_called()

    def context_responses(self):
        return [self.repo, self.run, {"id": 30, "state": "active", "path": gate.APPLY_WORKFLOW},
                {"object": {"sha": "a" * 40}}, self.environment, self.policies]

    def test_context_api_and_moved_main_fail_closed(self):
        from urllib.error import HTTPError
        with patch.object(gate, "get", side_effect=self.context_responses()):
            self.assertEqual(gate.context(gate.APPLY_WORKFLOW), (self.repo, self.run))
        responses = self.context_responses(); responses[3] = {"object": {"sha": "b" * 40}}
        with patch.object(gate, "get", side_effect=responses), self.assertRaises(ValueError):
            gate.context(gate.APPLY_WORKFLOW)
        for status in [403, 404, 500]:
            with patch.object(gate, "get", side_effect=HTTPError("https://api.github.com", status, "unavailable", {}, None)):
                with self.assertRaises(HTTPError): gate.context(gate.APPLY_WORKFLOW)

    def test_environment_missing_bypass_review_rules_and_branch_policy_rejected(self):
        for key, value in [("can_admins_bypass", True), ("can_admins_bypass", None), ("can_admins_bypass", 0),
                           ("name", "staging"), ("id", None), ("protection_rules", None),
                           ("protection_rules", [{"type": "required_reviewers"}]),
                           ("protection_rules", [{"type": "wait_timer"}]),
                           ("deployment_branch_policy", {"custom_branch_policies": False, "protected_branches": True})]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                gate.validate_environment({**self.environment, key: value}, self.policies)
        for entries in [[], [{"name": "*", "type": "branch"}], [{"name": "main", "type": "tag"}],
                        [{"name": "main"}], self.policies["branch_policies"] * 2]:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                gate.validate_environment(self.environment, {"branch_policies": entries})

    def test_exact_confirmation_and_inputs_required_before_api(self):
        for key in ["APPLY_CONFIRMATION", "PLAN_RUN_ID", "REVIEWED_COMMIT", "PLAN_SHA256"]:
            for value in ["", "wrong", "$(echo unsafe)"]:
                with self.subTest(key=key, value=value), patch.dict(os.environ, {key: value}), patch.object(gate, "get") as api:
                    with self.assertRaises(ValueError): gate.apply("prepare")
                    api.assert_not_called()

    def test_successful_separate_plan_is_accepted(self):
        gate.validate_plan_run(self.plan, self.run, self.repo, self.now)

    def test_expired_future_incomplete_after_dispatch_or_different_commit_plan_rejected(self):
        for key, value in [("created_at", "2026-10-30T12:00:00Z"), ("created_at", "2026-10-31T13:00:00Z"),
                           ("updated_at", "2026-10-31T11:01:00Z"), ("status", "in_progress"),
                           ("conclusion", "failure"), ("run_attempt", 2), ("head_sha", "b" * 40),
                           ("path", gate.APPLY_WORKFLOW)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                gate.validate_plan_run({**self.plan, key: value}, self.run, self.repo, self.now)

    def test_exact_artifact_provenance_and_missing_digest(self):
        self.assertEqual(gate.select_artifact([self.artifact], "aws-plan-100-1", self.plan, self.repo, self.now), self.artifact)
        for key, value in [("expired", True), ("digest", None), ("digest", ""),
                           ("expires_at", "2026-10-31T11:00:00Z"), ("workflow_run", {"id": 999})]:
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                gate.select_artifact([{**self.artifact, key: value}], "aws-plan-100-1", self.plan, self.repo, self.now)
        for artifacts in [[], [self.artifact, self.artifact]]:
            with self.assertRaises(ValueError): gate.select_artifact(artifacts, "aws-plan-100-1", self.plan, self.repo, self.now)

    def test_archive_digest_paths_and_redirect_credentials(self):
        import io
        from urllib.request import Request
        for filename in ["../escape", "/absolute", "bad\\path"]:
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as z: z.writestr(filename, "fixture")
            raw = data.getvalue()
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
                gate.extract_archive(raw, "sha256:" + hashlib.sha256(raw).hexdigest(), Path(tmp) / "out")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            gate.extract_archive(b"tampered", "sha256:" + "a" * 64, Path(tmp) / "out")
        req = Request("https://api.github.com/download", headers={"Authorization": "Bearer fixture"})
        redirect = gate.SafeRedirect().redirect_request(req, None, 302, "", {}, "https://storage.example.invalid/file")
        self.assertIsNone(redirect.get_header("Authorization"))
        with self.assertRaises(ValueError):
            gate.SafeRedirect().redirect_request(req, None, 302, "", {}, "http://storage.example.invalid/file")

    def test_saved_plan_tampering_and_configuration_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); digest = hashlib.sha256(b"saved-plan").hexdigest()
            (d / "reviewed.tfplan").write_bytes(b"saved-plan")
            (d / "reviewed-plan.txt").write_text("fixture")
            (d / "reviewed.tfplan.sha256").write_text(digest + "  reviewed.tfplan\n")
            (d / "reviewed-commit.txt").write_text("a" * 40 + "\n")
            (d / "reviewed-metadata.json").write_text(json.dumps({"plan_run_id": "100", "commit": "a" * 40,
                "sha256": digest, "configuration": gate.configuration()}))
            gate.verify_files(d, "100", "a" * 40, digest)
            with patch.dict(os.environ, {"TF_VAR_enable_admin": "true"}), self.assertRaises(ValueError):
                gate.verify_files(d, "100", "a" * 40, digest)
            (d / "reviewed.tfplan").write_bytes(b"tampered")
            with self.assertRaises(ValueError): gate.verify_files(d, "100", "a" * 40, digest)

    def test_replay_missing_reservation_and_different_apply_run_rejected(self):
        gate.validate_consumptions([], "100")
        record = {"id": 88, "payload": {"plan_run_id": "100", "apply_run_id": "200", "sha256": "b" * 64}}
        gate.validate_consumptions([record], "100", "88")
        for records, reservation in [([record], None), ([], "88"), ([record, record], "88"), ([record], "89"),
                                     ([{**record, "payload": {}}], "88")]:
            with self.subTest(records=records, reservation=reservation), self.assertRaises(ValueError):
                gate.validate_consumptions(records, "100", reservation)

    def test_pagination_does_not_ignore_later_consumption_records(self):
        with patch.object(gate, "get", side_effect=[[{}] * 100, [{"id": 88}]]) as api:
            records = gate.consumptions("100")
            self.assertEqual(len(records), 101)
            self.assertIn("page=2", api.call_args.args[0])
            with self.assertRaises(ValueError): gate.validate_consumptions(records, "100")

    def test_verification_requires_reservation_even_when_ledger_is_empty(self):
        with patch.object(gate, "context", return_value=(self.repo, self.run)), \
                patch.object(gate, "validate_plan_run"), patch.object(gate, "get", side_effect=[self.plan,
                    {"id": 31, "path": gate.PLAN_WORKFLOW, "state": "active"}]), \
                patch.object(gate, "consumptions") as ledger:
            with self.assertRaises(ValueError): gate.apply("verify")
            ledger.assert_not_called()

    def test_consume_creates_durable_record_only_after_all_checks(self):
        sys.path.insert(0, str(ROOT / "scripts/aws"))
        self.addCleanup(lambda: sys.path.remove(str(ROOT / "scripts/aws")))
        import verify_artifact
        record = {"id": 88, "payload": {"plan_run_id": "100", "apply_run_id": "200", "sha256": "b" * 64}}
        definition = {"id": 31, "path": gate.PLAN_WORKFLOW, "state": "active"}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GITHUB_ENV": str(Path(tmp) / "env")}), \
                patch.object(gate, "context", return_value=(self.repo, self.run)), \
                patch.object(gate, "validate_plan_run"), patch.object(gate, "get", side_effect=[self.plan, definition]), \
                patch.object(gate, "verify_files") as files, patch.object(verify_artifact, "verify") as build, \
                patch.object(gate, "consumptions", side_effect=[[], [record]]), \
                patch.object(gate, "api", return_value=record) as api:
            gate.apply("consume")
            files.assert_called_once(); build.assert_called_once()
            self.assertFalse(api.call_args.args[1]["auto_merge"])
            self.assertEqual(api.call_args.args[1]["payload"], record["payload"])
            self.assertEqual((Path(tmp) / "env").read_text(), "PLAN_RESERVATION_ID=88\n")
        with patch.object(gate, "context", return_value=(self.repo, self.run)), \
                patch.object(gate, "validate_plan_run"), patch.object(gate, "get", side_effect=[self.plan, definition]), \
                patch.object(gate, "consumptions", return_value=[record]), patch.object(gate, "api") as api:
            with self.assertRaises(ValueError): gate.apply("consume")
            api.assert_not_called()


class WorkflowApprovalTests(unittest.TestCase):
    def setUp(self):
        import yaml
        self.plan = yaml.safe_load((ROOT / ".github/workflows/plan-aws.yml").read_text())
        self.apply = yaml.safe_load((ROOT / ".github/workflows/deploy-aws.yml").read_text())

    def test_two_manual_workflows_no_automatic_apply(self):
        for workflow in [self.plan, self.apply]:
            triggers = workflow.get("on", workflow.get(True))
            self.assertEqual(set(triggers), {"workflow_dispatch"})
            self.assertEqual(workflow["concurrency"], {"group": "energy-demo-real-aws", "cancel-in-progress": False})
        self.assertNotIn("apply", self.plan["jobs"])
        self.assertNotIn("needs", self.apply["jobs"]["apply"])
        self.assertEqual(self.plan["env"], {k: v for k, v in self.apply["env"].items()
                                          if k not in {"PLAN_RUN_ID", "REVIEWED_COMMIT", "PLAN_SHA256", "APPLY_CONFIRMATION"}})

    def test_owner_gate_consumption_and_resource_checks_precede_credentials(self):
        job = self.apply["jobs"]["apply"]
        self.assertEqual(job["environment"], "aws-production")
        self.assertIn("refs/heads/main", job["if"])
        self.assertEqual(job["permissions"]["id-token"], "write")
        self.assertEqual(job["permissions"]["deployments"], "write")
        steps = job["steps"]
        credentials = next(i for i,s in enumerate(steps) if s.get("uses", "").startswith("aws-actions/configure-aws-credentials@"))
        before = "\n".join(s.get("run", "") for s in steps[:credentials])
        for check in ["check_environment.py prepare", "check_environment.py consume", "check_plan.py"]:
            self.assertIn(check, before)
        after = "\n".join(s.get("run", "") for s in steps[credentials:])
        self.assertLess(after.index("check_environment.py verify"), after.index(" apply "))
        self.assertIn("cmp .local/reviewed-plan/reviewed.tfplan", after)
        self.assertIn("-lock-timeout=120s reviewed.tfplan", after)
        self.assertNotIn("-lock=false", after)
        self.assertIn("github-deploy", steps[credentials]["with"]["role-to-assume"])
        for s in steps:
            self.assertNotIn("${{ inputs.", s.get("run", ""))


class PlanGuardTests(unittest.TestCase):
    def setUp(self):
        self.ids = plan_guard.expected_ids({
            "AWS_API_ID": "fixture123",
            "AWS_CLOUDFRONT_DISTRIBUTION_ID": "FIXTUREDIST",
            "AWS_CLOUDFRONT_OAC_ID": "FIXTUREOAC",
        })
        self.plan = {"resource_changes": [
            {"address": address, "change": {"actions": ["no-op"],
                                            "before": {"id": value}, "after": {"id": value}}}
            for address, value in self.ids.items()
        ]}

    def test_exact_bootstrap_ids_are_accepted(self):
        plan_guard.verify(self.plan, self.ids)

    def test_missing_ids_and_wildcards_are_rejected(self):
        with self.assertRaises(ValueError):
            plan_guard.expected_ids({})
        with self.assertRaises(ValueError):
            plan_guard.expected_ids({"AWS_API_ID": "*", "AWS_CLOUDFRONT_DISTRIBUTION_ID": "*", "AWS_CLOUDFRONT_OAC_ID": "*"})

    def test_initial_creation_cannot_be_done_by_ci(self):
        change = self.plan["resource_changes"][0]["change"]
        change["actions"] = ["create"]
        change["before"] = None
        with self.assertRaises(ValueError):
            plan_guard.verify(self.plan, self.ids)

    def test_unrelated_resource_id_is_rejected(self):
        self.plan["resource_changes"][1]["change"]["before"]["id"] = "UNRELATED"
        with self.assertRaises(ValueError):
            plan_guard.verify(self.plan, self.ids)

    def test_delete_and_replacement_are_rejected(self):
        for actions in [["delete"], ["delete", "create"], ["create", "delete"]]:
            self.plan["resource_changes"][0]["change"]["actions"] = actions
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                plan_guard.verify(self.plan, self.ids)


class BackendTests(unittest.TestCase):
    def test_floci_and_invalid_accounts_are_rejected(self):
        for value in ["", "000000000000", "test", "123"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                backend.configuration(value)

    def test_real_backend_has_account_guard_and_locking(self):
        # Syntactic fixture, never authenticated or sent to AWS.
        config = backend.configuration("123456789012")
        self.assertEqual(config["allowed_account_ids"], ["123456789012"])
        self.assertTrue(config["use_lockfile"])
        self.assertTrue(config["encrypt"])
        self.assertEqual(config["region"], "eu-north-1")
        self.assertEqual(config["key"], "energy-demo/aws/terraform.tfstate")


class ArtifactTests(unittest.TestCase):
    def test_wrong_commit_and_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "frontend").mkdir()
            (output / "frontend/index.html").write_text("<html></html>")
            with zipfile.ZipFile(output / "lambda.zip", "w") as archive:
                for name in ["handler.py", "user_handler.py", "energy_auth.py", "energy_store.py", "energy_validation.py", "jwt/__init__.py", "cryptography/__init__.py"]:
                    archive.writestr(name, "# test fixture")
            hashes = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in [output / "lambda.zip", output / "frontend/index.html"]}
            (output / "manifest.json").write_text(json.dumps({"commit": "trusted", "sha256": hashes}))
            artifact.verify(output, "trusted")
            with self.assertRaises(ValueError):
                artifact.verify(output, "other")
            (output / "frontend/index.html").write_text("tampered")
            with self.assertRaises(ValueError):
                artifact.verify(output, "trusted")


if __name__ == "__main__":
    unittest.main()
