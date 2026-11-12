# Administrator bootstrap

This is a separate Terraform root, not a module of the application and never
called by GitHub CI/deployment. It creates real resources only after explicit
approval and an authenticated MFA/SSO administrator session. No static AWS keys.
The Step 2 IAM changes are deployed and verified; Step 2.4 must not reapply this
root. See the current release status in the DynamoDB guide below.

## Resources

- Dedicated state bucket `energy-demo-tfstate-<ACCOUNT_ID>-eu-north-1`: private,
  encrypted with SSE-S3, versioned, TLS-only, prevent_destroy, force_destroy=false.
- GitHub OIDC provider, or reuse the existing provider via
  `existing_oidc_provider_arn`. Inspect before creating; never replace another
  application's account-wide provider.
- Separate `/energy-demo-bootstrap/github-plan` and `github-deploy` IAM roles.
- The existing `/energy-demo-bootstrap/lambda-logs-boundary` boundary, expanded
  only to allow Query on the public table's `PUBLIC` partition.
- A separate `/energy-demo-bootstrap/user-energy-boundary` for the private
  Lambda's exact-table CRUD and its own logs.

Inputs: `account_id`, `github_subject_prefix`, optional `existing_oidc_provider_arn`,
and optional `deployment_resource_ids` (default null).
The prefix is mandatory and must be verified from this repository's OIDC subject
format. Examples are `repo:AbrahamTad/energy-demo-aws:` or, for immutable claims,
`repo:AbrahamTad@<OWNER_ID>/energy-demo-aws@<REPO_ID>:`. Do not guess IDs or add `*`.

Plan trust appends `ref:refs/heads/main`; deploy trust appends
`environment:aws-production`. Both require `aud=sts.amazonaws.com` and the
account's exact GitHub provider ARN. Branch restrictions for the environment are
enforced by GitHub and checked by the workflow. Repository creation date alone
does not prove which subject format is active.

## IAM scope and limitations

Plan has read access to the application's resource scopes and the exact state
object. It can create/delete only the `.tflock` object for locking, not write
application state or change infrastructure. Neither role can delete the state.

Deploy adds named frontend-bucket/object writes, exact Lambda/log/budget scopes,
and management of two named execution roles under `/energy-demo-aws/`.
`iam:PassRole` allows only those roles, passed only to Lambda. Each role can only
be created with its own fixed permissions boundary. The deployment role cannot
remove/change boundaries, attach managed policies, edit its own IAM role, modify
the OIDC provider, or change the bootstrap state bucket configuration. The public
Lambda can Query only the public table's `PUBLIC` partition. The private Lambda
has only Query/GetItem/PutItem/UpdateItem/DeleteItem on the private table. Each
role writes only its own log streams; neither has secrets, S3 or IAM access.

For Step 2, CI can describe/manage the two exact EnergyDemo DynamoDB tables, but
has no item operations, Scan or DeleteTable. There are no wildcard table grants.
The provider's encryption refresh can only DescribeKey when requesting the
regional `alias/aws/dynamodb`; it cannot use or manage KMS keys.
Review/apply the administrator-managed IAM changes before releasing the new
application. See the [DynamoDB migration guide](../terraform-aws/STEP2-DYNAMODB.md)
for the table-first public seed and separate identity-state protections.

There are no API/CloudFront creation or account-wide mutation permissions in the
GitHub roles. With `deployment_resource_ids = null`, they have NO API/CloudFront
access. An administrator must perform the initial application creation as a
separate, explicitly reviewed operation, using the application Terraform root
and its remote state. This avoids granting CI permissions over unknown IDs.

After that operation, obtain `terraform output -json deployment_resource_ids`
from the application state. Independently verify the account, API name, distribution
origins, OAC name and EnergyDemo tags before supplying the resulting object:

```hcl
deployment_resource_ids = {
  api_id                     = "<EXACT_HTTP_API_ID>"
  cloudfront_distribution_id = "<EXACT_DISTRIBUTION_ID>"
  cloudfront_oac_id          = "<EXACT_OAC_ID>"
}
```

These placeholders are intentionally invalid until replaced with actual verified
IDs. Bootstrap rejects wildcard/path inputs. Review a second bootstrap plan to
bind the roles to those exact IDs. Then set the same GitHub repository variables:
`AWS_API_ID`, `AWS_CLOUDFRONT_DISTRIBUTION_ID`, `AWS_CLOUDFRONT_OAC_ID`.

CI may PATCH the exact API root, manage routes/integrations/stages only below that
API, update the exact distribution/OAC, and invalidate that distribution's cache.
The only API ARN wildcard is `/apis/<EXACT_ID>/*`, for children of that API. CI has
no API-root DELETE, distribution/OAC DELETE, creation, or tagging grants. Tag changes,
replacement, recovery after deletion, and initial creation require administrator
review. Plan validation also refuses deletions/replacements and wrong/missing IDs.

