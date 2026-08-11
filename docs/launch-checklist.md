# Production launch checklist

## Before deployment

- [ ] Run `python scripts/check_production_config.py` for the authenticated core
  deployment, then run it with `--profile full` before enabling provider-backed
  fulfillment.
- [ ] Run `python scripts/check_launch_readiness.py --profile full --live-slack
  --live-providers --live-search-console` against the deployment environment
  and resolve every blocked check; the live flags verify Slack owners, GitHub,
  Vercel, GBP, and active client Search Console properties.
- [ ] Treat malformed OAuth callbacks, owner email lists, GitHub PEM keys, and
  browser-worker URLs as release blockers; the readiness gate validates these
  shapes without printing their values.
- [ ] Set a persistent PostgreSQL `MAX_DATABASE_URL`.
- [ ] Run `.venv/bin/alembic upgrade head` against the deployment database.
- [ ] Run `python scripts/backup_database.py --output ...` against the
  deployment database, store the verified artifact in encrypted backup storage,
  and complete one isolated restore rehearsal. See
  `docs/operations-backups.md`.
- [ ] Schedule `python scripts/check_backup_age.py` and alert on any non-zero
  exit; a stale or unverifiable latest backup blocks release and rollback.
- [ ] Run `python scripts/restore_database_rehearsal.py` with an explicitly
  isolated PostgreSQL target and `--confirm-isolated-target`; verify the restored
  database accepts a read-only query before first paid-client traffic.
- [ ] Configure the GitHub Actions `MAX_JOB_RUNNER_URL` and
  `MAX_JOB_RUNNER_SECRET` repository secrets, then manually run the scheduled
  workflow once.
- [ ] Configure `AUTH_SECRET`, `MAX_ALLOWED_GOOGLE_EMAILS`, and Google OIDC
  callback values.
- [ ] Configure Slack bot, signing secret, workspace ID, and owner IDs.
- [ ] Populate `/agency/members` with each active team member, assign the
  least-privilege role, and map Slack user IDs; retain at least one active
  owner. Mapped client channels remain the explicit client-scope clearance
  boundary.
- [ ] Run `python scripts/check_slack_provider.py` in the deployment environment;
  it must complete the read-only `auth.test` probe and confirm the bot belongs
  to the configured workspace and every configured owner ID resolves to an
  active human Slack member before enabling Slack fulfillment.
- [ ] Set `MAX_PUBLIC_BASE_URL` to the HTTPS deployment origin so approved
  report links delivered to Slack are absolute.
- [ ] Configure `JOB_RUNNER_SECRET` and `CRON_SECRET`.
- [ ] Verify `/jobs/run-due` fails closed with `401` when production scheduler
  secrets are absent; the unauthenticated no-secret mode is local-development
  only.
- [ ] Configure OpenAI only after monthly and per-operation budgets are set.
- [ ] If paid-mode enforcement is enabled, configure the billing provider name
  and signed webhook secret, then verify active, past-due, and cancelled events.
- [ ] Verify subscription reads and manual entitlement changes require an
  authenticated owner session in the deployed environment; never expose
  provider customer/subscription identifiers to an unauthenticated caller.
- [ ] In paid mode, verify a missing/past-due subscription blocks new reports,
  in-depth audits, daily plans, direct website generation/previews, browser
  work, GBP posts, report delivery, and fulfillment while historical
  client/report reads remain available.
- [ ] Exercise the AI budget gate with a sandbox cost: verify actual cost takes
  precedence over estimate, 50%/80% warnings are visible, and over-budget
  requests stop without calling the provider.
- [ ] Configure GitHub App and verify the installation can access the intended
  repositories.
- [ ] Configure Vercel token/team/project access and verify project identity.
- [ ] Configure Google OAuth refresh token and verify Search Console/GBP scopes.
- [ ] Run `python scripts/check_provider_connections.py`; it must verify the
  configured GitHub repository, Vercel project, and GBP location with read-only
  provider calls before enabling external fulfillment.
- [ ] Run a read-only GBP inspection for a sandbox location and confirm the
  report records categories, hours, review aggregates, and any access blocker
  without storing review text.
- [ ] Configure `BROWSER_WORKER_URL` and `BROWSER_WORKER_TOKEN` if browser
  fallback is needed.
- [ ] Explicitly select `MAX_FULFILLMENT_MODE=codex_handoff` while Codex is the
  human handoff path, or `MAX_FULFILLMENT_MODE=github_vercel` only after direct
  external writes have been tested and approved.

### Per-client launch gate

