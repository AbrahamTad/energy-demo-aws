"""Explicitly approved GitHub-only runtime probe. Never call AWS or production ledgers."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import URLError
import uuid
from unittest.mock import patch

import check_environment as gate

WORKFLOW = ".github/workflows/github-compatibility.yml"
CONFIRMATION = "RUN GITHUB-ONLY COMPATIBILITY TEST"
ENV_PREFIX = "energy-demo-ci-compatibility-test-"
TASK_PREFIX = "energy-demo-compat-"
ROOT = Path(__file__).resolve().parents[2]


def approval(value):
    if value != CONFIRMATION:
        raise ValueError("Explicit GitHub-only test approval is required")


def context():
    approval(os.environ.get("COMPAT_CONFIRMATION"))  # Before any request or fixture write.
    gate.validate_attempt(os.environ.get("GITHUB_RUN_ATTEMPT"))
    # Hosted runner must not receive AWS credentials or OIDC request capability.
    forbidden = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                 "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN", "AWS_PROFILE",
                 "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL"]
    if any(os.environ.get(k) for k in forbidden):
        raise ValueError("Credential/OIDC capability is forbidden in this test")
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != gate.REPOSITORY
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.environ.get("GITHUB_ACTOR") != gate.OWNER
            or os.environ.get("GITHUB_TRIGGERING_ACTOR") != gate.OWNER
            or os.environ.get("GITHUB_ACTOR_ID") != os.environ.get("GITHUB_REPOSITORY_OWNER_ID")
            or os.environ.get("GITHUB_WORKFLOW_REF") != f"{gate.REPOSITORY}/{WORKFLOW}@refs/heads/main"
            or os.environ.get("GITHUB_WORKFLOW_SHA") != os.environ.get("GITHUB_SHA")):
        raise ValueError("Require owner-only trusted manual test on main")
    run_id, commit = os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("Invalid test run identity")
    repo = gate.get(gate.BASE)
    gate.validate_repository(repo)
    run = gate.get(f"{gate.BASE}/actions/runs/{run_id}")
    gate.validate_run(run, run_id, commit, WORKFLOW, repo)
    definition = gate.get(f"{gate.BASE}/actions/workflows/github-compatibility.yml")
    if definition.get("id") != run.get("workflow_id") or definition.get("path") != WORKFLOW or definition.get("state") != "active":
        raise ValueError("Test workflow identity unavailable")
    if gate.get(f"{gate.BASE}/git/ref/heads/main").get("object", {}).get("sha") != commit:
        raise ValueError("main moved; start a new compatibility test")
    # Read-only production environment API compatibility; never use its job/OIDC context.
    gate.validate_environment(gate.get(f"{gate.BASE}/environments/{gate.ENVIRONMENT}"),
        gate.get(f"{gate.BASE}/environments/{gate.ENVIRONMENT}/deployment-branch-policies?per_page=100"))
    return repo, run


def fixture():
    _, run = context()
    destination = ROOT / ".local/github-compat-fixture"
    destination.mkdir(parents=True, exist_ok=False)
    value = {"kind": "github-only-compatibility", "run_id": str(run["id"]),
             "commit": run["head_sha"], "nonce": uuid.uuid4().hex}
    (destination / "fixture.json").write_text(json.dumps(value, sort_keys=True) + "\n")


def identifiers(value, scenario):
    run_id = value["run_id"]
    if (value.get("kind") != "github-only-compatibility" or not re.fullmatch(r"[1-9][0-9]*", run_id)
            or run_id != os.environ.get("GITHUB_RUN_ID")
            or value.get("commit") != os.environ.get("GITHUB_SHA")
            or not re.fullmatch(r"[a-f0-9]{32}", value.get("nonce", ""))
            or scenario not in {"normal", "interrupted"}):
        raise ValueError("Invalid isolated fixture/ledger namespace")
    return ENV_PREFIX + run_id, TASK_PREFIX + run_id + "-" + value["nonce"] + "-" + scenario


def records(value, scenario):
    environment, task = identifiers(value, scenario)
    return gate.pages(f"{gate.BASE}/deployments?task={task}&environment={environment}")


def create_record(value, scenario, checksum):
    # The only mutation path: identifiers cannot select production environment/task.
    environment, task = identifiers(value, scenario)
    return gate.api(f"{gate.BASE}/deployments", {
        "ref": value["commit"], "task": task, "auto_merge": False, "required_contexts": [],
        "environment": environment, "production_environment": False, "transient_environment": True,
        "description": "GitHub-only compatibility metadata; no AWS or production deployment",
        "payload": {"plan_run_id": value["run_id"], "apply_run_id": value["run_id"], "sha256": checksum}})


class SimulatedInterruption(Exception):
    pass


def consume(value, scenario, checksum, interrupted=False):
    gate.validate_consumptions(records(value, scenario), value["run_id"])
    record = create_record(value, scenario, checksum)
    if type(record.get("id")) is not int or record["id"] <= 0:
        raise ValueError("Cannot establish written test record identity")
    if interrupted:
        # Model a process stopping after server acceptance, before acknowledgement.
        raise SimulatedInterruption()
    gate.validate_consumptions(records(value, scenario), value["run_id"], str(record["id"]))


def must_reject(function, exception=ValueError):
    try:
        function()
    except exception:
        return
    raise AssertionError("A negative compatibility test did not fail closed")


def negative_checks(value, checksum):
    for invalid in [None, "", "wrong"]:
        must_reject(lambda: approval(invalid))
    valid = {"PLAN_RUN_ID": value["run_id"], "REVIEWED_COMMIT": value["commit"],
             "PLAN_SHA256": checksum, "APPLY_CONFIRMATION": gate.CONFIRMATION}
    # Production confirmation validator, pure function: no Plan/Apply dispatch.
    with patch.dict(os.environ, valid):
        for invalid in ["", "wrong"]:
            with patch.dict(os.environ, {"APPLY_CONFIRMATION": invalid}):
                must_reject(gate.inputs)
        for field in ["PLAN_RUN_ID", "REVIEWED_COMMIT", "PLAN_SHA256"]:
            with patch.dict(os.environ, {field: ""}):
                must_reject(gate.inputs)
    for attempt in ["", "2"]:
        must_reject(lambda: gate.validate_attempt(attempt))
    with patch.object(gate, "get", side_effect=URLError("injected offline API failure")):
        must_reject(lambda: records(value, "normal"), URLError)
    with patch.object(gate, "api", side_effect=URLError("injected write failure")):
        must_reject(lambda: create_record(value, "normal", checksum), URLError)


def replay_must_reject(value, scenario, checksum):
    def forbidden_write(*args, **kwargs):
        raise AssertionError("Replay attempted an additional ledger write")
    # Probe actual ledger reads, but never permit a replay to create a third record.
    with patch.dict(globals(), {"create_record": forbidden_write}):
        must_reject(lambda: consume(value, scenario, checksum))


def verify():
    repo, run = context()
    artifacts = gate.pages(f"{gate.BASE}/actions/runs/{run['id']}/artifacts", "artifacts")
    artifact = gate.select_artifact(artifacts, f"github-compat-fixture-{run['id']}-1", run, repo, datetime.now(timezone.utc))
    directory = ROOT / ".local/github-compat-download"
    gate.download(artifact, directory)  # Checks GitHub digest, safe ZIP paths and redirects.
    if sorted(p.name for p in directory.iterdir()) != ["fixture.json"]:
        raise ValueError("Unexpected test artifact files")
    path = directory / "fixture.json"
    value = json.loads(path.read_text())
    identifiers(value, "normal")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    negative_checks(value, checksum)
    with patch.dict(os.environ, {"PLAN_SHA256": checksum}):
        consume(value, "normal", checksum)
        replay_must_reject(value, "normal", checksum)
        must_reject(lambda: consume(value, "interrupted", checksum, interrupted=True), SimulatedInterruption)
        replay_must_reject(value, "interrupted", checksum)
        found = {scenario: records(value, scenario) for scenario in ["normal", "interrupted"]}
        counts = {scenario: len(rows) for scenario, rows in found.items()}
        if counts != {"normal": 1, "interrupted": 1}:
            raise ValueError("Unexpected test-only ledger cardinality")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(f"GitHub-only compatibility PASS. Artifact `{artifact['id']}` verified.\n\n"
            f"Test metadata environment: `{ENV_PREFIX + value['run_id']}`.\n\n"
            f"Record IDs: normal `{found['normal'][0]['id']}`, interrupted `{found['interrupted'][0]['id']}`.\n\n"
            "Exactly one normal and one interrupted-consumption record; both replays rejected.\n"
            "No AWS credentials/OIDC, Terraform, emails or production consumption records used.\n"
            "Test records retained for separately approved cleanup; artifact expires after one day.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["fixture", "verify"])
    stage = parser.parse_args().stage
    (fixture if stage == "fixture" else verify)()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # No credentials, signed download URLs or HTTP response bodies in errors.
        raise SystemExit("GitHub-only compatibility test blocked/failed. No automatic cleanup or retry; review this run.") from None
