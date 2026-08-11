# Development log

## 2026-08-04

- Created the initial FastAPI application structure.
- Added SQLite database setup, client and intake records, API schemas, and routes.
- Added an automated health-check test and project setup documentation.
- Rebuilt the app into a scaffold, then added the first real feature: `POST /clients`.
- Simplified `POST /clients` to require `business_name` and `service_start_date`, set `onboarding` status, and reject duplicate business names.
- Added client listing, single-client lookup, onboarding form submission, onboarding form lookup, persistence coverage, and validation tests.
- Replaced deprecated FastAPI startup event wiring with lifespan startup.

## 2026-08-13

- Restored the complete FastAPI application wiring and verified the existing baseline.
- Added durable automatic onboarding runs queued by new intake submissions.
- Added automatic public Slack channel creation and read-only Vercel, GitHub, and website analytics discovery.
- Linked the Vercel owner to GitHub and scheduled the signed job runner every five minutes with repository-managed GitHub Actions so the Hobby deployment remains fully automatic.
- Added exact-match connection rules, owner-reviewed candidates, capped retries, and safe existing-client backfill.
- Added client-workspace progress controls and automatic approval-required task proposals after profile approval.
- Restored a 184-test green baseline after adding owner authentication, signed Slack actions, migrations, prompt artifacts, PDF report approval, GBP post approval, GitHub/Vercel website execution, browser-worker fallback, CI checks, and end-to-end acceptance coverage.
- Added approval-gated, client-bound, idempotent Slack delivery for client reports with durable retry records and production migration coverage.
- Added the owner-facing report approval/delivery controls, retry state, audit history, and end-to-end delivery acceptance coverage.
- Added executable core/full launch-readiness checks for database migrations, authentication, scheduler safety, provider configuration, and AI budgets.
- Added a read-only post-deployment smoke-test command and manual GitHub Actions workflow for health, stale-work, scheduler-failure, and readiness gates.
- Added a signed production-runtime Alembic endpoint for hosting integrations whose sensitive database URLs cannot be exported locally.
- Added a forward migration for legacy Google OAuth state columns and schema-contract readiness checks after production login exposed a stamped-but-incomplete table.
