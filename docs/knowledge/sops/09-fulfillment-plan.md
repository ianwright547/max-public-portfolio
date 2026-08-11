---
title: Fulfillment Plan
slug: fulfillment-plan
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - fulfillment plans
  - task proposals
  - task dependencies
  - website work
  - SEO work
  - content work
  - reporting work
owner: agency
review_required: true
---

# Fulfillment Plan

## Purpose

This SOP defines how Max turns an approved client goal, evidence-backed finding, or strategic request into an organized fulfillment plan.

A plan explains what should be done, why it matters, what it will cost, what access is needed, what depends on what, and how success will be verified.

## Plan creation

Max may create a plan after onboarding is approved and the client is ready for fulfillment.

Plans may also be created manually by the agency owner or an authorized team member from:

- A client profile
- A health finding
- Slack
- An approved strategic request

Max may create plans automatically when evidence or an approved request supports the work. An automatically created plan remains proposed until approved.

## Healthy clients

A healthy health check must not create unnecessary work.

A healthy client may receive a plan only when there is a separate approved strategic request, scheduled content workflow, or other deliberate business goal.

## Plan contents

Every plan must include:

- Client ID
- Plan ID
- Goal
- Exact requested outcome
- Reason
- Evidence or approved direction
- Tasks
- Task order
- Dependencies
- Required access
- Risk level
- Estimated effort
- Estimated cost
- Cost-saving options
- Success criteria
- Verification requirements
- Approval state
- Owner or responsible team member
- Proposed time

## Plan versions and history

One client may have multiple plans.

Every plan receives a unique ID and version number. Corrections create a new version rather than overwriting the previous plan.

Previous plans, rejected plans, cancelled plans, failures, decisions, and results remain visible.

## Task structure

One plan may contain multiple tasks.

Each task must have:

- One client
- One clear requested outcome
- A reason
- Evidence or an approved strategic direction
- Required access
- Dependencies
- Risk
- Estimated effort
- Estimated cost
- Acceptance criteria
- Verification method

A task that cannot be explained or verified is not ready for execution.

## Dependencies

Tasks may depend on other tasks.

Dependent tasks cannot become ready while a required dependency is unresolved.

Tasks may run out of order only when they have no unresolved dependency.

If a dependency fails, the dependent tasks become blocked. Max must explain:

- Which dependency failed
- Which tasks are affected
- What must happen next

When a blocker is resolved, Max rechecks access, dependencies, and acceptance criteria before moving eligible tasks to ready.

## Risk levels

Plans and tasks use:

- `low`: reversible, limited impact, and easy to check.
- `medium`: meaningful client impact but recoverable.
- `high`: major client, external, cost, or publishing impact.
- `critical`: potential data loss, client mismatch, security issue, or serious external harm.

Risk determines the amount of review and evidence required. It does not override the agency owner's final authority.

## Required access

Each task must identify required access, such as:

- GitHub
- Vercel
- Domain
- Website
- Google Business Profile
- Search Console
- Website analytics
- None

If required access is missing, Max may continue planning but must block the affected execution task and notify Slack.

## Approval and execution

Plan and task states include:

```text
proposed
approved
active
paused
blocked
completed
cancelled
archived
```

Proposed work cannot execute.

Once the agency owner or authorized team member approves the plan or task, approval authorizes execution. No second publish confirmation is required.

Max may still stop approved work for:

- Client mismatch
- Incorrect repository, domain, or external resource
- Missing required access
- Unresolved dependency
- Safety or security issue

The agency owner and authorized team members have final authority over whether approved work proceeds.

## Duplicate prevention

Max must prevent duplicate active tasks for the same client, issue, and requested outcome.

When a similar task already exists, Max should link to the existing task unless the new requested outcome is materially different.

Historical completed, failed, rejected, and cancelled tasks do not disappear when a new version is created.

## Cost and effort

Every substantial plan and task includes an estimated effort and cost.

The plan should identify ways to reduce cost, including:

- Smaller models for routine work
- Reusing approved content and components
- Batching related work
- Using application code instead of AI for calculations and validation
- Handling low-risk work manually when that is cheaper
- Avoiding repeated context and duplicate requests

If the expected cost changes materially or would exceed the approved budget, Max must stop before exceeding it and notify Slack.

## Codex packets

Plans create a Codex Work Packet when work involves:

- GitHub files
- Website generation
- Website edits
- SEO pages
- Blogs
- Technical SEO
- Vercel deployment

The packet must contain the client, repository, branch, Vercel project, domain, approved outcome, design requirements, SEO skills, allowed files, tests, cost guidance, and publishing state.

## Slack communication

Max should notify Slack for:

- Plan approval required
- Plan approved
- Missing access
- Blockers
- Task failures
- Meaningful progress that requires action
- Plan completion

Routine background processing should remain quiet.

Messages should be short, use bullets, and include a Max link when review or action is needed.

## Rejection, pause, and cancellation

When a plan is rejected:

1. Preserve the rejected plan.
2. Record the decision and reason when available.
3. Create a new version if changes are requested.

When a plan is paused, stop new work while preserving all history.

When a plan is cancelled, do not delete completed work, failures, evidence, or decisions.

## Completion and verification

Plan completion does not prove that every result is correct.

Each task must separately record:

- Execution status
- Changed files or intended actions
- Tests
- Evidence
- Cost
- Failure details
- Verification result

Only verified task results may resolve findings or appear as verified completed work in reports.

## Final plan record

The final plan record should show:

- Approved goal
- Tasks and order
- Dependencies
- Required access
- Approval records
- Estimated and actual costs
- Failures and blockers
- Codex packets
- Execution results
- Evidence
- Verification results
- Unresolved work
- Recommended next steps

## Final checklist

- Is the client correct?
- Is there a clear goal?
- Is the outcome exact?
- Is the evidence or approved direction recorded?
- Are tasks individually explainable?
- Are dependencies listed?
- Is required access known?
- Is risk assigned?
- Is cost estimated?
- Are cost-saving options included?
- Are duplicate active tasks prevented?
- Is approval recorded?
- Can approved work proceed safely?
- Are Codex packets created when needed?
- Are failures and blockers visible?
- Is verification required before resolution?

