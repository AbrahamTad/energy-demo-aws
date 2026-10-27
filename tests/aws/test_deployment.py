"""Offline tests for the sample Lambda and deployment security boundaries."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]


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
        result = sample.lambda_handler({"version": "2.0", "rawPath": "/api/energy"}, None)
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
        self.environment = {
            "id": 42,
            "protection_rules": [],
            "deployment_branch_policy": {
                "custom_branch_policies": True
            },
        }
        self.policies = {
            "branch_policies": [
                {"name": "main", "type": "branch"}
            ]
        }

    def test_solo_manual_deployment_and_main_only_are_accepted(self):
        gate.validate_environment(self.environment, self.policies)

    def test_required_reviewers_are_rejected_in_solo_mode(self):
        self.environment["protection_rules"] = [
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [
                    {"type": "User", "reviewer": {"login": "reviewer"}}
                ],
            }
        ]
        with self.assertRaises(ValueError):
            gate.validate_environment(self.environment, self.policies)

    def test_missing_main_branch_restriction_is_rejected(self):
        self.environment["deployment_branch_policy"] = {
            "custom_branch_policies": False
        }
        with self.assertRaises(ValueError):
            gate.validate_environment(self.environment, self.policies)

    def test_wildcard_or_tag_branch_policy_is_rejected(self):
        for policy in [{"name": "*"}, {"name": "main", "type": "tag"}]:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                gate.validate_environment(
                    self.environment, {"branch_policies": [policy]}
                )

    def test_admin_bypass_without_recorded_approval_is_rejected(self):
        with self.assertRaises(ValueError):
            gate.validate_approval(
                [], 42, "author",
                run_attempt=1,
                reviewer_logins={"reviewer"}
            )

    def test_wrong_environment_or_self_approval_is_rejected(self):
        for reviewer, environment in [("author", 42), ("reviewer", 99)]:
            with self.subTest(reviewer=reviewer), self.assertRaises(ValueError):
                gate.validate_approval(
                    [{
                        "state": "approved",
                        "user": {"login": reviewer},
                        "environments": [{"id": environment}]
                    }],
                    42, "author",
                    run_attempt=1,
                    reviewer_logins={"reviewer"}
                )

    def test_independent_approval_is_accepted(self):
        gate.validate_approval(
            [{
                "state": "approved",
                "user": {"login": "reviewer"},
                "environments": [{"id": 42}]
            }],
            42, "author",
            run_attempt=1,
            reviewer_logins={"reviewer"}
        )

    def test_rerun_initiator_cannot_approve(self):
        with self.assertRaises(ValueError):
            gate.validate_approval(
                [{
                    "state": "approved",
                    "user": {"login": "rerunner"},
                    "environments": [{"id": 42}]
                }],
                42, "author", "rerunner",
                run_attempt=1,
                reviewer_logins={"rerunner"}
            )

    def test_missing_reviewer_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            gate.validate_approval(
                [{
                    "state": "approved",
                    "environments": [{"id": 42}]
                }],
                42, "author",
                run_attempt=1,
                reviewer_logins={"reviewer"}
            )

    def test_unlisted_admin_approval_does_not_bypass_required_reviewer(self):
        with self.assertRaises(ValueError):
            gate.validate_approval(
                [{
                    "state": "approved",
                    "user": {"login": "unlisted-admin"},
                    "environments": [{"id": 42}]
                }],
                42, "author",
                run_attempt=1,
                reviewer_logins={"reviewer"}
            )

    def test_team_only_reviewers_fail_closed(self):
        self.environment["protection_rules"] = [
            {
                "type": "required_reviewers",
                "prevent_self_review": True,
                "reviewers": [
                    {"type": "Team", "reviewer": {"slug": "reviewers"}}
                ]
            }
        ]
        with self.assertRaises(ValueError):
            gate.validate_environment(self.environment, self.policies)

    def test_previous_approval_cannot_authorize_rerun(self):
        review = {
            "state": "approved",
            "user": {"login": "reviewer"},
            "environments": [{"id": 42}]
        }
        for attempt in [None, "", "2", "3", "01", "invalid"]:
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                gate.validate_approval(
                    [review], 42, "author",
                    run_attempt=attempt,
                    reviewer_logins={"reviewer"}
                )

    def test_rerun_is_rejected_before_any_api_access(self):
        with patch.dict(
            os.environ, {"GITHUB_RUN_ATTEMPT": "2"}, clear=True
        ), patch(
            "sys.argv", ["check_environment.py"]
        ), patch.object(gate, "get") as api:
            with self.assertRaises(ValueError):
                gate.main()
            api.assert_not_called()

    def test_rejected_or_ambiguous_review_history_fails_closed(self):
        approved = {
            "state": "approved",
            "user": {"login": "reviewer"},
            "environments": [{"id": 42}]
        }
        rejected = {**approved, "state": "rejected"}

        for reviews in [
            [rejected],
            [approved, rejected],
            [rejected, approved],
            [approved, approved]
        ]:
            with self.subTest(reviews=reviews), self.assertRaises(ValueError):
                gate.validate_approval(
                    reviews, 42, "author",
                    run_attempt=1,
                    reviewer_logins={"reviewer"}
                )

    def test_run_metadata_must_match_dispatch_commit_and_repository(self):
        run = {
            "id": 123,
            "run_attempt": 1,
            "head_sha": "a" * 40,
            "event": "workflow_dispatch",
            "head_branch": "main",
            "repository": {"full_name": gate.REPOSITORY},
            "head_repository": {"full_name": gate.REPOSITORY},
            "path": ".github/workflows/deploy-aws.yml",
        }

        gate.validate_run(run, "123", "a" * 40)

        for key, value in [
            ("run_attempt", 2),
            ("head_sha", "b" * 40),
            ("event", "push"),
            ("head_branch", "other"),
            ("path", ".github/workflows/other.yml"),
            ("head_repository", {"full_name": "other/repo"})
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.validate_run(
                    {**run, key: value}, "123", "a" * 40
                )


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
                archive.writestr("handler.py", "# test fixture")
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
