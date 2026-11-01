# GitHub-only compatibility probe - preparation only

No publication or dispatch is approved. Cognito, SES and Admin release remain ON
HOLD. This workflow/script/test/guide are new local files; pre-existing work must
stay separate. They need a separately approved isolated commit/PR before this
main-only manual workflow can ever run. Do not dispatch Plan or Apply.

## Boundaries and required approval

`github-compatibility.yml` has only workflow_dispatch, a separate concurrency group,
no aws-production job environment, no OIDC id-token permission, no AWS credentials,
no Terraform invocation and no state access. Its script rejects ambient AWS/OIDC
capability before API calls. Both jobs verify the exact owner, repo/run/workflow
identity and main commit. The verification job has contents/actions read and
deployments write; the fixture job has read permissions only (artifact upload
uses the Actions runtime mechanism). No static credentials are added.

A future dispatch must explicitly supply:
`RUN GITHUB-ONLY COMPATIBILITY TEST`.
Invalid/missing confirmation aborts before any script API call or artifact write.
Do not authorize dispatch until external integrations/webhooks are confirmed to
ignore the test environment/task prefixes: creating Deployment metadata can emit
deployment events. A namespace does not itself stop external listeners.

## Future runtime checks

1. Owner/context and read-only production environment settings APIs, using each
   job's workflow-issued GITHUB_TOKEN. Missing permissions/API data fail closed.
2. Upload a small non-sensitive JSON fixture; in a second job list exact run-scoped
   artifact metadata, check provenance/expiry/digest, download and verify ZIP bytes,
   redirect credential stripping and safe extraction using the production helper.
3. Run pure production confirmation/input/rerun validators against invalid values.
   Inject API read/write errors locally to establish exception propagation; these
   are simulated failures, not real GitHub outages or deliberate unauthorized calls.
4. Write and read one test-only normal consumption record. Re-run the consumer
   against it and require replay rejection before the writer is reached.
5. Write a second record and simulate interruption immediately after GitHub accepts
   it, before acknowledgement. A new consumer read must reject that record too.
   Replay probes install a write tripwire: even stale reads cannot create extras.
6. Require exactly one record per scenario and report their IDs and artifact ID.
   There is no automatic retry, rerun, cleanup or path into production ledgers.

## Exact maximum intended GitHub writes per approved first-attempt run

- One manual Actions run, two jobs, ordinary logs and a job summary.
- One artifact: `github-compat-fixture-<run-id>-1`, containing only `fixture.json`
  with run ID, commit and a generated 32-hex nonce. Retention: **one day**.
- Two Deployment metadata records, never real AWS deployments. Both have
  `auto_merge=false`, `production_environment=false`, `transient_environment=true`.
  Their environment label is `energy-demo-ci-compatibility-test-<run-id>`;
  reserve this test-only environment namespace, including any environment metadata
  GitHub may materialize for it. No environment settings API writes are coded.
- Tasks are `energy-demo-compat-<run-id>-<nonce>-normal` and
  `energy-demo-compat-<run-id>-<nonce>-interrupted`. Payload uses only test run IDs
  and the fixture checksum. No production consumption record is read or changed.
- No deployment statuses, issues, PR comments, repository settings, production
  environment settings, AWS resources, emails or Terraform state are written.

Interrupted/failed runs can leave zero, one or two test records; fail closed and
inspect that run. The artifact may already exist. Never blindly rerun; first review
remaining records, then approve a new dispatch with a new run ID and nonce.

## Retention and cleanup review BEFORE dispatch approval

Artifact expires after one day. Actions logs use the existing repository retention
(previously observed 90 days); summaries and run metadata remain GitHub-managed.
Deployment metadata has no artifact-style TTL. Keep the two records until results
are reviewed. This implementation performs **no automatic deletion**.

After separate explicit cleanup approval, list the exact test environment/tasks,
verify recorded IDs and payloads, then remove only those test records and any
associated test environment metadata through a reviewed manual cleanup. GitHub
may require records to be inactive before deletion, which would create additional
status metadata/events and needs its own approval. Never target aws-production,
energy-demo-plan-consumption or any task starting energy-demo-plan-.

## What this cannot prove

No AWS role assumption, live IAM trust, Terraform/provider/state permissions,
real Plan provenance/expiry across separate workflows, SES sending or Admin API
behavior is tested. Test records share production's API/helper shape but not its
namespace. Interruption is a deterministic simulation, not actual runner death,
network ambiguity after server acceptance, or proof of GitHub consistency.
Shared-concurrency behavior is statically checked; this single run does not prove
multi-run scheduling. Missing/invalid approvals use pure validators, not additional
negative workflow dispatches. GitHub deployments write is repository-wide, so
namespace fencing relies on trusted code; owner compromise/workflow edits remain
privileged boundaries. Read-only checks cannot prove these runtime behaviors.
