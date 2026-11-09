# Contact CI role ownership and remaining deployment trust

Local change only, 2026-11-09. No AWS resources, state, identities or live policies
were modified. Keep Contact CI, Admin activation and all real email sending off;
Karl remains ON HOLD. Existing runtime boundaries are unchanged.

## Minimal fix and dependency order

Remove the `create` managed-policy document and attachment from the Contact CI
module. `guard` explicitly denies `iam:CreateRole` for all resources, in addition
to the existing boundary replacement/removal and trust-policy modification denies.
Scoped PutRolePolicy and Lambda-only PassRole remain unchanged. Other secrets,
records, queue contents, SES/SNS sends, runtime invocation and KMS denies remain.

Before `enable_contact_ci=true`, bootstrap data lookups require all five roles:
`/energy-demo-aws/contact-{api,relay,worker,admin,events}` in account 628582070745.
Every role must use its matching
`/energy-demo-bootstrap/contact-{kind}-boundary`, exact account/path/ARN and the
strict policy produced by the existing application role resource: Version
2012-10-17, one Allow sts:AssumeRole statement, Service lambda.amazonaws.com only.
Extra principals, statements, actions, missing roles or mismatched boundaries
must fail closed. Lookups are metadata only and inactive while CI is disabled.
Managed CI policies depend on successful role metadata postconditions, so
attachments cannot be granted first. These checks do not create or repair roles.

The existing application root continues managing `aws_iam_role.contact` and its
runtime policies. An operator must provision it using a separately approved,
normally locked full application plan/Apply with CI disabled, then independently
review its resulting roles before any CI grant. The existing pipeline's plan
guard now rejects role creation. Existing roles can be refreshed and their scoped
policies/code updated; CI cannot repair missing roles or change their trust or
boundaries. Do not add a second Terraform role owner or migrate state.

Because the draft CI policies have no live attachments, removing the unused create
policy requires no live cleanup now. Any future plan proposing unexpected policy
or role deletion must stop for review; this local change authorizes no Apply.

## Residual risk ? deployment authority still accesses runtime data indirectly

This closes the initial-trust/attacker-assumption path. It does not make a
compromised deployment principal unable to access data through modified Lambda
code. UpdateFunctionCode/UpdateFunctionConfiguration remain allowed for exact
Contact functions, and PassRole remains scoped to the five roles and Lambda.
A malicious deployer could replace an existing API/events function's code, or
select another permitted Contact role, and act through its bounded permissions.
Caller-side secret/data/InvokeFunction denies do not transfer to runtime roles;
public API or service triggers can execute deployed code. Plan checks and
application auth are not an IAM sandbox against arbitrary direct deployment calls.

Treat deploy credentials as trusted production-data authority. Preserve immutable
repository-ID OIDC subjects, main/manual/owner and protected environment gates,
reviewed source/artifact/plan hashes and code review. Stronger isolation would
need a separate reviewed design (for example independently enforced signed-code
provenance or reduced deployment capabilities), not claims that this minimal fix
eliminates all compromised-CI data risk. Runtime boundaries still cap IAM actions
and the worker boundary's explicit SES deny still prevents real sending.

## Regression evidence to retain

Offline IAM evaluation must reject CreateRole even with the correct boundary or
an accidental Allow-all policy; reject trust/boundary edits, unrelated role
policy changes and non-Lambda/unrelated PassRole. Keep scoped PutRolePolicy and
Lambda update positives to make residual authority explicit. Mock Terraform
checks must reject attacker trust, wrong path/boundary, require all five exact
roles, keep CI off by default and preserve OIDC/no-send restrictions. Missing-role
lookups fail in the provider; mocks cannot establish live existence. Security
tests are offline policy evaluation, not an AWS IAM simulation or exploit.

No live boundary changes are necessary. Next approval is review of this local
patch and its tests; publishing, provisioning roles, CI grants and deployments
remain separate approval gates. Never reapply the consumed five-boundary plan.
