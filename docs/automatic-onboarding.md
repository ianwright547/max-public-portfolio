# Automatic onboarding

Automatic onboarding turns one saved client intake into a durable, reviewable
handoff to fulfillment.

```text
Intake saved
  → OpenAI profile proposal
  → public Slack channel
  → Vercel project discovery
  → GitHub repository discovery
  → website analytics tracker discovery
  → connection review when needed
  → profile approval
  → approval-required task proposals
```

## One-time agency setup

Configure the OpenAI, Slack, Vercel, and GitHub values shown in `.env.example`.
The website analytics adapter uses the existing aggregate-only dashboard data
source. Provider credentials remain environment secrets and are never copied
into client records, prompts, reports, or Slack.

Production uses `.github/workflows/run-due-jobs.yml` to call
`POST /jobs/run-due` every five minutes. Configure the repository secrets
`MAX_JOB_RUNNER_URL` and `MAX_JOB_RUNNER_SECRET`; the latter must match the
deployment's `JOB_RUNNER_SECRET`. The endpoint also supports Vercel Cron's
signed GET format if the project is upgraded from Hobby later. Repeated
scheduler calls are safe.

## Matching rules

- Vercel auto-connects only when one visible project has an exact normalized
  production hostname matching the intake domain.
- GitHub auto-connects only when the verified Vercel project exposes one exact
  repository URL available to the installed GitHub App.
- Website analytics auto-connects only when one tracker identifier exactly
  matches the normalized client domain key.
- Multiple, partial, name-only, conflicting, or cross-client matches require
  owner review or stop processing.
- Approving a candidate re-reads the provider before saving it and supersedes
  other candidates for that provider.

## Failure and retry behavior

Runs and jobs are persisted before any provider call. Temporary network,
rate-limit, or provider failures retry no more than three times. Missing or
invalid credentials, budget exhaustion, mismatches, rejected matches, and
exhausted retries block the run and create an owner notification. Retrying a
blocked run reuses completed steps and existing verified mappings.

## Owner controls

The client workspace shows the status of interpretation, Slack, Vercel, GitHub,
analytics, profile approval, and task generation. The API provides the same
state:

- `POST /clients/{client_id}/onboarding-automation`
- `GET /clients/{client_id}/onboarding-automation`
- `GET /clients/{client_id}/connection-candidates`
- `POST /connection-candidates/{candidate_id}/decision`
- `POST /onboarding-automation/backfill`

Backfill creates runs only for clients with saved intakes. It fills missing
connections and never replaces a verified mapping.
