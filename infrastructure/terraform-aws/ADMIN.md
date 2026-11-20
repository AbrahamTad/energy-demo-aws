# Admin dashboard: coding complete, deployment pending

## Release baseline

Admin source was merged in PR #3; Contact/Turnstile followed in PR #4. The
solo-owner Plan/Apply safeguards are also merged. Source availability and the
completed IAM boundary preparation do not establish deployment readiness.
No AWS operation or activation is authorized by this document. Use current
identity, state ownership and drift evidence before any separately approved plan;
never reuse a completed plan or an approval for a different operation.
Any release must rebuild reviewed code and follow the saved-plan/artifact guards.

## Read-only readiness checkpoint: 13 November 2026

This inventory concerns account `628582070745`, region `eu-north-1`. It is a
dated observation, not an ongoing drift check or permission to deploy. No secret
values, user records, Contact messages or group membership were inspected.

| Dependency | Observed state | Remaining gate |
| --- | --- | --- |
| Bootstrap IAM | Two Admin boundaries and all five Contact boundaries exist, with no consumers. The approved boundary-only Apply completed; authoritative bootstrap state advanced to serial 34. | Preserve the original backend, state and backups. Do not reapply the completed plan. |
| Existing application | Public/personal Lambdas and tables are active. Tables are deletion protected; execution roles retain their separate boundaries. | A source merge or successful build does not deploy Admin/Contact or establish application-state freshness. |
| Admin/Contact application | Admin/Contact execution roles, Lambdas and their control/Contact tables are absent. | Resolve authoritative application-state ownership before a separately approved application plan. |
| Cognito | Existing Lite pool has optional MFA and software-token support. The `energy-demo-admin` group and `energy-demo-admin-step-up` client exist. | Presence alone does not verify client flows, token revocation, per-user TOTP or membership. Do not recreate these resources. Karl remains ON HOLD. |
| Contact secrets | Metadata lookup reports `energy-demo/contact` absent. Repository secret name `AWS_CONTACT_ORIGIN_TOKEN` is also absent. | Separately approve the runtime secret and independent origin credential. Never put values in logs, Git or frontend configuration. |
| Turnstile | Repository public site-key variable is configured. | Cloudflare Managed mode, approved hostname and secret/key pairing remain unverified; see the [Contact Turnstile guide](CONTACT-TURNSTILE.md). |
| Contact monitoring/delivery | Configured alarm topic exists with zero confirmed or pending subscriptions. Contact queues, event topic and SES configuration set are absent. | A topic ARN alone is insufficient: establish working approved alarm subscribers and delivery dependencies separately. |
| SES | Account is in sandbox with account sending enabled. Admin SES configuration set is absent. | Account status does not override IAM denies or authorize sending. Sender/recipient verification and event delivery remain unverified. |
| GitHub configuration | Admin/Contact activation variables and Admin email-test variable are unset, defaulting to false. Contact sending/customer-email variables are false. | Keep these gates off. CI expansion, deployment and activation require separate review/approval. |

No client-secret response or secret value was requested during this inventory.
Admin has no Secrets Manager prerequisite of its own; the secret blockers above
belong to Contact. Inventory absence is not permission to create a resource
without resolving its authoritative state ownership.

## No-send preparation and deployment order

Bootstrap and application roots have separate `enable_admin` inputs. Enabling
bootstrap preparation does not enable the application. Keep
`admin_email_testing_enabled=false` in both roots for no-send review.

1. **Preserve completed bootstrap work.** No-send preparation needs only
   `admin-admin-boundary` and `admin-private-boundary`, under
   `/energy-demo-bootstrap/`. Both explicitly deny SES sending. Preserve the
   five Contact boundaries. Bootstrap `enable_admin_ci=false` and
   `enable_contact_ci=false` keep CI expansion gated. Creating boundaries grants
   no application role or deployment capability by itself.
2. **Verify existing identity prerequisites.** Reconcile the existing group and
   dedicated client with the identity root's authoritative state. Separately
   verify client flows and token-revocation settings without exposing client
   secrets. Identity changes require explicit approval; Karl remains ON HOLD.
