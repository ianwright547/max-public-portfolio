---
title: Verification and Finding Resolution
slug: verification-and-finding-resolution
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - task verification
  - execution review
  - findings
  - reports
owner: agency
review_required: true
---

# Verification and Finding Resolution

## Purpose

Verification confirms whether completed work actually met the approved request. A completed task is not verified work, and a completed task does not automatically resolve its finding.

## Required checks

Verification must confirm:

- Correct client was affected
- Approved task was followed
- Requested output exists
- Tests passed
- Evidence is present
- Result matches the requested outcome
- No unexpected files or systems changed

## Outcomes

```text
verified
verification_failed
needs_manual_review
not_enough_evidence
```

Only `verified` work may resolve a finding.

## Evidence

Evidence may include:

- Changed files
- Deployment URL
- Screenshots
- Test results
- Logs without credentials
- External-record references
- Before and after values
- Metric snapshots
- Human review notes

Evidence must identify the correct client and source. Evidence from another client invalidates verification.

## Decisions

Every decision records:

- Reviewer
- Client
- Task
- Time
- Evidence
- Explanation
- Outcome

Previous failed attempts remain visible.

## Repeatability

Verification may be repeated. Repeating verification creates a new decision record or links to the existing decision without creating duplicate work.

## Finding resolution

A finding may be resolved only when:

1. Its source task completed.
2. Verification outcome is `verified`.
3. Evidence supports the requested result.
4. The reviewer decision is saved.

Failed verification returns the task for correction or manual review. It does not resolve the finding.

## Final checklist

- Correct client?
- Approved request followed?
- Output exists?
- Tests passed?
- Evidence present?
- Result matches request?
- No unexpected changes?
- Reviewer and time recorded?
- Finding resolved only after verification?

