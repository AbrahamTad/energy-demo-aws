# Contact Turnstile integration

Local source changes on `feature/contact-turnstile` reuse the existing contact
implementation. They create no new endpoint, infrastructure or Cloudflare widget.
Existing unrelated Admin/TOTP edits are preserved. Karl remains ON HOLD.

## Configuration for a separately authorized deployment

- Keep the existing Cloudflare widget in **Managed** mode with the approved
  hostname `d2gfvw1j7itrwq.cloudfront.net`. Managed mode is a widget setting,
  not a JavaScript render option. This change does not inspect or modify that account.
- Build with `VITE_TURNSTILE_SITE_KEY` set to that widget's **public** site key.
  Existing CI maps repository variable `CONTACT_TURNSTILE_SITE_KEY` to it.
  No private key belongs in a Vite variable. No actual widget key was requested,
  read or embedded during this integration. A build without it disables submission.
- Reuse `CONTACT_SECRET_ARN` and the existing Secrets Manager JSON configuration:
  `turnstile_secret` and `rate_hmac_key` (at least 32 characters). Provisioning or
  changing this secret requires separate authorization. Deployed handlers reject
  Cloudflare test secrets. Restart/replace the Lambda environment after rotation
  because the existing loader caches configuration per execution environment.
- Existing Terraform `contact_hostnames` must contain exactly the approved
  distribution hostname, mapping to `CONTACT_HOSTNAMES` as a JSON array.
  Expected action is fixed to `contact` in the widget and Lambda.
- Reuse existing CSP allowances for `https://challenges.cloudflare.com`, public
  `POST /api/contact`, CloudFront origin checks, API throttles and contact IAM.
  The Lambda requires outbound HTTPS to Cloudflare's Siteverify endpoint.
- Preserve all activation and no-send gates. In particular the current Terraform
  requires `enable_admin` for contact activation. This integration does not enable
  Admin or bypass that gate. A deployment needs a separate review/authorization
  resolving that dependency; local testing does not require Admin activation.

## Request and failure behavior

The browser renders the existing widget explicitly, obtains a challenge token,
and posts it as `botToken` alongside the existing contact fields. The widget's
automatic response field is disabled so strict API shape validation succeeds.
Every submission consumes the browser token and resets the widget afterward;
retries retain the inquiry ID and require another challenge token. Expiry, challenge
timeouts/errors and script-load errors disable submission and offer a retry. A
submit-time age check rejects tokens at four minutes even if an expiry callback
was delayed by the browser. Existing responsive form styling is retained.

Every backend submission, including an idempotent retry, calls Siteverify before
inquiry lookup/write. Only boolean `success: true`, the exact approved hostname
and action `contact` pass. Cloudflare enforces expiry and single-use semantics;
`timeout-or-duplicate` is rejected. There is no local bypass or acceptance cache.
Network errors, timeout (five seconds), bad responses and missing configuration
fail closed. Responses are sanitized; requests, tokens and inquiry fields are not
logged. The contact endpoint saves an inquiry/outbox only; existing separately
guarded workers remain responsible for any future authorized email sends.

## Local verification

`tests/aws/test_contact_turnstile.py` mocks all HTTP and AWS access and uses
Cloudflare's published test credential only inside the mocked Siteverify contract.
It covers success, missing/invalid tokens, expiry/replay responses, wrong hostname
or action, strict success typing, timeout/HTTP/malformed response failures, bad
hostname configuration, missing secret and rejection of test secrets by the real
configuration loader. It asserts no AWS client access on the submission paths.
No real Cloudflare verification, SES email or SNS notification is performed.

Frontend tests cover the public key/render contract, exact request fields,
age/expiry/timeout/error invalidation, script retry, cleanup, reset, pending-submit
locking and retries retaining the inquiry ID. Production build includes TypeScript
checks. Full local results and private log paths are recorded in
`.local/turnstile-checkpoint.md` (ignored by Git).

References: [Cloudflare server validation](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/),
[widget configuration](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/widget-configurations/),
[official test credentials](https://developers.cloudflare.com/turnstile/troubleshooting/testing/).
