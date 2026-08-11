---
title: Website Analytics
slug: website-analytics
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - website analytics
  - portfolio metrics
  - website reports
  - health checks
owner: agency
review_required: true
---

# Website Analytics

## Purpose

This SOP defines how Max uses the existing website analytics dashboard/project and its adapter to import website performance for connected clients.

The existing implementation is the source of truth for the available aggregate fields and synchronization behavior. The knowledge layer must reference the adapter rather than invent a second metric schema.

Current implementation reference:

- Adapter: `app/website_analytics.py`
- Source label: `website_analytics_dashboard`
- Supported windows: 7, 30, and 90 days
- Stored history: `WebsiteMetricSnapshot`
- Client mapping: verified website/client manifest and website connections

## Connection and client mapping

Every imported snapshot belongs to exactly one client.

The adapter must map tracker sites to the correct verified client and skip unmatched sites rather than assigning them to another client.

If a website or tracker cannot be confidently mapped to a client, do not import it under a guessed client.

## Source labels

Live dashboard data is labeled `live` or with the existing provider source label `website_analytics_dashboard`.

Manual, mock, and imported values keep their own labels and are never represented as live dashboard data.

## Historical preservation

Snapshots preserve:

- Client
- Period start
- Period end
- Window days
- Available provider metrics
- Tracker sites
- Source
- Recorded time

Repeated synchronization for the same window and period reuses the existing snapshot instead of creating an uncontrolled duplicate.

## Existing dashboard behavior

The website analytics dashboard supports portfolio and client views. Max should use the existing adapter and models when adding new reports or comparisons.

Do not create a second conflicting source for the same dashboard data.

## Missing and unmatched data

No matching tracker data means no fabricated snapshot. Unmatched tracker sites should be recorded for review.

Missing values remain missing or not enough data. They must not silently become zero.

## Comparisons and explanations

Application code calculates period comparisons and conversion values. AI may explain the measured values but must not invent causes, revenue, leads, or outcomes.

Use DeepSeek Flash for routine summaries and OpenAI Terra for complex explanations.

## Scheduling and reporting

Website analytics synchronization may run as one coordinated batch for all eligible connected clients. Weekly mini reports and monthly full reports may reuse the saved snapshots.

Clients without a verified website analytics connection are skipped and recorded without unnecessary AI work.

## Final checklist

- Existing adapter used?
- Correct client mapping?
- Source labeled?
- Valid window?
- Snapshot preserved?
- Duplicate sync prevented?
- Unmatched trackers recorded?
- No values invented?
- Reports use saved snapshots?

