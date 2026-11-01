# Admin dashboard: coding complete, deployment pending

## Release baseline

Admin source is isolated on `feature/admin-release-preparation`, based on main
`7bc602bc4dada693dc6600bcba679e2d4b9a2df8` (merged compatibility-test PR #2).
The solo-owner Plan/Apply safeguards are already merged. Admin source remains
uncommitted and no Admin AWS provisioning/deployment is authorized by this file.
Historical normal-app workflow success is not evidence of current AWS drift.
Use fresh identity/bootstrap/application saved plans; do not reuse older approvals.
Local artifacts contain uncommitted source and must never be deployed directly.

## Implemented boundary

- `/admin` and `/admin/` rewrite only to the SPA entry. Existing hash routes and
  `/api/*` behavior remain intact; no global error-to-HTML fallback is added.
- Every admin API requires the existing Gateway JWT authorizer and independent
  Lambda verification of the RS256 signature, issuer, client, expiry, access-token
  use and signed `energy-demo-admin` group. Every request checks current enabled
  user, current group membership (paginated) and preferred TOTP MFA in Cognito.
  A token-authorized `GetUser` call also rejects revoked/global-signed-out tokens;
  signature validation alone cannot detect revocation.
- The normal Cognito pool remains optional-MFA for ordinary users. Admin entry
  requires a separate IAM-only `ADMIN_USER_PASSWORD_AUTH` client: password starts
  a real `SOFTWARE_TOKEN_MFA` challenge; code completion must return a verified
  access token for the same subject and dedicated client. A token-bound proof
  lasts at most 15 minutes and never outlives the original access token.
  Passwords and returned tokens are never stored or logged. Challenge sessions
  expire logically after three minutes; five step-up calls/admin/UTC minute.
- Read-only directory pages contain only sub, enabled and account status. Cognito
  is asked for only the `sub` attribute. Pages are capped at 25. Opaque cursors
  bind to actor and route, expire after 15 minutes and cannot select an owner.
- Public records query only `PUBLIC`. Personal records use a short-lived assumed
  read-only role with `dynamodb:LeadingKeys = aws:PrincipalTag/user_sub`. The
  admin Lambda has no direct private-table data permissions. No Scan, user
  mutation, group mutation or cross-user record endpoint exists.
- Audit entries contain actor, operation, outcome and time, never payloads or
  tokens. Successful admin operations and reserved email tests are retained for
  30 days. API logs contain existing safe request metadata; logs expire in seven
  days. Control data is encrypted, backed up and deletion protected. TTL cleanup
  is eventual; expiry is explicitly checked for proof, challenge, cursor and
  email status access. PITR backups can retain older expired data.

## SES safety and status

The operator selects a fixed sender and 1–5 individually SES-verified recipient
addresses in Stockholm. The backend checks verification at send time. Both its
IAM policy and operator-managed permissions boundary pin sender and recipients.
The fixed plain-text test message accepts no subject, body, attachments, CC or BCC.
Cognito's built-in account email is not used for arbitrary test messages.

One DynamoDB transaction reserves the request ID, an admin cooldown of 60 seconds
and an account-wide cap of ten requests/UTC day. Reservations are not refunded
on failure. Idempotency is retained at least 30 days, including pending, failed
and ambiguous sends. Network/5xx failures are `unknown` and never auto-resend.
Retries use the same ID. A crash after reservation may remain pending/unknown;
inspect its status rather than submitting another ID. The control table permits
10 read/10 write units per second: a three-item transactional reservation needs
at least six write units. Existing energy-table caps are unchanged.

SES configuration-set events go through a restricted, customer-key-encrypted SNS
topic to a separate Lambda that cannot send mail or read records. It accepts
only the exact topic/configuration set and applies monotonic status precedence:
accepted → delayed → delivered → rejected/failed → bounced → complaint.
Duplicate/older events do not overwrite a later outcome. “Delivered” means the
recipient server accepted the message, not guaranteed inbox placement. Missing
events never become a fabricated delivery success. Sender/recipient verification
and end-to-end encrypted event publishing still need live acceptance testing.

## Costs and proposed future deployment

At ≤10,000 admin requests/month, ≤300 email tests, small audit records and minimal
logs, budget **$1–$3/month incremental**, excluding existing spend, tax and free
tiers. The customer-managed SNS encryption key starts at about $1/month; retained
rotated key material can raise that baseline later. SES base sending for 300
tests is about $0.03 on à-la-carte pricing or $0.048 on Essentials. Confirm the
account plan and Stockholm prices before approval. No dedicated IPs, paid SES
plan upgrades, NAT, VPC, RDS, provisioned concurrency or Cognito tier upgrade.
Existing $5 budget alerts remain alerts, not a spending cap.

Sources: [KMS pricing](https://aws.amazon.com/kms/pricing/),
[SES pricing](https://aws.amazon.com/ses/pricing/),
[SES encrypted SNS requirements](https://docs.aws.amazon.com/ses/latest/dg/configure-sns-notifications.html).

**No AWS change or email send is authorized by this document.** Future scope:

1. Read-only live inventory/drift check of the base deployment, provider limits,
   Cognito MFA configuration and SES plan/sandbox. Select the operator, sender
   and recipient allowlist. Stay in SES sandbox; no production-access request
   is needed for verified test recipients.
2. Separately review identity-root changes: one empty admin group and one
   dedicated client. Enroll and prefer TOTP in Settings before assigning membership outside the
   application; then sign in again to obtain fresh group claims.
3. Separately review bootstrap with `enable_admin=true`: four role boundaries,
   three scoped managed CI policies/four attachments, SES identities and
   configuration-set event destination, SNS topic/policy and one KMS key.
   Creating SES identities can send verification mail: approval must cover this.
   Existing identities must be inventoried/imported rather than blindly recreated.
4. App defaults remain `enable_admin=false`. After preparation, review repository
   variables `AWS_ENABLE_ADMIN=true`, `AWS_ADMIN_COGNITO_CLIENT_ID`,
   `AWS_ADMIN_EMAIL_SENDER`, and `AWS_ADMIN_EMAIL_RECIPIENTS` (JSON array).
   The sender/allowlist must match the operator-managed boundary configuration.
   CI gets no Cognito administration, SES sending or DynamoDB item permissions.
5. Expect 36 new app resources: control table; four roles/policies; three
   Lambdas/log groups; two integrations; eight routes/invoke grants; one event
   invoke grant/subscription; one CloudFront Function. Existing CloudFront
   receives its scoped association; both existing Lambda ZIP hashes update.
   No energy-table changes, deletions or replacements are intended. Only a real
   saved plan against inspected state can establish the final deployment scope.
6. Preserve the current manual-dispatch, OIDC, account/ID, artifact/hash,
   fresh-run and saved-plan guards. No workflow protection settings are changed.
   After separately approved deployment, test anonymous/non-admin denial, removed
   group membership, disabled MFA, token refresh, TOTP step-up, two-admin record
   isolation/pagination, verified-recipient rejection and one approved real send
   with delivery events. Production API throttling remains 1 request/sec, burst 2.

## Offline validation

Run the existing Python and frontend test suites, lint and AWS-mode build, then
`scripts/aws/build_artifact.py` and `scripts/aws/verify_artifact.py`.
`python3 scripts/aws/validate_offline.py` copies only Terraform source/locks,
modules, tests and the ZIP to temporary directories, then runs backend-disabled
init, validation and provider-mocked tests for all three roots. It never copies
live state, `.tfvars`, plans or backend metadata. CI also tests enabled/disabled
admin configurations and IAM boundaries. Local artifacts contain uncommitted
source and must not be deployed; any future release must rebuild reviewed code.


## Solo-owner CI deployment (merged; Admin activation pending)

The owner-only process is documented in [SOLO_DEPLOYMENT.md](../../.github/SOLO_DEPLOYMENT.md).
Plan and Apply are separate manual dispatches; Apply requires the reviewed run,
commit, checksum and confirmation phrase. Independent review is no longer used.
Cognito identity provisioning remains ON HOLD in its separate Terraform root.
