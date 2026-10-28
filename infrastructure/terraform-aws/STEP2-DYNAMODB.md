# Step 2: persistent energy records

Status on 2026-10-28: the administrator-managed IAM changes and both tables are
deployed. The four reviewed public seed records were read back and verified;
the application/private API release is still pending. The commands below retain
the migration history and must not be replayed as a release shortcut.
The existing application root and state key remain `energy-demo/aws/terraform.tfstate`.
The deployed Cognito pool/client remain in the separate identity root and its
`energy-demo/auth/terraform.tfstate` key. CI never reads or applies that root.
Local Floci/PostgreSQL files and the separate `lambda/energy-db/` are unchanged.

## Data and authorization

| Resource | Purpose | Access |
| --- | --- | --- |
| `energy-demo-aws-public-energy` | Reviewed public snapshot; partition `dataset=PUBLIC`, sort key `source` | Existing public Lambda: Query only, restricted to `PUBLIC` |
| `energy-demo-aws-user-energy` | Personal records; partition `user_sub`, sort key UUID `record_id` | Separate private Lambda: Query/GetItem/PutItem/UpdateItem/DeleteItem on this table only |

These are on-demand DynamoDB Standard tables with encryption at rest, an
AWS-managed DynamoDB key, point-in-time recovery, deletion protection and
Terraform `prevent_destroy`. Each table caps on-demand read/write throughput at
10/5 request units per second. These caps and API throttling are best effort,
not a billing limit. There are no indexes, streams, VPC/NAT gateways or new
customer-managed KMS keys. CI can manage these two exact tables but has no
item access, Scan or DeleteTable permission. Separate administrator-managed
permissions boundaries limit each Lambda to its own logs and table operations.
CI also has only `kms:DescribeKey` for `kms:RequestAlias=alias/aws/dynamodb`
in this account/region, because the pinned provider resolves that alias during
refresh to avoid false encryption drift. It has no key usage/management grants.

`GET /api/energy` stays public with the same `{project,status,records}` response
and `{source,production,unit}` entries. It queries only the public table's
`PUBLIC` partition and serializes an explicit field allowlist. It never reads
private records or falls back to hardcoded examples. An empty table returns an
empty list; snapshots above 100 records fail with a sanitized service error.

Private routes use `Authorization: Bearer <Cognito access token>`:

| Method and path | Result |
| --- | --- |
| `GET /api/me/energy` | `{records,next_cursor}`, up to 25 records; optional `?cursor=<record UUID>` |
| `POST /api/me/energy` | 201, created record |
| `GET /api/me/energy/{record_id}` | 200, owned record |
| `PUT /api/me/energy/{record_id}` | 200, replacement of editable fields |
| `DELETE /api/me/energy/{record_id}` | 204 |

POST/PUT accept exactly this shape (production is a JSON number):

```json
{"source":"Solar","production":12.345,"unit":"kWh","measured_at":"2026-10-27T12:00:00Z"}
```

Source length is 1–64, production is 0–1 billion with at most three decimal
places, and timestamps require a timezone and years 2000–2100. Bodies are limited
to 4 KB. Responses add `id`, `measured_at` and `updated_at`; they omit the owner.
User IDs and ownership fields in the request body/query are rejected. Missing
records and another user's records both return 404. Updates cannot create an
unowned record. Pagination keys always use the verified caller's partition.

API Gateway requires the existing Cognito issuer, public SPA client and
`aws.cognito.signin.user.admin` scope. The Lambda independently verifies RS256
signatures against that fixed issuer's HTTPS JWKS, expiration, issue time,
issuer, `token_use=access`, `client_id`, scope and UUID `sub`. It does not trust
client-supplied claims or use ID tokens for API access. Keys are cached for five
minutes. Identity/database outages fail closed. As with standard offline JWT
verification, a previously issued access token can remain valid until its
15-minute expiry after sign-out; refresh/session handling remains with Cognito.

