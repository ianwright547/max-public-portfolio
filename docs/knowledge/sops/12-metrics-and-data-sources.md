---
title: Metrics and Data Sources
slug: metrics-and-data-sources
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - metric snapshots
  - baselines
  - website analytics
  - Search Console data
  - Google Business Profile data
  - reports
owner: agency
review_required: true
---

# Metrics and Data Sources

## Purpose

This SOP defines how Max records, labels, preserves, and compares client metrics.

## Source labels

Every metric must be labeled as one of:

- `manual`
- `mock`
- `imported`
- `live`

Mock, manual, and imported information must never be represented as live API data.

## Supported metrics

Max may track:

- Reviews
- Rating
- Calls
- Website clicks
- Direction requests
- Impressions
- Search clicks
- Website visits
- Page views
- Form submissions
- Last Google post date

Invalid metric names must be rejected instead of saved as arbitrary data.

## Client separation

Every metric belongs to exactly one client. Before saving data, Max must verify the client and source connection.

Possible client or external-resource mismatches stop synchronization immediately.

## Historical preservation

Every snapshot is permanent and includes:

- Client
- Metric name
- Value
- Measurement period
- Recorded time
- Source type
- Source reference when available

Existing snapshots must never be overwritten.

## Baselines and comparisons

One appropriate snapshot may be marked as the starting baseline. The baseline remains visible even after newer snapshots exist.

Max compares:

- Current period with the baseline
- Current period with the previous period

Code calculates absolute and percentage changes. AI may explain the result but must not invent a cause.

If the previous value is zero, show the numerical change and label percentage change as unavailable rather than dividing by zero.

## Missing data

Missing data is labeled as missing or not enough data. Max must not substitute a guessed value.

## Final checklist

- Correct client?
- Valid metric?
- Source labeled?
- Period recorded?
- Historical snapshot preserved?
- Baseline identified when applicable?
- Comparison calculated by code?
- Missing data shown honestly?

