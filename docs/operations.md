# Production operations

## Health

- `/health` verifies the application can reach its database.
- `/health/details` exposes safe scheduler and onboarding signals without
  client data, credentials, prompts, or provider tokens. Its `alerts` array
  contains stable codes, severity, affected record IDs, and remediation text
  suitable for an external monitor.
- `/health/readiness?profile=core|full` verifies migration, security, and
  provider launch requirements without exposing configured values.
- A degraded status means at least one onboarding run has been stale for more
  than 30 minutes.

## Deployment smoke test

After deploying and migrating, run:

```bash
python scripts/smoke_test_deployment.py https://max.example.com --profile full
```

The command performs only three GET requests. It requires healthy database and
scheduler signals, zero stale onboarding runs, zero failed scheduled jobs, and
zero readiness blockers. HTTP is rejected except for localhost when explicitly
enabled with `--allow-http-localhost`.

The `Max production smoke test` GitHub Actions workflow exposes the same check
as a manual workflow with deployment URL and readiness-profile inputs.

## Continuous verification

Configure monitoring to page on critical/high entries in
`/health/details.alerts`, and preserve its `request_id` for incident
correlation. Alert payloads intentionally exclude raw provider errors.

GitHub Actions runs compilation and the complete pytest suite on every push and
pull request. Deployment should be gated on that workflow and on
`alembic upgrade head` succeeding against the production PostgreSQL database.
When the hosting integration prevents credentials from being exported, deploy
and call signed `POST /jobs/migrate` with `X-Max-Job-Secret`; the endpoint is
idempotent and returns only the resulting migration revision.

## Recovery

Failed scheduled jobs remain recorded with a safe error category. Re-running
the signed job endpoint is idempotent. Onboarding runs and executions retain
their state and should be resumed through the existing workflow controls after
the underlying provider or access problem is corrected.