The Step 2 boundaries and GitHub policies were read back from the real account
and matched bootstrap state. Execution through Actions still needs the normal
release checks; missing service-specific permissions must be reviewed, not fixed
by restoring broad collection permissions.

IAM and CloudFront are global; API/Lambda/log scopes are Stockholm. Avoid a blanket
region-deny policy that would accidentally block global-service operations.

## State bootstrapping and approval order

The bootstrap starts with a distinct ignored local state at
`.local/terraform-aws-bootstrap.tfstate`, because its S3 bucket does not exist yet.
Protect `.local/` and back up bootstrap state privately. It never shares the Floci
state or application state. After the bucket exists, application state uses only
`energy-demo/aws/terraform.tfstate` with native S3 lockfiles and account guards.
Bootstrap-state migration to a separate protected S3 key is a later administrator
operation with its own reviewed backend change; do not manually upload a stale
state file or mix it with application state.

## Read-only preflight for an existing bootstrap

Historical deployment notes above are not evidence of current ownership or drift.
Before preparing another bootstrap plan:

1. Use the operator-selected authenticated AWS profile. Verify STS account and
   caller against the approved EnergyDemo account; explicitly select `eu-north-1`.
   An expired session must be reauthenticated by the operator. Never print
   credentials, authentication-cache contents or secret values.
2. Establish the authoritative bootstrap backend and state with its owner. The
   checked-in backend resolves to this worktree's
   `.local/terraform-aws-bootstrap.tfstate`; absence of that file does not mean
   bootstrap resources are absent. Stop rather than initialize an empty state,
   copy another worktree's state, migrate a backend or use the application's S3
   state as bootstrap state. Inspect only necessary state metadata and resource
   addresses privately; do not print or commit state contents.
3. Coordinate with every bootstrap/application writer and obtain an explicit
   no-write window. Check running and queued GitHub Plan/Apply workflows. Their
   `energy-demo-real-aws` concurrency group does not coordinate local Terraform
   processes or other administrator sessions. An idle Actions queue or absent
   lock alone does not establish exclusive access. Do not create, remove or
   force-unlock locks during this preflight.
4. Use scoped read-only IAM inspection to verify the five policies
   `/energy-demo-bootstrap/contact-{api,relay,worker,admin,events}-boundary`.
   Compare default policy versions with the reviewed Contact policy module,
   including the intended sending gate. Verify exact account, path, ownership,
   attachment consumers and resource scopes; policy existence alone is not a
   policy-content or drift check. Do not read Contact messages or secret values.
5. Inventory `/energy-demo-bootstrap/admin-admin-boundary` and
   `/energy-demo-bootstrap/admin-private-boundary`. These are the two Admin
   boundaries selected by `enable_admin=true` with
   `admin_email_testing_enabled=false`. The `admin-email-boundary` and
   `admin-events-boundary` policies belong to the separately approved email-test
   mode. Record each observed presence/absence; do not infer it from source or
   assume a missing policy is safe to create without resolving state ownership.
6. Validate Terraform in an isolated source copy with backend access disabled,
   following the offline validation instructions in
   [ADMIN.md](../terraform-aws/ADMIN.md#offline-validation). Do not initialize the
   live backend merely to validate source. This does not establish live drift.
7. Only after account, authoritative state, inputs, ownership and the no-write
   window are verified, prepare a normal refresh-enabled saved plan with
   `-input=false -lock=false`. Keep the plan and its JSON inspection private in
   an ignored directory. Do not run refresh-only apply, state commands that
   mutate state, imports, backend migration or Apply. Review every resource's
   before/after actions, refresh drift, data reads and output changes. Report the
   actual add/change/destroy counts and all replacements; never assume
   `2 adds / 0 changes / 0 destroys`. Stop if a resource is already owned by a
   different state or any prerequisite is uncertain.

Keep Contact sending, Admin email testing, CI activation and identity/membership
gates at their separately approved settings. Karl's Admin membership remains
ON HOLD. A reviewed plan grants no permission to apply it or activate production.

Order: review files and IAM → confirm account/OIDC/quotas/billing/solo-owner controls →
approve administrator bootstrap plan (null resource IDs) → create bootstrap →
independently review/approve an initial administrator application plan → create
the initial stack in the application's remote state → verify its IDs/ownership →
approve the exact-ID bootstrap policy update → configure GitHub environment and
variables -> manual Plan -> owner reviews plan/hash -> separate manual Apply.
The initial administrator application backend uses the documented S3 settings;
the OIDC-only `init_backend.py` helper is for CI, not administrator sessions.
A $5 budget is part of the application plan; it is not a hard limit
and does not cover bootstrap costs before that apply. For first deployment,
configure an account billing alert before approving resource creation.

Nothing in this repository runs this order automatically. No authenticated AWS
calls, resources or GitHub settings were changed while preparing these files.
