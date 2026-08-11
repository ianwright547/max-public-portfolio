---
title: Slack Communication and Approval
slug: slack-communication-and-approval
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - Slack messages
  - client channels
  - Max mentions
  - approvals
  - task decisions
  - notifications
  - reports
  - questions
owner: agency
review_required: true
---

# Slack Communication and Approval

## Purpose

Slack is Max's working communication and approval surface. Max remains the system of record for clients, tasks, decisions, evidence, and history.

Slack should make the next action obvious without creating unnecessary noise or unnecessary AI calls.

## Channel structure

Each client receives one public Slack channel named after the client's business name using Slack-safe formatting.

The client channel is used for:

- Onboarding
- Questions
- Website work
- SEO work
- Task updates
- Findings
- Approvals
- Reports
- Failures and blockers

Separate approval, report, alert, or content channels are not required for the current workflow.

A general public channel named `Max` is used for agency-wide questions and requests that do not yet belong to one client.

Clients are not invited to the internal agency channels in this workflow.

## Message style

Slack messages should be short and contain the information needed to make the next decision.

Use bullets instead of large paragraphs.

Internal Slack messages should be clear and practical. They do not need to use the Universal Human Writing SOP unless they will be shown to a client or another external audience.

The client name should be shown when:

- The message is in the general `Max` channel.
- The message is in a channel that may contain multiple client discussions.
- The message could be forwarded or detached from its original thread.

The client name does not need to be repeated in every message inside a dedicated client channel.

Include a link back to Max when the recipient needs to review, approve, inspect evidence, or take an action. Do not add links when they do not help the next step.

## Standard message format

Use the following structure for meaningful workflow messages:

```text
What happened
- Short factual summary

Why it matters
- Practical impact or reason

Action needed
- Exact decision or next step

Status
- Current Max status

Max
- Link only when review or action is needed
```

## Main message use cases

### New intake received

```text
New onboarding intake received

- Business: [business name]
- Status: [status]
- Missing: [items or None]
- Conflicts: [items or None]

Action needed
- Review the intake and choose the next step.

Max
- [link]
```

### Missing information

```text
Information needed

- Business: [business name]
- Needed: [short list]
- Why: [what cannot continue]

Action needed
- Reply with the missing information or tell Max to continue with low-risk work.
```

### Proposed profile review

```text
Client profile ready for review

- Business: [business name]
- Source intake: [intake ID]
- Missing: [items or None]
- Conflicts: [items or None]

Action needed
- Approve the profile, request changes, or reject it.

Max
- [link]
```

### Website-generation request

```text
Website generation requested

- Business: [business name]
- Domain: [domain]
- Mode: [new_build / replicate / improve / repair]
- Skills: [website skill, SEO skill]
- Status: [status]

Action needed
- Review the Codex packet or approve the next step.

Max
- [link]
```

### Fulfillment plan ready

```text
Fulfillment plan ready

- Business: [business name]
- Tasks: [count]
- First action: [task]
- Blockers: [items or None]
- Estimated effort: [estimate]
- Estimated cost: [estimate]

Action needed
- Approve the plan, request changes, or reject it.

Max
- [link]
```

### Task approval required

```text
Task approval required

- Task: [title]
- Requested outcome: [exact outcome]
- Reason: [why it is needed]
- Risk: [risk]
- Required access: [access or None]
- Dependencies: [dependencies or None]

Action needed
- Approve or reject this task.

Max
- [link]
```

### Task blocked or failed

```text
Task blocked

- Task: [title]
- Reason: [short failure or blocker]
- Attempts: [count]
- Next step: [question or required access]

Action needed
- Resolve the blocker, retry, or change the plan.

Max
- [link]
```

### Verification review

```text
Verification review needed

- Task: [title]
- Client: [business name when needed]
- Output: [what exists]
- Tests: [passed / failed / missing]
- Evidence: [present / missing]
- Unexpected changes: [None or list]

Action needed
- Verify, request correction, or mark for manual review.

Max
- [link]
```

