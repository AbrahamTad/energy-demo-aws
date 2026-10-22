"""Fail closed unless GitHub enforces main-only independent deployment approval."""
import argparse
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPOSITORY = "AbrahamTad/energy-demo-aws"
ENVIRONMENT = "aws-production"


def get(path):
    request = Request("https://api.github.com/" + path, headers={
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def required_reviewers(environment):
    return {
        reviewer["reviewer"]["login"].lower()
        for rule in environment.get("protection_rules", [])
        if rule.get("type") == "required_reviewers" and rule.get("prevent_self_review") is True
        for reviewer in rule.get("reviewers", [])
        if reviewer.get("type") == "User" and reviewer.get("reviewer", {}).get("login")
    }


def validate_environment(environment, policies):
    if not required_reviewers(environment):
        raise ValueError("A direct required User reviewer with self-review prevention is required; team-only rules are not supported")
    branch = environment.get("deployment_branch_policy") or {}
    if branch.get("custom_branch_policies") is not True:
        raise ValueError("Environment must use selected deployment branches")
    entries = policies.get("branch_policies", [])
    if len(entries) != 1 or entries[0].get("name") != "main" or entries[0].get("type", "branch") != "branch":
        raise ValueError("Environment must allow only the main branch, with no tags/wildcards")


def validate_attempt(attempt):
    # Review history has no reliable per-attempt binding. Reusing a run is unsafe:
    # force a new manual dispatch/run ID and a new environment approval instead.
    if str(attempt) != "1":
        raise ValueError("Reruns cannot prove fresh approval; start a NEW manual deployment run")


def validate_run(run, run_id, commit):
    validate_attempt(run.get("run_attempt"))
    if (str(run.get("id")) != run_id or run.get("head_sha") != commit
            or not re.fullmatch(r"[a-f0-9]{40}", commit)
            or run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main"
            or run.get("repository", {}).get("full_name") != REPOSITORY
            or run.get("head_repository", {}).get("full_name") != REPOSITORY
            or run.get("path", "").split("@")[0] != ".github/workflows/deploy-aws.yml"):
        raise ValueError("Cannot verify this deployment run, repository and commit")


def validate_approval(reviews, environment_id, actor, triggering_actor=None, *, run_attempt, reviewer_logins):
    validate_attempt(run_attempt)
    if not actor or not isinstance(reviews, list):
        raise ValueError("Cannot verify the deployment initiator or reviews")
    initiators = {actor.lower(), (triggering_actor or actor).lower()}
    relevant = [r for r in reviews if any(
        e.get("id") == environment_id for e in r.get("environments", [])
    )]
    # Ambiguous/rejected/multiple decisions require a fresh dispatch, not a guess
    # about API ordering. This also refuses an admin bypass after a rejection.
    if len(relevant) != 1:
        raise ValueError("Exactly one fresh approval for this environment is required")
    review = relevant[0]
    reviewer = review.get("user", {}).get("login", "")
    if (review.get("state") != "approved" or not reviewer or reviewer.lower() in initiators
            or reviewer.lower() not in reviewer_logins):
        raise ValueError("No independent approval recorded; bypass is refused")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-approval", action="store_true")
    args = parser.parse_args()
    validate_attempt(os.environ.get("GITHUB_RUN_ATTEMPT"))
    if (os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        raise ValueError("Manual deployments are restricted to this repository's main branch")
    account = os.environ.get("TF_VAR_account_id", "")
    if not re.fullmatch(r"[0-9]{12}", account) or account == "000000000000":
        raise ValueError("Configure a real AWS_ACCOUNT_ID repository variable")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", os.environ.get("TF_VAR_budget_email", "")):
        raise ValueError("Configure AWS_BUDGET_EMAIL repository variable")
    for key, pattern in {
        "AWS_API_ID": r"[a-z0-9]{1,32}",
        "AWS_CLOUDFRONT_DISTRIBUTION_ID": r"[A-Z0-9]{1,64}",
        "AWS_CLOUDFRONT_OAC_ID": r"[A-Z0-9]{1,64}",
    }.items():
        if not re.fullmatch(pattern, os.environ.get(key, "")):
            raise ValueError("Configure administrator-verified " + key + "; creation is not permitted in CI")
    base = f"repos/{REPOSITORY}"
    run_id = os.environ["GITHUB_RUN_ID"]
    if not run_id.isdigit():
        raise ValueError("Invalid workflow run ID")
    run = get(f"{base}/actions/runs/{run_id}")
    validate_run(run, run_id, os.environ["GITHUB_SHA"])
    environment = get(f"{base}/environments/{ENVIRONMENT}")
    policies = get(f"{base}/environments/{ENVIRONMENT}/deployment-branch-policies?per_page=100")
    validate_environment(environment, policies)
    if args.require_approval:
        reviews = get(f"{base}/actions/runs/{run_id}/approvals")
        validate_approval(reviews, environment["id"], os.environ["GITHUB_ACTOR"],
                          os.environ.get("GITHUB_TRIGGERING_ACTOR"),
                          run_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
                          reviewer_logins=required_reviewers(environment))
    print("GitHub deployment protections verified.")


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError, KeyError, ValueError) as error:
        # Never dump HTTP request headers/tokens or continue on unavailable features.
        message = str(error) if isinstance(error, ValueError) else "GitHub protection checks unavailable"
        raise SystemExit("Deployment blocked: " + message) from None
