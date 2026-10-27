# Cognito identity: separate, approval-only stage

This root is independent of the existing application and IAM bootstrap roots.
It proposes **two resources** in `eu-north-1`: one Cognito User Pool and one
public browser app client. The user reports this root has now been deployed:
pool `eu-north-1_6m60ePWS0`, public client `796jkcsk4dc5scoc77r8ejies7`. Read-only
AWS inspection confirmed the client belongs to this pool, has no client secret,
and supports SRP/refresh authentication. The steps below document initial
provisioning; do not repeat that operation for a frontend release.
GitHub's plan/deploy roles receive **no Cognito permissions** and their state-key
permissions do not include this root. CI only validates and runs provider mocks.

## Cost review (27 October 2026)

The pool explicitly selects **Lite**, rather than the default Essentials tier.
For direct sign-in, AWS currently includes 10,000 monthly active users per
account/organization across Lite/Essentials pools. Under that shared allowance,
estimate $0/month in incremental authentication MAU charges; Lite's first paid
tier is $0.0055 per MAU (for example, 100 additional billable MAUs ≈ $0.55/month).
Existing CloudFront, S3, API Gateway and Lambda request/storage charges continue.
The existing $5 account budget alerts are preserved and are not a spending cap.

Email verification/recovery uses Cognito's default AWS-managed sender, which has
a low daily sending quota. No customer SES identity, SMS, custom domain, identity
pool, database, WAF, NAT gateway, or advanced-security add-on is created. AWS lists
messaging separately: verify the actual account allowance and regional charges
before approving. For production email volume, separately review SES identity,
verified-domain configuration, sandbox exit, quotas and per-message costs.
Use this configuration for a small learning workload until that review.

Sources: [Cognito pricing](https://aws.amazon.com/cognito/pricing/),
[default email delivery and quotas](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-email.html).

## Security choices

- Email sign-in, required email confirmation and verified-email-only recovery.
- Minimum 12-character mixed-case/number/symbol passwords, enforced by Cognito.
- Optional authenticator-app TOTP MFA; no SMS charges. The frontend supports
  enrollment and TOTP challenges. Users must retain their authenticator; lost
  factors require a separately authorized Cognito administrator recovery process.
- Public SPA client with no secret; only SRP and refresh-token authentication.
  No implicit flow, password-grant flow, admin-password flow, or AWS credentials.
- 15-minute access/ID tokens, one-day refresh lifetime, token revocation enabled,
  and user-existence error suppression. Amplify owns SRP and session refresh.
- Access/ID/refresh tokens use Amplify's `sharedInMemoryStorage`; no application
  auth state goes into localStorage, sessionStorage, or cookies. Amplify may use
  its own short-lived sessionStorage entries for a pending multi-step challenge;
  these are not a persisted signed-in session. Reload requires sign-in again.
- The pool has AWS deletion protection; pool/client have `prevent_destroy`.
  Schema changes and account/client replacement require separate review.

## Exact next steps, only after approval

Run from the repository root using Terraform 1.16.5 and an approved administrator
SSO/MFA profile. Replace the explicit placeholder; no static keys or root login.
Do **not** run these commands until infrastructure/cost/state access is approved.

```bash
export AWS_PROFILE='<approved-administrator-profile>'
export AWS_REGION=eu-north-1
export AWS_EC2_METADATA_DISABLED=true
export TF_VAR_account_id='<approved-12-digit-account-id>'
test "$(aws sts get-caller-identity --query Account --output text)" = "$TF_VAR_account_id"

terraform -chdir=infrastructure/terraform-aws-auth init -input=false -lockfile=readonly \
  -backend-config="bucket=energy-demo-tfstate-${TF_VAR_account_id}-eu-north-1" \
  -backend-config='key=energy-demo/auth/terraform.tfstate' \
  -backend-config='region=eu-north-1' \
  -backend-config='encrypt=true' \
  -backend-config='use_lockfile=true' \
  -backend-config="allowed_account_ids=[\"${TF_VAR_account_id}\"]"
terraform -chdir=infrastructure/terraform-aws-auth plan -input=false -out=auth-reviewed.tfplan
terraform -chdir=infrastructure/terraform-aws-auth show -no-color auth-reviewed.tfplan
```

Review that the plan adds **only the pool and SPA client** and touches none of
the current stack. With explicit approval of that exact saved plan:

```bash
terraform -chdir=infrastructure/terraform-aws-auth apply auth-reviewed.tfplan
terraform -chdir=infrastructure/terraform-aws-auth output -raw user_pool_id
terraform -chdir=infrastructure/terraform-aws-auth output -raw spa_client_id
```

Set repository **variables**, not secrets, `COGNITO_USER_POOL_ID` and
`COGNITO_CLIENT_ID` to those outputs. They are intentionally public browser IDs.
Do not create or supply a client secret. The Build AWS workflow passes these
optional overrides as `VITE_COGNITO_USER_POOL_ID` and `VITE_COGNITO_CLIENT_ID`.
AWS builds default to the deployed public pair in `frontend/src/auth/config.ts`
when both variables are unset. If overrides exist, both must match the deployed
pair; partial, malformed or conflicting configuration fails the AWS build.
The browser bundle includes the IDs and uses the regional Cognito HTTPS API.
No pipeline needs access to this root's state or any Cognito administrative APIs.

For a local connection to the real approved pool, copy `frontend/.env.example`
to `frontend/.env.local`, fill the same two public IDs, and run `npm run dev`.
No Cognito hosted domain/callback URL or CORS change is needed for direct SRP.

After separately approved source review/merge, wait for Build AWS to pass.
Start a **new** `Deploy AWS (manual)` dispatch from `main` and review the saved
application plan through the existing gates. Do not rerun an old dispatch, bypass
preflight, expand deployment IAM, or apply an unreviewed plan. Confirm the prior
log-ARN bootstrap fix has been applied by an administrator if AWS still has the
old planning policy. Cognito never needs a grant to the GitHub deployment roles.

After approved deployment, verify `/`, `/#/energy`, direct `/#/profile` navigation,
and unchanged JSON/errors at `/api/energy`. With a real email account you control:
register → receive/confirm email code → log in → edit profile → enable TOTP →
sign out → log in with TOTP → reset password → log in with the new password.
Check reload signs out, expired sessions cannot open protected pages, and no
JWTs/passwords appear in localStorage, logs, URLs, or cached static files.
These AWS-connected operations have **not** been run during local preparation.

## Future database boundary

The frontend `UserProfile` maps Cognito `sub`, verified email and display name.
`sub` (together with the pool issuer when multiple pools exist) is the stable
database ownership key; email is mutable and must not be a primary key.
No database resource or fake profile repository is introduced. Name edits are
real Cognito attribute updates. The existing `/api/energy` is still public shared
snapshot data and is never presented as personal user readings.

Before introducing private profile/energy endpoints, add API Gateway JWT
authorization for this pool's issuer and SPA audience. Verify `token_use=access`,
expiry and audience/client binding, derive ownership from verified `sub` on the
server, and test cross-user isolation. A React route guard is a UI control,
not a backend authorization boundary. Do not retrofit public `/api/energy` into
a private API or trust client-submitted account IDs without a separate review.
