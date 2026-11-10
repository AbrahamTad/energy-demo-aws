# Contact CI role ownership and remaining deployment trust

Local change only, 2026-11-09. No AWS resources, state, identities or live policies
were modified. Keep Contact CI, Admin activation and all real email sending off;
Karl remains ON HOLD. Existing runtime boundaries are unchanged.

## Minimal fix and dependency order

Remove the `create` managed-policy document and attachment from the Contact CI
module. `guard` explicitly denies `iam:CreateRole` for all resources, in addition
to the existing boundary replacement/removal and trust-policy modification denies.
Contact CI no longer grants PutRolePolicy, PassRole, CreateFunction or
UpdateFunctionConfiguration. Exact Contact role/function denies enforce operator
ownership even if another policy accidentally grants these actions. These new
denies do not block unrelated EnergyDemo roles/functions. Existing secrets,
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
guard rejects role/function creation and Contact runtime policy writes. Existing
roles and policies can be refreshed but runtime policy changes require an operator
plan. CI can update existing Contact code/tags only; it cannot pass roles, reassign
a function role, change environment/runtime/handler/layers or repair missing roles.
Do not add a second Terraform role owner or migrate state.

Because the draft CI policies have no live attachments, removing the unused create
policy requires no live cleanup now. Any future plan proposing unexpected policy
or role deletion must stop for review; this local change authorizes no Apply.

## Residual risk ? deployment authority still accesses runtime data indirectly

This closes the initial-trust/attacker-assumption path. It does not make a
compromised deployment principal unable to access data through modified Lambda
code. UpdateFunctionCode remains allowed for exact Contact functions.
UpdateFunctionConfiguration and cross-role PassRole are now explicitly denied.
A malicious deployer could still replace an existing API/events function's code
and act through that function's existing bounded permissions.
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
policy changes and every Contact PassRole attempt, including Lambda and cross-role
combinations. Negative tests include accidental Allow-all grants, sensitive Lambda
configuration, concurrency, invocation/destination settings and mapping updates.
Keep exact code-update positives and direct-data denies to make residual authority
explicit. Mock Terraform
checks must reject attacker trust, wrong path/boundary, require all five exact
roles, keep CI off by default and preserve OIDC/no-send restrictions. Missing-role
lookups fail in the provider; mocks cannot establish live existence. Security
tests are offline policy evaluation, not an AWS IAM simulation or exploit.

No live boundary changes are necessary. Next approval is review of this local
patch and its tests; publishing, provisioning roles, CI grants and deployments
remain separate approval gates. Never reapply the consumed five-boundary plan.

## Runtime configuration hardening follow-up (local, unpublished)

The existing application state remains the sole owner of Contact roles, policies,
functions and mappings. Operator ownership means using that same Terraform root,
backend and reviewed normal plan; never duplicate manually managed IAM roles.
Initial provisioning and later IAM/configuration changes require separately
approved operator deployment with Contact CI disabled. Routine CI can deploy a
code-only change to already-provisioned functions only if all other configuration
is unchanged. If a plan changes runtime IAM/configuration, stop and use the
operator review path; do not broaden CI rights to make it pass.

Sensitive execution settings are also operator-owned: concurrency, invocation
permissions, asynchronous failure destinations and event-source mappings. CI has
explicit scoped denies for their writes. This preserves zero worker concurrency,
disabled queue consumption and the existing SES boundary denies. Role tags and
Lambda tags retain their existing exact-resource permissions; they do not grant
runtime IAM policy/configuration authority. The plan guard is deliberately
conservative and rejects mapping changes, including combined tag/config plans.

A code-only Lambda plan may change code references/hash, derived version/signing
metadata and tags. Any changed/unknown runtime setting (role, environment, handler,
runtime, layers, networking, concurrency, signing configuration, etc.) is rejected.
The guard also rejects runtime IAM writes even when their permissions would fit
under a boundary. AWS denies remain necessary because a plan guard is not an IAM
sandbox against direct API requests. Unknown new configuration attributes fail
closed; review provider changes rather than silently adding broad exceptions.

This patch does not guarantee confidentiality against a compromised code deployer:
malicious code can call DynamoDB/Secrets Manager using the existing runtime role
and return data through API responses or outbound traffic. No role-policy edit,
PassRole or direct InvokeFunction permission is needed when existing triggers
execute that code. Treat code deployment as trusted production-data authority;
independently enforced code provenance/approval would need its own design. No
source-code test can prove arbitrary future deployment code harmless.

Keep all activation/sending/CI flags off and Karl ON HOLD. This local patch changes
neither live boundaries nor state and authorizes no commit, push or deployment.
