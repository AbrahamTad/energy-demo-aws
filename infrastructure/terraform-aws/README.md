# EnergyDemo: real AWS deployment preparation

Step 2 IAM/tables and public seeding are complete; the application release is
pending. Further AWS changes must be explicitly approved.
`../terraform-local/`, Floci, PostgreSQL and the database Lambda are independent.
See [Step 2: DynamoDB](STEP2-DYNAMODB.md) for the persistent public/private data
model, authorization, costs, migration order and exact next deployment steps.

## Stack

- Private AES256-encrypted S3 bucket; Block Public Access and bucket-owner enforcement.
- CloudFront HTTPS/default certificate, PriceClass_100, S3 Origin Access Control.
- `/api/*` routes unchanged to an HTTP API with a `$default` stage. API caching is
  disabled and the viewer Host header is excluded. No `/dev` origin prefix.
- GET `/api/energy` uses the Python 3.12 Lambda, 128 MB, three-second timeout,
  querying only the public DynamoDB table's `PUBLIC` partition.
- Separate Cognito-protected personal CRUD routes use a five-second, 128 MB
  Lambda and another table keyed by the verified access token's `sub`.
- Separate bounded execution roles access only their own table operations and
  logs. API/Lambda logs expire after seven days; logs exclude bodies and credentials.
- Both tables use on-demand billing, encryption, PITR, deletion protection and
  `prevent_destroy`. CI cannot read/write items or delete tables.
- API rate limit one request/second, burst two. These are best-effort throttles,
  not hard billing limits. No RDS, VPC/NAT gateway, custom domain, database secrets,
  provisioned concurrency, access keys, or Floci endpoints are used.
- Account-wide $5 monthly budget, actual alerts above $1/$3/$5, excluding credits
  and refunds. Notifications are delayed, not a spending cap. The budget email is
  sensitive in Terraform output but is still stored in protected plan/state files.

React keeps `fetch('/api/energy')`. The AWS-mode build labels its data correctly.
There is no cross-origin browser request, so no CORS configuration is needed.
No global SPA error mapping is configured: it must not turn API errors into HTML.
Assets are uploaded after apply, before index.html; old hashed assets are retained
to avoid breaking cached pages. S3 upload content is owned by the workflow, not
Terraform. Obsolete assets need an explicitly reviewed cleanup later.

## Files and separation

`versions.tf` pins Terraform/provider versions. The S3 backend is deliberately
partial; `scripts/aws/init_backend.py` supplies account-bound configuration only
after OIDC and identity checks:

```hcl
bucket              = "energy-demo-tfstate-<ACCOUNT_ID>-eu-north-1"
key                 = "energy-demo/aws/terraform.tfstate"
region              = "eu-north-1"
encrypt             = true
use_lockfile        = true
allowed_account_ids = ["<ACCOUNT_ID>"]
```

Bootstrap must create this separate state bucket first. No DynamoDB lock table is
needed: Terraform uses the S3 `.tflock` object. Never copy/import local Floci state
or run the real provider from `terraform-local/`. State and `.terraform/` are never
uploaded as GitHub artifacts. Saved plans expire after one day and can contain
sensitive values; restrict Actions artifact access.

## Required setup, not executed

1. Choose a dedicated learning account. Confirm its ID, billing status and Lambda
   concurrency quotas using an approved administrator session, never root keys.
2. Review `../terraform-aws-bootstrap/README.md` and its IAM policies. Bootstrap
   and initial API/CloudFront creation require separate, independently reviewed
   administrator operations. The application remains managed in this root's
   remote state; CI is an update path, not an initial-creation shortcut.
3. After initial creation, independently verify the application's output
   `deployment_resource_ids` and bind the bootstrap IAM policy to those IDs.
   Set repository variables `AWS_ACCOUNT_ID`, `AWS_BUDGET_EMAIL`, `AWS_API_ID`,
   `AWS_CLOUDFRONT_DISTRIBUTION_ID`, and `AWS_CLOUDFRONT_OAC_ID` to the reviewed
   values. Role ARNs/state bucket names are account-derived; no AWS secrets are
   configured. Missing IDs block preflight. CI has no API/CloudFront creation,
   root-deletion or tagging permissions; updates use exact resource ARNs only.
