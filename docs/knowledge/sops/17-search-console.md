---
title: Search Console
slug: search-console
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - Search Console connections
  - performance metrics
  - SEO reporting
  - SEO findings
  - scheduled synchronization
owner: agency
review_required: true
---

# Search Console

## Purpose

This SOP defines how Max connects to Search Console for read-only performance data, historical metric storage, comparisons, explanations, and evidence-backed findings.

## Read-only scope

The initial Search Console workflow is read-only.

Max may retrieve:

- Clicks
- Impressions
- Click-through rate
- Average position
- Queries
- Pages
- Countries
- Devices
- Date ranges

Max must not automatically change Search Console ownership, permissions, property settings, or account settings.

## Client connection

Each connection stores:

- Client ID
- Property URL
- Property type
- External property ID
- Verification status
- Permission status
- Connection status
- Last successful synchronization
- Last error

Before synchronizing, Max must confirm that the property belongs to the client's verified domain.

If the property, domain, or client does not match, Max must stop immediately and create a mismatch issue.

## Permissions

Use the minimum read permission required for performance data.

Missing permission creates a missing-access state and a Slack notification.

Expired authorization creates an expired-connection state and stops synchronization.

Ownership, permissions, and account-setting changes require manual agency-owner action.

## Synchronization

When enabled, Max may synchronize daily. Weekly and monthly reports use the saved snapshots.

Every synchronization records:

- Client
- Property
- Requested period
- Retrieved metrics
- Source label
- Started time
- Completed time
- Result
- Error when applicable

Live Search Console data is labeled `live`.

Manual data is labeled `manual`.

Imported data is labeled `imported`.

Mock test data is labeled `mock`.

## Historical snapshots

Every metric snapshot is preserved. Synchronizing the same client, property, metric, and period must be idempotent and must not create uncontrolled duplicates.

Snapshots must not be overwritten. Corrections create a new record or correction record with its source and time.

## Missing data

If Search Console has no usable data, Max records `not_enough_data` rather than replacing the result with zero.

If the previous value is zero, show the numerical change and mark the percentage change unavailable.

## Comparisons

Application code calculates:

- Current versus previous period
- Current versus baseline
- Absolute change
- Percentage change when mathematically valid

AI may explain calculated results but must not change the numbers.

Negative changes remain visible.

## AI explanations

Use DeepSeek Flash for routine summaries. Use OpenAI Terra for complex explanations or conflicting evidence.

An explanation must be based on saved Search Console metrics and labeled evidence.

AI may describe possible explanations as possibilities. It must not claim a cause unless the evidence supports it.

Record:

- Provider
- Model
- Input snapshot
- Output
- Source metrics
- Explanation version

## Findings and tasks

Search Console data may support a health finding or SEO task only when a rules-based check identifies a meaningful issue.

Healthy or ordinary results must not create unnecessary work.

Any task must remain linked to the correct client, property, metrics, and evidence.

## Errors and retries

Temporary rate limits, network failures, and service outages may retry using the existing retry policy.

After the retry limit:

1. Preserve the failed synchronization.
2. Keep previous snapshots available.
3. Mark the connection or sync as failed.
4. Notify Slack when action is needed.

## Domain changes

If the client domain changes, pause Search Console synchronization until the new property is verified and connected to the same client.

## Reporting

Search Console reports must show:

- Property
- Period
- Source type
- Clicks
- Impressions
- CTR
- Average position
- Queries and pages when included
- Comparison period
- Missing data or errors
- Evidence link or record

Client-facing reports require review before delivery.

## Final checklist

- Correct client?
- Correct verified property?
- Read permission available?
- Connection status current?
- Source labeled `live`?
- Historical snapshot preserved?
- Duplicate sync prevented?
- Comparisons calculated by code?
- Negative changes visible?
- AI explanation supported by evidence?
- No ownership or permission changes attempted?
- Errors and retries recorded?