### Report available

```text
Report available

- Business: [business name]
- Period: [period]
- Data sources: [manual / mock / imported / live]
- Key change: [short factual change]
- Unresolved items: [count]

Action needed
- Review or approve the report.

Max
- [link]
```

### Critical health issue

```text
Critical issue found

- Business: [business name]
- Issue: [title]
- Evidence: [short evidence]
- Source: [source]
- Recommended action: [action]

Action needed
- Review the finding and decide whether to create a task.

Max
- [link]
```

## `@max` behavior

When someone mentions `@max` in a client channel, Max should use the channel and thread context to identify the client.

For a small, clear, low-risk request, Max may respond briefly or perform the task immediately. A short acknowledgment such as `OK`, `Yes`, or `Done` is acceptable when no longer explanation is needed.

For a major, risky, external, or unclear request, Max must:

1. Create or update the related Max record.
2. Explain the requested action and risk briefly.
3. Create an approval request.
4. Wait for the approval before acting.

## General `Max` channel

When a request appears in the general `Max` channel and does not identify a client, Max should ask:

```text
Which client should I attach this to?
```

Max may remember the client from the current thread when the relationship is unambiguous. If the client is still unclear, Max must ask before creating a client-specific action.

Meaningful questions and answers should be saved in Max when doing so does not create unnecessary cost or duplicate records. Trivial acknowledgments do not need a separate AI record.

## Button actions

Approvals use Slack buttons rather than emoji reactions.

Supported actions may include:

- Approve
- Reject
- Request changes
- Ask a question
- Retry
- Mark blocked
- Verify
- Needs manual review

The approval interaction should be:

```text
Select action
      ↓
Show the exact action and risk
      ↓
Confirm
      ↓
Save the decision in Max
```

Buttons create real Max actions. A visual reaction alone does not approve work.

Consequential task rejection must continue to follow the task rule requiring a rejection reason. Minor drafts or informational requests may be declined without a formal reason when no work is authorized.

Every meaningful decision records:

- Slack user
- Max user, when available
- Client
- Related record
- Exact decision
- Timestamp
- Reason, when required or provided
- Slack channel and message reference

Anyone in the configured internal workspace may use the buttons in the current workflow. Max must still record who acted and preserve the decision history.

## Evidence and warnings

Max should show warnings when evidence is missing, the client is uncertain, or an external resource has not been verified.

Missing evidence should not silently become positive evidence. A user may override a warning where the applicable workflow permits it, but the override must be recorded.

Max should not silently refuse every action because evidence is incomplete. Instead, it should label the action as needing manual review or not enough evidence and explain what is missing.

## Notifications

Send immediate Slack notifications for:

- Approval required
- Critical health issue
- Task failure
- Verification failure
- Missing required access
- Cost threshold exceeded
- Meaningful performance change
- Scheduled report available

Do not send notifications for:

- Healthy checks
- Normal background processing
- Repeated duplicate findings
- Small unimportant changes
- Successful routine operations requiring no action

Duplicate notifications for the same unresolved event must be prevented. If the event has already been sent, Max should update or link the existing record instead of sending unlimited copies.

## Delivery failures

If Slack delivery fails, Max should retry when the error is temporary. If retrying does not work, Max should notify the agency owner through another available internal method and record the Slack delivery failure.

The underlying Max decision must remain saved even when Slack delivery fails.

For approval workflows that require Slack confirmation, the decision remains pending until a valid action is recorded in Max. A failed notification alone is not an approval.

## Final checklist

Before sending or acting on a Slack message, Max should confirm:

- Is the correct client known?
- Is the message necessary?
- Is the message short and clear?
- Is the next action obvious?
- Is a Max link needed?
- Is approval required?
- Is the actor allowed to take the action?
- Is the decision saved in Max?
- Could this notification duplicate an unresolved event?
- Are credentials and sensitive secrets excluded?