4. Configure **aws-production** for the solo-owner process: selected **main**
   branch only, administrator bypass disabled, and no required reviewers,
   wait timer or custom rules. Keep the environment name/OIDC trust unchanged.
5. Protect `main` against force pushes/deletion and require the Build AWS check.
   Restrict workflow/helper/Terraform edits. Main-branch code and the owner account
   are deployment trust boundaries; there is no independent reviewer in solo mode.

GitHub API verification must work; unavailable settings, artifact provenance,
run identity or replay history fail closed before deployment credentials.
See [the solo deployment guide](../../.github/SOLO_DEPLOYMENT.md) for feature
availability, exact manual settings and failure recovery.

## Workflow

`build-aws.yml`: PR/main/reusable CI, contents-read only, pinned action SHAs,
Node 24.21.0 and Python 3.12, `npm ci`, lint, AWS build, database/JWT/security tests,
deterministic dependency-inclusive Lambda ZIP and a same-commit SHA256 manifest. Terraform init uses
`-backend=false`; provider-mocked Terraform tests never call AWS.

`plan-aws.yml`: owner-only **workflow_dispatch from main**, validates/builds,
assumes the separate planning role, verifies account/backend, saves the exact
non-destructive plan and publishes a readable review, run ID, commit and SHA-256.
It cannot automatically continue to Apply.

`deploy-aws.yml`: a separate owner-only manual dispatch on current main requires
that reviewed Plan run ID, commit SHA, plan SHA-256 and the exact phrase
`APPLY ENERGYDEMO PRODUCTION`. Plan must have succeeded before Apply was requested,
be less than 24 hours old, and match current main and all deployment settings.
The checker verifies exact run-scoped artifacts and archive digests, then local
saved-plan/build checks and resource guards run before deployment credentials.

Both workflows share concurrency one, with cancel-in-progress disabled. A durable
GitHub consumption record is created before deploy OIDC; any failed/interrupted
attempt after consumption requires a new Plan. Reruns and replays fail closed.
Apply rechecks the reservation/expiry/main/files and only applies the saved plan;
it never silently replans. State locking remains mandatory. For complete steps
and privileged trust boundaries, see the solo deployment guide.
`check_plan.py` verifies that API/distribution/OAC before-and-after IDs match the
administrator-approved variables, and refuses all deletions/replacements or
initial creation of these three resources. They also have prevent_destroy guards.
After apply, it uploads the frontend, invalidates `/` and `/index.html`, and tests
the frontend/public API for HTTP 200 and a safe public-only response shape, plus
anonymous private-endpoint rejection. Record counts depend on the reviewed seed.

Failed smoke tests do not automatically destroy or roll back infrastructure.
Investigate before a NEW manual dispatch. There is no destroy workflow. An API
child change requiring replacement/deletion must be separately reviewed as an
administrator operation rather than weakening the saved-plan guard.

## Offline verification

From the repo root (no AWS credentials needed):

```bash
python3 -m venv /tmp/energy-demo-checks
/tmp/energy-demo-checks/bin/pip install -r tests/aws/requirements.txt
/tmp/energy-demo-checks/bin/python -m unittest discover -s tests/aws -v
cd frontend
npm ci
npm run lint
npm test -- --run
npm run build -- --mode aws
cd ..
/tmp/energy-demo-checks/bin/python scripts/aws/build_artifact.py
/tmp/energy-demo-checks/bin/python scripts/aws/verify_artifact.py
for directory in infrastructure/terraform-aws infrastructure/terraform-aws-bootstrap infrastructure/terraform-aws-auth; do
  terraform fmt -check -recursive "$directory"
  terraform -chdir="$directory" init -backend=false -input=false -lockfile=readonly
  terraform -chdir="$directory" validate
  terraform -chdir="$directory" test
done
```

Registry/npm downloads are needed, but these commands do not authenticate to AWS.
Use clean temporary source copies for Terraform checks if local backend metadata
or `.tfvars` are present, as described in the Step 2 guide.
Real Terraform plan/apply and public smoke tests are intentionally not run during
preparation. GitHub artifact/ledger APIs and OIDC cannot be end-to-end tested locally.
