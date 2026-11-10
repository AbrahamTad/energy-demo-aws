"""Owner-only two-dispatch deployment gate. No AWS calls; fail closed on GitHub/API errors."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler, urlopen
import zipfile

OWNER = "AbrahamTad"
REPOSITORY = OWNER + "/energy-demo-aws"
ENVIRONMENT = "aws-production"
PLAN_WORKFLOW = ".github/workflows/plan-aws.yml"
APPLY_WORKFLOW = ".github/workflows/deploy-aws.yml"
CONFIRMATION = "APPLY ENERGYDEMO PRODUCTION"
MAX_AGE = timedelta(hours=24)
ROOT = Path(__file__).resolve().parents[2]
BASE = "repos/" + REPOSITORY


def api(path, payload=None):
    request = Request("https://api.github.com/" + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def get(path):
    return api(path)


def pages(path, key=None):
    result = []
    for page in range(1, 101):
        data = get(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}")
        rows = data if key is None else data[key]
        if not isinstance(rows, list):
            raise ValueError("Invalid paginated GitHub response")
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise ValueError("Cannot establish complete GitHub history")


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Unverifiable timestamp")
    return parsed


def validate_attempt(value):
    if str(value) != "1":
        raise ValueError("Reruns are forbidden; dispatch a NEW Plan and Apply")


def validate_environment(environment, policies):
    if (environment.get("name") != ENVIRONMENT or type(environment.get("id")) is not int
            or environment["id"] <= 0 or environment.get("can_admins_bypass") is not False):
        raise ValueError("Production environment identity/bypass policy is unverifiable")
    rules = environment.get("protection_rules")
    if not isinstance(rules, list) or any(r.get("type") != "branch_policy" for r in rules):
        raise ValueError("Solo mode requires branch protection only; remove reviewer/wait/custom rules")
    if environment.get("deployment_branch_policy") != {
            "protected_branches": False, "custom_branch_policies": True}:
        raise ValueError("Require selected deployment branches only")
    entries = policies.get("branch_policies")
    if (not isinstance(entries, list) or len(entries) != 1
            or entries[0].get("name") != "main" or entries[0].get("type") != "branch"):
        raise ValueError("Production must allow only main, with no tags/wildcards")


def validate_repository(repository):
    owner = repository.get("owner", {})
    if (repository.get("full_name") != REPOSITORY or owner.get("login") != OWNER
            or owner.get("type") != "User" or type(owner.get("id")) is not int
            or str(owner["id"]) != os.environ.get("GITHUB_REPOSITORY_OWNER_ID")
            or str(repository.get("id")) != os.environ.get("GITHUB_REPOSITORY_ID")
            or repository.get("archived") is not False or repository.get("disabled") is not False
            or repository.get("default_branch") != "main"):
        raise ValueError("Unauthorized repository/owner or inactive repository")


def validate_run(run, run_id, commit, workflow, repository):
    validate_attempt(run.get("run_attempt"))
    owner_id = repository["owner"]["id"]
    if (str(run.get("id")) != str(run_id) or run.get("head_sha") != commit
            or not re.fullmatch(r"[a-f0-9]{40}", commit)
            or run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main"
            or run.get("repository", {}).get("id") != repository["id"]
            or run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("head_repository", {}).get("id") != repository["id"]
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or run.get("path", "").split("@")[0] != workflow):
        raise ValueError("Untrusted run, workflow, branch, repository or commit")
    for key in ["actor", "triggering_actor"]:
        actor = run.get(key, {})
        if actor.get("id") != owner_id or actor.get("login") != OWNER or actor.get("type") != "User":
            raise ValueError("Only the exact repository owner may initiate deployment runs")


def context(workflow):
    validate_attempt(os.environ.get("GITHUB_RUN_ATTEMPT"))
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REPOSITORY_OWNER") != OWNER
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
            or os.environ.get("GITHUB_ACTOR") != OWNER
            or os.environ.get("GITHUB_TRIGGERING_ACTOR") != OWNER
            or os.environ.get("GITHUB_ACTOR_ID") != os.environ.get("GITHUB_REPOSITORY_OWNER_ID")
            or os.environ.get("GITHUB_WORKFLOW_REF") != f"{REPOSITORY}/{workflow}@refs/heads/main"
            or os.environ.get("GITHUB_WORKFLOW_SHA") != os.environ.get("GITHUB_SHA")):
        raise ValueError("Require trusted owner-only manual Actions context on main")
    run_id, commit = os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        raise ValueError("Invalid run ID")
    repository = get(BASE)
    validate_repository(repository)
    current = get(f"{BASE}/actions/runs/{run_id}")
    validate_run(current, run_id, commit, workflow, repository)
    definition = get(f"{BASE}/actions/workflows/{workflow.rsplit('/', 1)[1]}")
    if definition.get("path") != workflow or definition.get("state") != "active" or definition.get("id") != current.get("workflow_id"):
        raise ValueError("Workflow identity unavailable")
    if get(f"{BASE}/git/ref/heads/main").get("object", {}).get("sha") != commit:
        raise ValueError("main moved; generate a fresh Plan")
    validate_environment(get(f"{BASE}/environments/{ENVIRONMENT}"),
                         get(f"{BASE}/environments/{ENVIRONMENT}/deployment-branch-policies?per_page=100"))
    configuration()  # Preserve account/resource input checks before any credentials.
    return repository, current


def configuration():
    values = {key: value for key, value in os.environ.items()
              if key.startswith("TF_VAR_") or key in {"AWS_REGION", "AWS_DEFAULT_REGION", "AWS_API_ID",
                  "AWS_CLOUDFRONT_DISTRIBUTION_ID", "AWS_CLOUDFRONT_OAC_ID", "VITE_TURNSTILE_SITE_KEY"}}
    patterns = {"TF_VAR_account_id": r"[0-9]{12}", "TF_VAR_budget_email": r"[^@\s]+@[^@\s]+\.[^@\s]+",
        "AWS_API_ID": r"[a-z0-9]{1,32}", "AWS_CLOUDFRONT_DISTRIBUTION_ID": r"[A-Z0-9]{1,64}",
        "AWS_CLOUDFRONT_OAC_ID": r"[A-Z0-9]{1,64}"}
    if any(not re.fullmatch(pattern, values.get(key, "")) for key, pattern in patterns.items()):
        raise ValueError("Missing/invalid account, budget or administrator-verified resource IDs")
    if (values["TF_VAR_account_id"] == "000000000000" or values.get("AWS_REGION") != "eu-north-1"
            or values.get("AWS_DEFAULT_REGION") != "eu-north-1"):
        raise ValueError("Incorrect AWS account/region configuration")
    if values.get("TF_VAR_enable_contact", "false") not in ["true", "false"]:
        raise ValueError("Invalid Contact enable flag")
    if values.get("TF_VAR_admin_email_testing_enabled", "false") != "false":
        raise ValueError("Admin email testing is disabled for the reviewed no-send deployment workflow")
    if values.get("TF_VAR_enable_contact") == "true":
        origin = values.get("TF_VAR_contact_site_origin", "")
        hostnames = json.loads(values.get("TF_VAR_contact_hostnames", "[]"))
        key = values.get("VITE_TURNSTILE_SITE_KEY", "")
        if (not re.fullmatch(r"https://[a-z0-9-]+\.cloudfront\.net", origin)
                or hostnames != [origin.removeprefix("https://")]
                or not re.fullmatch(r"[a-f0-9]{64}", values.get("TF_VAR_contact_origin_token", ""))
                or not re.fullmatch(r"[A-Za-z0-9_-]{20,100}", key) or key.startswith(("1x", "2x", "3x"))
                or values.get("TF_VAR_enable_admin") != "true"
                or not re.fullmatch(r"arn:aws:sns:eu-north-1:" + values["TF_VAR_account_id"] + r":[A-Za-z0-9_-]+",
                    values.get("TF_VAR_contact_alarm_topic_arn", ""))):
            raise ValueError("Contact origin, widget, alarm destination or credential is unapproved")
        for name in ["contact_sender", "contact_admin_email"]:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", values.get("TF_VAR_" + name, "")):
                raise ValueError("Missing Contact sender/inbox")
        for name in ["contact_email_sending_enabled", "contact_customer_email_enabled"]:
            if values.get("TF_VAR_" + name, "false") != "false":
                raise ValueError("Contact readiness rollout is no-send; sending needs a separately reviewed gate change")
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def inputs():
    values = tuple(os.environ.get(k, "") for k in ["PLAN_RUN_ID", "REVIEWED_COMMIT", "PLAN_SHA256"])
    if (not re.fullmatch(r"[1-9][0-9]*", values[0]) or not re.fullmatch(r"[a-f0-9]{40}", values[1])
            or not re.fullmatch(r"[a-f0-9]{64}", values[2])
            or os.environ.get("APPLY_CONFIRMATION") != CONFIRMATION):
        raise ValueError("Require Plan run ID, exact commit/checksum and explicit Apply confirmation")
    return values


def validate_plan_run(plan, current, repository, now):
    run_id, commit, _ = inputs()
    validate_run(plan, run_id, commit, PLAN_WORKFLOW, repository)
    if (plan.get("status") != "completed" or plan.get("conclusion") != "success"
            or plan.get("head_sha") != current["head_sha"]
            or str(plan["id"]) == str(current["id"])):
        raise ValueError("Require a successful separate Plan at the Apply/main commit")
    started, finished = timestamp(plan["created_at"]), timestamp(plan["updated_at"])
    if not (started <= finished <= timestamp(current["created_at"]) <= now
            and timedelta(0) <= now - started < MAX_AGE):
        raise ValueError("Plan is expired, future-dated, or finished after Apply was requested")


def select_artifact(artifacts, name, plan, repository, now):
    matches = [a for a in artifacts if a.get("name") == name]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous exact Plan artifact")
    artifact = matches[0]
    run = artifact.get("workflow_run", {})
    if (type(artifact.get("id")) is not int or artifact.get("expired") is not False
            or timestamp(artifact["expires_at"]) <= now
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact.get("digest", ""))
            or run.get("id") != plan["id"] or run.get("head_sha") != plan["head_sha"]
            or run.get("head_branch") != "main" or run.get("repository_id") != repository["id"]
            or run.get("head_repository_id") != repository["id"]):
        raise ValueError("Unverifiable, expired or untrusted artifact provenance/digest")
    return artifact


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise ValueError("Unsafe artifact redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        # Signed artifact-storage URLs need no GitHub credential.
        if urlparse(newurl).netloc != urlparse(req.full_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


def extract_archive(data, digest, destination):
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("GitHub archive digest mismatch")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set()
        if sum(i.file_size for i in archive.infolist()) > 250_000_000:
            raise ValueError("Oversized artifact")
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                    or info.filename in names or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError("Unsafe artifact path")
            names.add(info.filename)
        destination.mkdir(parents=True, exist_ok=False)
        archive.extractall(destination)


def download(artifact, destination):
    request = Request(f"https://api.github.com/{BASE}/actions/artifacts/{artifact['id']}/zip",
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json"})
    with build_opener(SafeRedirect()).open(request, timeout=60) as response:
        data = response.read(100_000_001)
    if len(data) > 100_000_000:
        raise ValueError("Oversized archive download")
    extract_archive(data, artifact["digest"], destination)


def verify_files(directory, run_id, commit, checksum):
    expected = {"reviewed.tfplan", "reviewed-plan.txt", "reviewed-commit.txt", "reviewed.tfplan.sha256", "reviewed-metadata.json"}
    if {p.name for p in directory.iterdir()} != expected or any(p.is_symlink() or not p.is_file() for p in directory.iterdir()):
        raise ValueError("Unexpected saved-plan files")
    if (hashlib.sha256((directory / "reviewed.tfplan").read_bytes()).hexdigest() != checksum
            or (directory / "reviewed-commit.txt").read_text().strip() != commit
            or (directory / "reviewed.tfplan.sha256").read_text() != checksum + "  reviewed.tfplan\n"):
        raise ValueError("Saved-plan checksum/commit mismatch")
    meta = json.loads((directory / "reviewed-metadata.json").read_text())
    if meta != {"plan_run_id": run_id, "commit": commit, "sha256": checksum, "configuration": configuration()}:
        raise ValueError("Saved-plan provenance or deployment configuration changed")


def consumptions(run_id):
    return pages(f"{BASE}/deployments?task=energy-demo-plan-{run_id}&environment=energy-demo-plan-consumption")


def validate_consumptions(records, run_id, reservation=None):
    if reservation is None:
        if records:
            raise ValueError("Plan already consumed; create a NEW Plan, including after failed Apply")
    elif (len(records) != 1 or str(records[0].get("id")) != reservation
          or records[0].get("payload") != {"plan_run_id": run_id, "apply_run_id": os.environ["GITHUB_RUN_ID"],
                                          "sha256": os.environ["PLAN_SHA256"]}):
        raise ValueError("Plan consumption reservation is missing or ambiguous")


def apply(stage):
    run_id, commit, checksum = inputs()  # Validate before any GitHub request.
    repository, current = context(APPLY_WORKFLOW)
    now = datetime.now(timezone.utc)
    plan = get(f"{BASE}/actions/runs/{run_id}")
    validate_plan_run(plan, current, repository, now)
    definition = get(f"{BASE}/actions/workflows/plan-aws.yml")
    if definition.get("id") != plan.get("workflow_id") or definition.get("path") != PLAN_WORKFLOW or definition.get("state") != "active":
        raise ValueError("Untrusted Plan workflow ID")
    reservation = os.environ.get("PLAN_RESERVATION_ID") if stage == "verify" else None
    if stage == "verify" and not re.fullmatch(r"[1-9][0-9]*", reservation or ""):
        raise ValueError("A verified consumption reservation is mandatory before Apply")
    records = consumptions(run_id)
    validate_consumptions(records, run_id, reservation)
    directory = ROOT / ".local/reviewed-plan"
    if stage == "prepare":
        artifacts = pages(f"{BASE}/actions/runs/{run_id}/artifacts", "artifacts")
        download(select_artifact(artifacts, f"aws-plan-{run_id}-1", plan, repository, now), directory)
        download(select_artifact(artifacts, f"aws-build-{commit}", plan, repository, now), ROOT / "artifacts/aws")
    verify_files(directory, run_id, commit, checksum)
    # This script is invoked from scripts/aws; only local file verification.
    from verify_artifact import verify
    verify(ROOT / "artifacts/aws", commit)
    if stage == "consume":
        record = api(f"{BASE}/deployments", {
            "ref": commit, "task": f"energy-demo-plan-{run_id}", "auto_merge": False,
            "required_contexts": [], "environment": "energy-demo-plan-consumption",
            "production_environment": False, "transient_environment": False,
            "description": "Single-use plan consumed before AWS credentials; never reuse after failure",
            "payload": {"plan_run_id": run_id, "apply_run_id": os.environ["GITHUB_RUN_ID"], "sha256": checksum}})
        if type(record.get("id")) is not int or record["id"] <= 0:
            raise ValueError("Cannot verify recorded consumption identity")
        reservation = str(record["id"])
        validate_consumptions(consumptions(run_id), run_id, reservation)
        with open(os.environ["GITHUB_ENV"], "a") as output:
            output.write("PLAN_RESERVATION_ID=" + reservation + "\n")


def record_plan():
    directory = ROOT / "infrastructure/terraform-aws"
    commit, run_id = os.environ["GITHUB_SHA"], os.environ["GITHUB_RUN_ID"]
    digest = hashlib.sha256((directory / "reviewed.tfplan").read_bytes()).hexdigest()
    (directory / "reviewed.tfplan.sha256").write_text(digest + "  reviewed.tfplan\n")
    (directory / "reviewed-commit.txt").write_text(commit + "\n")
    (directory / "reviewed-metadata.json").write_text(json.dumps({"plan_run_id": run_id, "commit": commit,
        "sha256": digest, "configuration": configuration()}, sort_keys=True) + "\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(f"\nReviewed Plan run: `{run_id}`\n\nCommit: `{commit}`\n\nPlan SHA-256: `{digest}`\n\n"
                      f"Apply is a separate owner dispatch within 24h. Confirmation: `{CONFIRMATION}`.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["plan", "record", "prepare", "consume", "verify"])
    stage = parser.parse_args().stage
    if stage == "plan":
        context(PLAN_WORKFLOW)
    elif stage == "record":
        context(PLAN_WORKFLOW)
        record_plan()
    else:
        apply(stage)
    print("Solo-owner deployment verification passed: " + stage)


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError, KeyError, ValueError, TypeError, AttributeError, OSError, zipfile.BadZipFile, subprocess.CalledProcessError):
        # No response bodies, signed artifact URLs, credentials or input values.
        raise SystemExit("Deployment blocked: verification unavailable or rejected; review configuration or create a fresh Plan.") from None
