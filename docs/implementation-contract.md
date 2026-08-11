# Max implementation contract

This document is the executable contract for the current MVP. It supersedes
the unfinished questionnaire sections in the original product-definition
working document.

## Relationships and history

- A client may have many intakes, tasks, metric periods, reports, findings,
  executions, verifications, notifications, and audit events.
- An intake belongs to exactly one client and is immutable after submission.
- Multiple intakes may produce profile versions for one client; only one
  approved official profile is active at a time.
- A task may depend on many tasks. A dependency may be shared by many tasks.
- Cancelling or rejecting a dependency blocks dependent work and preserves the
  dependency history.
- No historical intake, metric, task, execution, report, finding,
  verification, or audit record is permanently deleted.

## Canonical states

```text
Client: new → onboarding → awaiting_profile_approval → ready_for_fulfillment
        → fulfillment_in_progress → active | paused | cancelled
Intake: received → processing → needs_review | awaiting_approval | approved | rejected
Task: proposed → approved → ready → running → completed → verified
      proposed → rejected; running → blocked | failed
Report: draft → approved
GBP post: draft → approved → published | failed
Browser execution: running → completed | failed | blocked
```

Approval, execution, completion, and verification are separate facts. No
completed execution resolves a finding until an independent verification
passes.

## External-action rules

- API adapters are preferred for GitHub, Vercel, Search Console, and Google
  Business Profile.
- Browser work is delegated to the configured browser worker only when an API
  cannot perform the task.
- Every external mutation requires an approved task and verified client,
  account, resource, and scope.
- Operation keys make retries idempotent.
- Provider credentials are runtime-only and never enter prompts, reports,
  Slack, evidence, or logs.
- Provider mismatch, missing access, expired approval, unsupported action, and
  missing worker configuration stop the workflow with an actionable error.

## Definition of done

The MVP is accepted when the end-to-end test passes, CI passes on Python 3.9,
PostgreSQL migrations apply successfully, a production deployment can expose
the health endpoints, and a configured owner can complete the workflow from
intake through approved report delivery without database repair.
