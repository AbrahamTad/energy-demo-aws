# Administrator bootstrap: proposed only

This is a separate Terraform root, not a module of the application and never
called by GitHub CI/deployment. It creates real resources only after explicit
approval and an authenticated MFA/SSO administrator session. No static AWS keys.

## Proposed resources

- Dedicated state bucket `energy-demo-tfstate-<ACCOUNT_ID>-eu-north-1`: private,
  encrypted with SSE-S3, versioned, TLS-only, prevent_destroy, force_destroy=false.
- GitHub OIDC provider, or reuse the existing provider via
  `existing_oidc_provider_arn`. Inspect before creating; never replace another
  application's account-wide provider.
- Separate `/energy-demo-bootstrap/github-plan` and `github-deploy` IAM roles.
- A `/energy-demo-bootstrap/lambda-logs-boundary` managed permissions boundary.

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
and management of one execution role under `/energy-demo-aws/`. `iam:PassRole`
allows that role only, passed only to Lambda. Role creation requires the fixed
logging-only permissions boundary; the deployment role cannot remove/change the
boundary, attach managed policies, edit its own IAM role, modify the OIDC provider,
or change the bootstrap state bucket configuration. The Lambda role cannot access
databases, secrets, S3, or IAM; it writes only its own log streams.

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

IAM policies have not been tested against a real account; missing service-specific
permissions must be reviewed, not fixed by restoring broad collection permissions.

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

Order: review files and IAM → confirm account/OIDC/quotas/billing/reviewer setup →
approve administrator bootstrap plan (null resource IDs) → create bootstrap →
independently review/approve an initial administrator application plan → create
the initial stack in the application's remote state → verify its IDs/ownership →
approve the exact-ID bootstrap policy update → configure GitHub environment and
variables → manually dispatch an update plan → independent approval → CI update.
The initial administrator application backend uses the documented S3 settings;
the OIDC-only `init_backend.py` helper is for CI, not administrator sessions.
A $5 budget is part of the application plan; it is not a hard limit
and does not cover bootstrap costs before that apply. For first deployment,
configure an account billing alert before approving resource creation.

Nothing in this repository runs this order automatically. No authenticated AWS
calls, resources or GitHub settings were changed while preparing these files.
