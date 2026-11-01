# Solo-owner deployment - future operation only

Local implementation only. No deployment or GitHub configuration is approved by
this document. Cognito identity provisioning remains ON HOLD. The identity and
bootstrap Terraform roots are never applied by these workflows.

## Required GitHub configuration (manual, separately authorized)

- Preserve repository `AbrahamTad/energy-demo-aws`, personal owner `AbrahamTad`,
  default branch `main`, and the `aws-production` environment name. The checker
  compares GitHub repository/owner numeric IDs and both initiating actors with
  the exact owner. Collaborators, bots, forks and reruns are refused.
- On `aws-production`, remove independent required reviewers and wait/custom
  rules. Keep administrator bypass disabled. Select only the `main` **branch**,
  with no tags/wildcards. This environment remains the deployment OIDC subject.
- Retain existing repository AWS variables/secrets, exact API/CloudFront IDs,
  Cognito public IDs and budget email; do not add static AWS keys. Both workflows
  must resolve identical deployment settings. Keep `AWS_ENABLE_ADMIN` false
  while admin release preparation is on HOLD.
- Allow the existing pinned actions and GITHUB_TOKEN permissions: Plan uses
  contents/actions/deployments read; Apply additionally needs deployments write
  for the durable single-use ledger. Only the AWS Plan/Apply jobs receive
  id-token write. No AWS IAM/OIDC change is proposed.
- Keep Actions artifacts at least one day. Plan artifacts retain one day; build
  artifacts retain two. GitHub must expose artifact SHA-256 digests, run metadata,
  environment settings, deployment records and branch-policy APIs. Missing fields,
  permissions, unsupported features or API failures block progress.
- GitHub Free/Pro/Team restrict independent environment reviewers to public repos.
  This design does not use that feature. Private repositories still need a plan
  supporting environments and selected deployment branches (Pro/Team/Enterprise).
  Support is checked through actual environment APIs; there is no unguarded
  fallback. See [GitHub environment availability](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
- Protect `main` against force pushes and deletion; require passing build checks
  where supported. Restrict workflow edits and token access. Account MFA/passkeys
  are recommended. A single owner can change these controls, so they cannot
  provide independent protection against owner-account compromise.

## Step 1: Plan AWS (manual)

After separately approved changes reach main, owner dispatches `plan-aws.yml` on
main. The workflow verifies owner/run/environment identity, runs the existing
build/test/Terraform validation, assumes only `github-plan`, locks the existing
state backend, saves the plan, runs resource guards, and publishes its readable
review, commit SHA, run ID and plan SHA-256. It never calls Apply or dispatches a
second workflow. Push/PR builds stay automatic and have no deployment credentials.

Review the complete plan and resource counts. The guard rejects destroys and
replacements and preserves exact bootstrap IDs, but some creates/updates remain
allowed and still need review. Terraform plans/artifacts can contain sensitive
values; avoid copying them to issues or public logs. Existing readable plan
summary behavior is retained; review sensitivity before deployment.

## Step 2: Apply AWS (manual, reviewed plan only)

Owner starts a **new** `deploy-aws.yml` dispatch on main after Plan succeeds:

- `plan_run_id`: successful first-attempt Plan run ID.
- `commit_sha`: exact reviewed 40-character SHA, still current main.
- `plan_sha256`: exact reviewed 64-character binary-plan SHA-256.
- `confirmation`: exactly `APPLY ENERGYDEMO PRODUCTION`.

Inputs are passed as environment values, never interpolated into shell code.
Plan must finish before Apply was requested and be less than 24 hours old,
measured from Plan creation. Both runs/workflow IDs, repo/owner IDs, commit,
artifact provenance/digests, saved files and deployment configuration must match.
Build comes from the **same Plan run**, not an arbitrary same-commit build.
Artifact archives are digest-verified before safe extraction; auth headers never
follow redirects to artifact storage.

Before deployment credentials, Apply verifies the saved plan/resource guards and
creates a durable GitHub Deployment metadata record with task
`energy-demo-plan-<run-id>` and environment `energy-demo-plan-consumption`.
This is a replay ledger, not an AWS deployment or a replacement OIDC environment.
It uses auto_merge=false and never merges code. Shared workflow concurrency
serializes consumers; existing records refuse replay even after failed or canceled
Apply. An ambiguous API response fails closed. Do not delete ledger records.

Only then can Apply assume the existing `github-deploy` role. It rechecks owner,
main, expiry, reservation and exact plan/build bytes, checks account and state
locking, applies only the saved plan, then uploads that Plan's frontend and runs
the existing smoke checks. No plan is regenerated during Apply.

## Failures and remaining boundaries

Never rerun Plan or Apply. Generate a new Plan and explicitly confirm it again
after failures, expiry, main/configuration changes, missing artifacts, consumed
plans or interrupted reservations. Terraform rejects stale state; stop and
reconcile partial applies before creating a new Plan. An Apply can finish its
Terraform step and fail during frontend publishing; automatic retry is forbidden.

GitHub concurrency does not serialize a separate administrator using Terraform;
state locking remains mandatory. AWS drift can occur after review. Artifact and
ledger deletion, workflow modification, repo/owner compromise or direct AWS
administrator access remain privileged trust boundaries. GitHub metadata writes
are required for replay protection; network failures reduce availability instead
of bypassing checks. Live GitHub/OIDC compatibility has not been exercised locally.