Global deployment readiness does not prove that an individual client is ready.
Before activating recurring fulfillment, request
`GET /clients/{client_id}/launch-readiness` or open the client's dashboard
overview. Resolve every **required** check: active client, saved intake,
approved official profile, healthy Slack client boundary, onboarding state,
website access when website/SEO work was requested, billing entitlement when
paid-mode enforcement is enabled, and GitHub access when GitHub/Vercel writes
are selected. Search Console and GBP are recommended evidence sources; if they
are missing, reports must show the limitation instead of treating the data as
live. Use `POST /clients/{client_id}/provider-verification` (or **Run live
provider checks** in the client dashboard) to perform bounded read-only probes
against the exact saved Slack channel, website URL, GitHub repository, Search
Console property, and GBP location. Rerun the gate after remediation; the
result and provider codes are retained in the audit trail without raw provider
errors or credentials.

For a deployment smoke sweep, run
`python scripts/check_client_provider_health.py` after provider credentials are
loaded. Use `--client-id CLIENT_ID` for a single-client rehearsal. A non-zero
exit means at least one active client's saved provider failed its read-only
probe and recurring fulfillment should remain paused until the returned code
is resolved.

The manual **Max production smoke test** workflow can run the same sweep through
`GET /jobs/provider-health` using the scheduler secret. Keep the provider-health
input enabled for a paid deployment; the workflow fails if the secret is absent
or any active client returns a failed provider result.

## Verification gates

- [ ] `GET /health` returns `ok`.
- [ ] `GET /health/details` reports database `ok` and no stale runs.
- [ ] Configure monitoring for `/health/details.alerts`; page on critical/high
  alerts and preserve the returned request ID for incident correlation.
- [ ] `GET /health/details` reports zero failed or stale scheduled jobs after a
  controlled scheduler run; confirm a forced client-job failure creates one
  actionable notification and backs off the next attempt.
- [ ] `GET /health/readiness?profile=full` reports `ready` without exposing any
  configured values.
- [ ] Review `/dashboard/release-readiness` (or the CLI equivalent) and resolve
  scheduler stale/repeated-failure, archived-client job-safety, and persisted
  provider error checks before calling the release ready.
- [ ] Run `python scripts/smoke_test_deployment.py DEPLOYMENT_ORIGIN --profile
  full`, or manually run the `Max production smoke test` GitHub workflow.
- [ ] Confirm the deployment smoke test's API contract probe passes; it verifies
  the deployed build exposes report/PDF, daily-plan, task approval/browser
  approval, website-preview, and scheduler surfaces, not only `/health`.
- [ ] Confirm the deployment smoke test's authentication-boundary probe gets
  `401` from `/clients` without an owner session; a `200` is a release blocker.
- [ ] Owner login succeeds and a non-owner is rejected.
- [ ] A signed billing webhook remains callable without an owner cookie, while
  invalid signatures are rejected and replayed event payloads stay idempotent.
- [ ] Slack signed action succeeds once and is idempotent on replay.
- [ ] Reusing a Slack event/action key with a different signed payload is
  rejected, while the original payload remains idempotent.
- [ ] A sandbox client completes the end-to-end acceptance test.
- [ ] The sandbox completes the Codex lifecycle: approved task -> packet ->
  handoff -> structured result -> independent verification.
- [ ] A website change commits only allowed files and records a deployment ID.
- [ ] A sandbox website execution can be rolled back once; verify the revert
  commit is recorded and the task returns to blocked pending fresh verification.
- [ ] A generated website preview is inspectable before any commit or deployment,
  with file hashes and added/removed/changed path comparisons matching the
  reviewed draft.
- [ ] A GBP post remains blocked until approval and records its provider ID.
- [ ] A client report remains blocked until approval and downloads as PDF.
- [ ] Convert one report 30/60/90 recommendation into a proposed task, confirm
  the task retains the report evidence and success metric, and replay the same
  request to confirm no duplicate task is created.
- [ ] Archiving/removing a client disables every future scheduled job for that
  client while preserving job history, and new reports/tasks are rejected.
- [ ] An archived client cannot queue or resume onboarding automation, approve a
  pending profile, or create a corrected profile version.
- [ ] Internal reports show the evidence-based operational retention-risk summary;
  client reports include an approval-gated message draft with no internal risk
  language or unsupported outcome claims.
- [ ] A sandbox client has a persisted daily-plan configuration; verify simple and
  in-depth modes, focus selection, and optional scheduled report creation.
- [ ] A browser fallback job remains unverified until worker evidence is polled
  and independently reviewed; the task has a separate, scoped browser-control
  approval recorded before submission.
- [ ] CI passes compilation and all tests.

## Rollback and recovery

- [ ] Keep the last approved Vercel deployment ID and Git commit SHA.
- [ ] Disable `MAX_ENABLE_EXTERNAL_WRITES` if provider behavior is unsafe.
- [ ] Disable affected scheduled jobs while preserving their records.
- [ ] Correct provider access or worker state, then resume the persisted job.
- [ ] Never repair workflow state by deleting historical records.