CloudFront continues to disable API caching and remove the viewer Host header.
Its allowed method set expands to permit writes; API Gateway exposes only the
five explicit protected routes and the existing public GET. Access logs omit
bodies and credentials; both Lambdas return sanitized errors. The private
dashboard sends access tokens from Amplify's memory storage, bypasses caches,
and clears personal data on account changes or authentication failure. It has
loading/error/empty states, create/edit/delete forms, confirmation and pagination.
The public dashboard reads the public database snapshot. User records are never
automatically promoted into public data. A future publisher needs separate review.

## Costs

The [AWS Stockholm price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonDynamoDB/current/eu-north-1/index.json)
lists Standard on-demand writes at $0.67/million request units, reads at
$0.1345/million, storage at $0.269/GB-month, and PITR at $0.21/GB-month
(USD, checked 2026-10-27). For example, 10,000 read units, 1,000 write units and
0.05 GB total across both tables cost about **$0.03/month** before free allowances.
Strongly consistent reads use more units than eventual reads; sizes and actual
request units matter. Existing Lambda/API Gateway/CloudFront/logging/Cognito
charges, any applicable KMS requests and taxes are additional. PITR protects
data but does not expire it; implement retention later if needed. Existing budget
alerts remain and are delayed notifications rather than spending caps.

## Local checks