3. **Review a separately authorized application plan.** App defaults remain
   `enable_admin=false`. A proposed no-send Admin plan uses the existing dedicated
   client ID, with email testing false. The mock-tested shape has two execution
   roles (`admin`, `private`), one Admin Lambda/integration and six JWT routes,
   plus the control table, policies, logs and frontend routing resources. It
   omits email/events roles, Lambdas, integrations, subscriptions and email
   routes. Do not assume a fixed total resource count: inspect the saved plan's
   resource changes, artifact hashes and outputs before approval.
4. **Keep Contact prerequisites explicit.** Current Contact activation requires
   `enable_admin=true` in the application root. This dependency does not authorize
   either feature. Resolve the runtime secret, separate origin credential,
   Turnstile checks, working alarm subscribers and queue/event dependencies.
   Keep Contact sending/customer email and Admin email testing false for no-send
   review. Contact dependencies do not make Admin email testing mandatory.
5. **Choose the authorized deployment path.** The initial operator path does not
   require enabling CI. If CI is proposed later, review separate policies,
   attachments and exact ownership/scopes; do not enable CI flags or broaden
   permissions to work around a failed plan. Repository activation variables
   are separate gates, not prerequisites for local tests.
6. **Approve execution separately.** Reconfirm account, authoritative state,
   ownership, no competing writers and an exclusive no-write window. Bind
   approval to the exact saved plan/hash and scope. Preserve manual-dispatch,
   OIDC, artifact, freshness, replay and state-locking safeguards. Post-deployment
   tests that write proofs, audit data or records also need an approved scope.

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
- Read-only directory pages contain display name, email, account ID, account
  status, enabled state and email verification when available. Cognito requests
  project only the account ID and those optional attributes. Pages are capped
  at five. Opaque cursors bind to actor and route, expire after 15 minutes and
  cannot select an owner. Directory responses use private, no-store caching.
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

The behavior below applies only to separately enabled Admin email testing.
No-send mode retains explicit SES sending denies on its policies and boundaries.
The Admin status endpoint reports email disabled without querying SES when the
application email-test gate is off. With that gate on, it reports enabled only
for an explicit account `SendingEnabled=true`; SES inspection failures report
unavailable. This status does not verify recipients or authorize a send.

For email testing, the operator selects a fixed sender and 1–5 SES-verified recipient
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

**No AWS change or email send is authorized by this document.** After no-send
readiness is resolved, email testing is a separate proposal:

1. Select an approved fixed sender and 1–5 recipients. Inventory existing SES
   identities first; stay in sandbox. Creating an SES identity may send
   verification mail and needs explicit approval covering that email.
2. Separately review `admin_email_testing_enabled=true` in bootstrap and app
   plans. Bootstrap adds email/events boundaries, approved SES identities,
   configuration set/event destination, encrypted SNS topic/policy and KMS key.
   App adds email/events execution roles, functions, routes and event wiring.
   CI expansion remains independently gated by `enable_admin_ci`.
3. Review sender/recipient and email-test repository variables only as part of
   the approved deployment path. Boundary and runtime allowlists must match.
   CI receives no Cognito administration, SES sending or DynamoDB item access.
4. Separately authorize live identity tests, TOTP/proof operations, email
   reservations, real sends and delivery-event testing. Existing tests do not
   authorize changing membership, sending mail or reading user data.
   Production API throttling remains 1 request/sec, burst 2.

## Offline validation

Run the existing Python and frontend test suites, lint and AWS-mode build, then
`scripts/aws/build_artifact.py` and `scripts/aws/verify_artifact.py`.
`python3 scripts/aws/validate_offline.py` copies only Terraform source/locks,
modules, tests and the ZIP to temporary directories, then runs backend-disabled
init, validation and provider-mocked tests for all three roots. It never copies
live state, `.tfvars`, plans or backend metadata. CI also tests enabled/disabled
admin configurations and IAM boundaries. Any future release must rebuild reviewed
code; local artifacts are not release approval or evidence of deployed code.


## Solo-owner CI deployment (merged; Admin activation pending)

The owner-only process is documented in [SOLO_DEPLOYMENT.md](../../.github/SOLO_DEPLOYMENT.md).
Plan and Apply are separate manual dispatches; Apply requires the reviewed run,
commit, checksum and confirmation phrase. Independent review is no longer used.
Further identity changes require separate approval in the identity Terraform root;
Karl's membership remains ON HOLD.
