---
title: Task Execution
slug: task-execution
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - approved fulfillment tasks
  - Codex work
  - website work
  - SEO work
  - content work
  - simulated execution
  - external execution
owner: agency
review_required: true
---

# Task Execution

## Purpose

This SOP defines how Max executes an approved fulfillment task and records what happened.

Task execution must be controlled, client-specific, repeatable, and easy to verify. Approval authorizes the work, but completion is not the same as verification.

## Task lifecycle

```text
proposed
    ↓ approval
approved
    ↓ dependencies and access ready
ready
    ↓ execution starts
running
    ↓ result recorded
completed / failed / blocked
    ↓ human or rules-based verification
verified
```

Other terminal or administrative states include:

- `rejected`
- `cancelled`

## Approval enforcement

Only tasks in `approved` or `ready` may execute.

Max must refuse execution for:

- Proposed tasks
- Rejected tasks
- Cancelled tasks
- Tasks with unresolved required dependencies
- Tasks missing required access
- Tasks connected to the wrong client or external resource

Approval must record:

- Decision
- Decision maker
- Time
- Client
- Task
- Reason when provided

Once approved by the agency owner or authorized team member, the task may proceed without another publish confirmation unless a safety issue is discovered.

## Pre-execution checks

Before starting, Max must confirm:

- Correct client ID
- Correct task and plan
- Approved requested outcome
- Required access
- Dependencies resolved
- Correct GitHub repository when applicable
- Correct Vercel project when applicable
- Correct domain when applicable
- Risk level
- Estimated cost
- Execution mode
- Unique operation key

If a client, repository, project, domain, or external resource mismatch is possible, Max must stop immediately.

## Execution modes

### Simulator

The safe fulfillment simulator may deliberately produce:

- Successful outcome
- Failed outcome
- Blocked outcome

It records intended actions without changing a real client system.

### Codex or external executor

Codex or another authorized executor may work on approved GitHub-backed tasks through a generated work packet.

The work packet must contain the exact client, repository, branch, domain, Vercel project, allowed files, prohibited files, requested outcome, skills, tests, cost guidance, and publishing state.

No executor may use another client's files, credentials, domain, repository, or project.

## Idempotency and duplicate execution

Every execution receives a unique operation key.

Repeated requests with the same operation key must return or link to the existing execution instead of starting the action again.

Max must prevent duplicate active executions for the same task and operation.

Execution records remain visible even when the task is retried.

## Execution record

Every execution must record:

- Execution ID
- Operation key
- Task ID
- Client ID
- Executor type
- Intended actions
- Actual actions
- Changed files
- Systems touched
- Test results
- Evidence
- Estimated cost
- Actual cost when available
- Start time
- Completion time
- Outcome
- Failure details
- Retry count

Credentials, tokens, and secrets must never appear in execution records, Slack messages, prompts, or reports.

## Outcomes

### Completed

Use `completed` only when the executor reports that the requested action finished.

Completed does not mean verified.

### Failed

Use `failed` when the action did not finish successfully.

A failed action must never be shown as completed.

Preserve the error, attempted actions, evidence, cost, and affected files.

### Blocked

Use `blocked` when the action cannot safely proceed because of:

- Missing access
- Unresolved dependency
- Client mismatch
- Incorrect project or domain
- Required information missing
- Safety issue
- Permanent failure limit reached

Blocked tasks require a next step and should notify Slack.

## Retry policy

Automatic retries are allowed only for temporary failures such as:

- Rate limits
- Temporary service outages
- Network failures
- Temporary unavailable resources

Maximum automatic retries: three.

Retry timing should represent approximately:

1. Ten seconds
2. One minute
3. Five minutes

Tests must use a controllable clock and must not wait for these real durations.

Permanent failures must not be retried automatically.

After the retry limit:

1. Preserve all attempts.
2. Mark the task failed or blocked.
3. Notify Slack.
4. Ask for next steps.

## Cost control

Before execution, Max should show the estimated cost.

Execution must stop before exceeding an approved budget.

Use application code instead of AI for validation, calculations, duplicate checks, and status transitions.

Use the efficient model for routine work and stronger models for major website, strategy, ambiguity, and high-risk work.

Retries count toward the task's cost and attempt history.

## Client separation

Every execution belongs to exactly one task and exactly one client.

Max must verify that:

- Task client equals execution client.
- Files belong to the same client repository.
- External project belongs to the same client.
- Domain belongs to the same client.
- Evidence names the correct client.

Evidence from another client invalidates the execution for verification and must create a mismatch warning.

## Slack updates

Send short Slack updates when:

- Execution starts and action is meaningful
- A task is blocked
- A task fails
- Retry limit is reached
- Access is missing
- Execution completes and review is needed

Do not send long updates for routine background processing.

## Completion versus verification

Execution completion means the executor reports that the action finished.

Verification must separately confirm:

- Correct client
- Approved task was followed
- Output exists
- Tests passed
- Evidence is present
- Result matches the requested outcome
- No unexpected files or systems changed

Only verified work may resolve a finding or appear as verified completed work in reports.

## Cancellation and correction

An approved task may be cancelled by the agency owner or authorized team member before execution completes.

Cancellation preserves:

- Approval
- Execution attempts
- Costs
- Evidence
- Reason
- Time

If verification fails, return the task for correction or create a new task version. Do not erase the failed attempt.

## Final checklist

- Is the task approved?
- Is the correct client identified?
- Are dependencies resolved?
- Is required access available?
- Is the operation key unique?
- Is the budget known?
- Is the executor appropriate?
- Are intended actions recorded?
- Are changed files recorded?
- Are tests recorded?
- Are costs recorded?
- Are retries limited?
- Is failure distinct from completion?
- Is completion distinct from verification?
- Is evidence saved?
- Is Slack notified when action is needed?