Use Node 24.21.0 and Python 3.12 (CI runtime). From the repository root:

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
```

The package builder downloads hash-locked, binary-only Python 3.12 Linux x86_64
wheels for PyJWT/cryptography and their dependencies. Development Moto/boto3
test dependencies are not shipped. boto3 comes from the Lambda runtime. ZIP
verification checks expected modules, dependencies, paths, size and manifest hashes.

Terraform checks use `init -backend=false -input=false -lockfile=readonly`,
`validate`, and provider-mocked `test` in all three roots. Run them in clean
temporary copies containing only tracked/source `.tf`, lock and test files plus
the built `artifacts/aws/lambda.zip` at its expected relative path. This avoids
real backend metadata, local `.tfvars` and administrator credentials. Do not copy
state, saved plans or `.terraform/` into the checks. Python tests use Moto and
locally signed JWTs; frontend SDK doubles exist only in tests. No live AWS CRUD
or Cognito sign-ins are part of these checks.

## Migration and next deployment steps — approval required

No commands below that write AWS have been run. Review the code and changes
first; do not commit/push or deploy without the requested approval. A full
deployment before seeding can briefly show an empty public snapshot. To preserve
the existing public records, use this one-time administrator migration order:

1. Refresh the `energy-demo-admin` SSO session and confirm STS account
   `628582070745`. In the **bootstrap root**, review a saved plan using its
   existing protected local state/configuration. Approve and apply only the IAM
   changes: the existing public boundary gains Query on the public table's
   `PUBLIC` partition; the new private boundary and exact two-table management
   permissions are added. The CI role cannot modify these boundaries itself.
   Do not initialize or move bootstrap state into application/identity state.

   ```bash
   aws sts get-caller-identity --profile energy-demo-admin --region eu-north-1 \
     --query Account --output text
   AWS_PROFILE=energy-demo-admin terraform -chdir=infrastructure/terraform-aws-bootstrap plan \
     -out=bootstrap-reviewed.tfplan
   AWS_PROFILE=energy-demo-admin terraform -chdir=infrastructure/terraform-aws-bootstrap show \
     -no-color bootstrap-reviewed.tfplan
   ```

   Keep the existing approved bootstrap variables and local backend. Do not
   share saved plans or their output; they can contain sensitive configuration.
2. Build and verify the artifacts using the commands above. In the **application
   root only**, initialize the existing backend if needed:

   ```bash
   AWS_PROFILE=energy-demo-admin terraform -chdir=infrastructure/terraform-aws init \
     -input=false -reconfigure \
     -backend-config=bucket=energy-demo-tfstate-628582070745-eu-north-1 \
     -backend-config=key=energy-demo/aws/terraform.tfstate \
     -backend-config=region=eu-north-1 -backend-config=encrypt=true \
     -backend-config=use_lockfile=true \
     '-backend-config=allowed_account_ids=["628582070745"]'
   ```

   Do not use the OIDC-only CI initializer with an administrator session. Keep
   the existing account/budget variable inputs and resource-ID approvals.
3. As a one-time migration exception, produce and review a **table-only** plan:

   ```bash
   AWS_PROFILE=energy-demo-admin terraform -chdir=infrastructure/terraform-aws plan \
     -target=aws_dynamodb_table.public_energy \
     -target=aws_dynamodb_table.user_energy -out=database-reviewed.tfplan
   AWS_PROFILE=energy-demo-admin terraform -chdir=infrastructure/terraform-aws show \
     -no-color database-reviewed.tfplan
   ```

   Supply the root's existing required variables as usual. Confirm exactly two
   table creations with the protections above, no destruction and no other
   changes. After separate explicit approval, apply only that saved plan. This
   targeted initial migration is not the normal CI update path; the full-plan
   CI guard still requires the existing API/distribution/OAC and is unchanged
   in that respect. Never weaken that guard to accept a partial plan.
4. Review an input containing **public data only**. The optional
   `scripts/aws/public_energy_seed.json` preserves the four previously published
   example values and is explicitly not metered production data. Use it only
   if retaining those published examples is intended; otherwise supply a
   reviewed real snapshot in the same `{records:[...]}` format. Validate offline:

   ```bash
   /tmp/energy-demo-checks/bin/python scripts/aws/seed_public_energy.py \
     --file scripts/aws/public_energy_seed.json --account-id 628582070745
   ```

   This defaults to dry run, prints the input hash/target/count and makes no AWS
   calls. After approval, repeat the exact command with
   `--profile energy-demo-admin --execute`. The tool verifies the STS account,
   ignores configured service endpoint overrides, and inserts only missing
   `PUBLIC` source keys in the exact public table; existing keys are skipped,
   never overwritten. Verify skipped entries separately before proceeding.
   Private data is not imported or published; the private table starts empty.
5. After review and approval to release, commit/push the related files and run
   the existing **new** `Deploy AWS (manual)` dispatch on main. Review its full
   application plan before approval: two tables should now be unchanged; the
   private Lambda/role/log group, authorizer, routes and permissions are new;
   public Lambda code/env/IAM and CloudFront allowed methods update in place.
   Expect **no removals/replacements**, origin/Host/cache policy changes,
   Cognito resources or identity-state changes. The normal same-commit artifact,
   saved-plan and environment approval protections remain in force.
6. After release, check public `/api/energy`, anonymous private GET rejection,
   and register/verify/login. With two real test accounts, create/read/edit/delete
   a private record and confirm the other account cannot list/read/change it or
   discover its owner; confirm public output stays unchanged. Check loading,
   empty, error, pagination, logout and mobile flows. Smoke tests check public
   response allowlists and unauthenticated private denial, never private writes.

Do not apply the Cognito root again. Back up data before future schema changes;
the destroy/deletion guards are intentional and must not be removed to deploy.

## Step 2.4: exact release scope and safe release order

Preparation checks on 2026-10-28 passed: 38 Python tests in the offline Lambda
Python 3.12 image, 33 frontend tests, lint, production build, artifact verification,
and fmt/validate plus 11 provider-mocked Terraform tests across all three roots.
The fresh full application plan matched 17 creates/2 updates/0 destroys with
both tables unchanged. JWT scope/issuer/client, separate IAM boundaries and
cross-user isolation checks passed. Live GitHub environment/variable checks
passed the existing gate; local main matched origin/main. Actual Actions checks
must still run against the future committed release. Live two-account acceptance
remains a post-deployment check. Terraform's state-pull validation-metadata order
varied, but canonical contents and the S3 state version were unchanged.

The release contains exactly **36 files**: the following explicit staging command
is the allowlist. It includes the already-deployed bootstrap/table source changes
so Git records the reviewed infrastructure. It excludes the Cognito root, all
state/backups/plans, `.terraform/`, `.tfvars`, `.env.local`, generated artifacts,
`infrastructure/terraform-aws-bootstrap/--profile`, both unrelated files under
`infrastructure/terraform-local/`, and the unrelated `lambda/energy-db/` tree.
The historical first-release scope in `frontend/README.md` is not this release.

Nothing has been staged, committed, pushed or deployed during release preparation.
After explicit approval to commit, from the repository root:

```bash
git add -- \
  .github/workflows/build-aws.yml \
  frontend/README.md \
  frontend/src/App.css \
  frontend/src/components/UserRecords.test.tsx \
  frontend/src/components/UserRecords.tsx \
  frontend/src/lib/user-energy.ts \
  frontend/src/pages/AccountPages.tsx \
  frontend/src/pages/EnergyPages.tsx \
  infrastructure/terraform-aws-bootstrap/README.md \
  infrastructure/terraform-aws-bootstrap/main.tf \
  infrastructure/terraform-aws-bootstrap/tests/offline.tftest.hcl \
  infrastructure/terraform-aws/README.md \
  infrastructure/terraform-aws/STEP2-DYNAMODB.md \
  infrastructure/terraform-aws/api.tf \
  infrastructure/terraform-aws/database.tf \
  infrastructure/terraform-aws/frontend.tf \
  infrastructure/terraform-aws/iam.tf \
  infrastructure/terraform-aws/tests/offline.tftest.hcl \
  infrastructure/terraform-aws/user-api.tf \
  infrastructure/terraform-aws/variables.tf \
  lambda/energy/energy_auth.py \
  lambda/energy/energy_store.py \
  lambda/energy/energy_validation.py \
  lambda/energy/handler.py \
  lambda/energy/requirements-lambda.txt \
  lambda/energy/user_handler.py \
  scripts/aws/build_artifact.py \
  scripts/aws/check_plan.py \
  scripts/aws/public_energy_seed.json \
  scripts/aws/publish_frontend.py \
  scripts/aws/seed_public_energy.py \
  scripts/aws/verify_artifact.py \
  tests/aws/requirements.txt \
  tests/aws/test_database_safeguards.py \
  tests/aws/test_deployment.py \
  tests/aws/test_energy_database.py
