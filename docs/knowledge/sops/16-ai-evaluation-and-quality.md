---
title: AI Evaluation and Quality
slug: ai-evaluation-and-quality
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - AI outputs
  - prompts
  - skills
  - SOP changes
  - website content
  - SEO content
  - reports
owner: agency
review_required: true
---

# AI Evaluation and Quality

## Purpose

Max evaluates AI outputs before they become approved work, published content, or active knowledge.

## Required evaluation areas

Every applicable evaluation checks:

- Client separation
- Factual accuracy
- Source use
- Unsupported claims
- Approval state
- Required format
- Relevant SOP and skill use
- Evidence requirements
- Cost and model routing

## Prohibited output

Fail evaluation when an output invents or implies unsupported:

- Services
- Locations
- Reviews
- Testimonials
- Prices
- Certifications
- Awards
- Rankings
- Revenue
- Leads
- Results
- Guarantees
- Business history

## Client separation tests

Use test cases that verify:

- Client A information cannot appear under Client B.
- A task cannot use another client's repository or domain.
- Evidence names the correct client.
- Reports contain only the selected client's records.

## Workflow tests

Test:

- Proposed work cannot execute.
- Approved work can proceed.
- Failed work is not completed.
- Completed work is not automatically verified.
- Unverified work cannot resolve a finding.
- Duplicate operations are prevented.
- Historical versions remain visible.
- Missing evidence creates the correct review outcome.

## Knowledge-change evaluation

Max may propose an SOP, skill, prompt, or template improvement when repeated feedback shows a pattern.

The improvement must:

1. Remain proposed.
2. Include the reason for the change.
3. Identify affected workflows.
4. Be tested against representative prior examples.
5. Be reviewed by the agency owner.
6. Become active only after approval and versioning.

Max must not silently rewrite active safety rules, client facts, permissions, or SOPs.

## Output review

Evaluation should record:

- Input snapshot
- Client
- Task
- SOP versions
- Skill versions
- Prompt version
- Model role
- Generated output
- Human edits
- Approval or rejection
- Rejection reason
- Verification result
- Later measured outcome when available

## Quality result

Use:

```text
passed
failed
needs_manual_review
not_enough_evidence
```

A failed evaluation must not be presented as a successful result.

## Final checklist

- Correct client?
- Facts supported?
- No invented claims?
- Correct SOPs and skills used?
- Approval state respected?
- Output format correct?
- Evidence sufficient?
- Cost and model appropriate?
- Historical record preserved?
- Human review required where appropriate?

