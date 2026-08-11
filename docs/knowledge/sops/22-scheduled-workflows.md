---
title: Scheduled Workflows
slug: scheduled-workflows
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - health checks
  - metrics
  - blogs
  - Google Business Profile posts
  - reports
  - Slack reminders
owner: agency
review_required: true
---

# Scheduled Workflows

## Purpose

Max runs recurring work as coordinated batches so all eligible clients can be processed at the same time without duplicating work or wasting AI credits.

## Per-client controls

Each workflow is enabled or disabled per client:

- Health checks
- Website analytics
- Search Console
- Weekly blogs
- Google Business Profile posts
- Weekly mini reports
- Monthly full reports
- Slack notifications

Disabled workflows do not create new work. History remains visible.

## Default schedules

- Health checks: weekly.
- Website analytics: daily when a live connection exists.
- Search Console: daily when a live connection exists.
- Google Business Profile posts: Monday at 9:00 AM America/Chicago.
- Blog drafts or posts: weekly when enabled.
- Mini reports: weekly.
- Full reports: monthly.

The agency may change the configured time later without changing the workflow rules.

## Coordinated batches

Universal workflows run as one batch for all eligible clients:

1. Load enabled clients.
2. Check live connections and required access.
3. Create an idempotency key for client, workflow, and period.
4. Skip clients without required connections.
5. Run eligible work.
6. Preserve results and errors.
7. Notify Slack only when action is needed.

## Blogs

When the approved blog workflow is enabled, Max may generate and publish the blog automatically after factual, SEO, human-writing, and publication checks pass.

Blogs must use approved client facts, relevant keywords, and no fabricated claims.

## Google Business Profile posts

Scheduled work may draft a post for clients with a verified live connection and
enabled workflow, but publication remains a separate owner-approved action in
the current release. Clients without live access are skipped with
`skipped_no_live_connection`; provider failures and in-flight publication locks
remain visible in the audit history.

Profile edits, categories, services, hours, permissions, and ownership are not covered by the automatic post exception.

## Reports

Weekly mini reports are short progress and monitoring summaries.

Monthly full reports include detailed metrics, verified work, findings, failures, costs, risks, and next steps.

Client-facing reports require review before delivery unless a separate approved delivery workflow exists.

## Cost controls

Scheduled work uses application code for calculations and checks. DeepSeek Flash handles routine content. AI work is skipped when required data is missing or the client has no eligible connection.

Scheduled work respects the $30 target and $50 hard monthly AI maximum.

## Failures and missed runs

Temporary failures retry using the existing retry policy. After retry limits, preserve the failure and notify Slack when action is needed.

Missed schedules run at the next valid occurrence unless safe, relevant backfill is explicitly supported.

## Final checklist

- Workflow enabled?
- Correct client?
- Required live connection present?
- Batch period correct?
- Idempotency key unique?
- AI call necessary?
- Cost limit respected?
- History preserved?
- Failure recorded?
- Slack notification needed?