git diff --cached --check
git diff --cached --name-status
git diff --cached
```

Check that the staged names match all 36 entries exactly, and review the entire
staged diff for secrets, unrelated changes and security regressions. Do not use
`git add .` or stage directory trees. If the scope changes, review it again.

When explicitly authorized, commit the reviewed index:

```bash
git commit -m "feat: persist energy records in DynamoDB with Cognito-protected CRUD"
```

Push only after separate authorization and a fresh synchronization check:

```bash
git fetch origin main
git merge-base --is-ancestor origin/main HEAD
git log --oneline origin/main..HEAD
git diff --name-only origin/main..HEAD
git push origin HEAD:main
```

Confirm the remote base is the reviewed first-release commit, the outgoing log
contains only this release commit, and its file list matches the allowlist. If
remote main moved, stop and reconcile/review the new base; never force-push.
If branch protection requires a PR, use that review path instead of bypassing it.

Wait for **Build AWS** on the new commit. Local artifacts currently contain
uncommitted source and must not be deployed: CI must rebuild the committed source
and bind its manifest to that commit. After separate deployment approval, start
a **new** manual dispatch on main (not a rerun):

```bash
gh workflow run deploy-aws.yml --repo AbrahamTad/energy-demo-aws --ref main
```

Review that run's newly generated, non-targeted saved plan before allowing it to
proceed. Expect **17 creates, 2 updates, 0 destroys/replacements**: the private
Lambda/role/log group, two execution policies, JWT authorizer/integration, five
routes and five invocation grants are new; only public Lambda code/environment
and CloudFront API allowed methods update. Both existing tables must be no-op.
Cognito, CloudFront origins, API cache-disabled/Host-removal policies and all
other existing resources must remain unchanged. Keep the existing workflow's
main-only/manual-dispatch, fresh-run, OIDC, account, artifact-hash, exact-ID and
saved-plan safeguards. Do not alter GitHub protection settings to make it run.

Do not reapply bootstrap, re-create tables, reapply Cognito, re-seed, or use a
local administrator apply to release the app. If the plan differs from the
reviewed scope, investigate and obtain a new review before proceeding. After
deployment, complete the two-account live authorization/CRUD acceptance checks
in step 6 above. Offline tests validate the enforcement logic; they do not
replace live Cognito/API Gateway acceptance.
