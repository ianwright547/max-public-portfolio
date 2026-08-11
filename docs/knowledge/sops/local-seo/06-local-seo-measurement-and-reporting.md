---
title: Local SEO measurement and reporting SOP
slug: local-seo-measurement-reporting
knowledge_type: sop
version: "1.0.0"
status: proposed
owner: agency
---

# Local SEO measurement and reporting SOP

## Purpose

This SOP covers baselines, geogrid data, Search Console interpretation, profile data, analytics, conversions, attribution, reporting, and limitations.

The rank map is the North Star for local visibility decisions. It measures top-three coverage across a defined geography and helps Max choose the next roadmap phase.

## Source classification

Every metric must include a source class:

- `live`: retrieved directly from the connected platform
- `imported`: exported from a named platform
- `manual`: entered by a person
- `modeled`: calculated from other data
- `mock`: test data
- `unknown`: source cannot be confirmed

Never label imported, manual, modeled, or mock data as live.

## Baseline

Before work begins, record:

- client
- location
- date and time
- profile identifier
- website property
- target queries
- service areas
- geogrid settings
- Search Console date range
- analytics date range
- conversions
- review metrics
- citation status
- page inventory
- known recent changes
- known seasonality
- data gaps
- rank-map top-three coverage and scan settings
- current roadmap phase

Do not compare results to an undocumented memory of past performance.

## Google Business Profile reporting

Possible profile metrics include:

- calls
- website clicks
- direction requests
- messages
- bookings
- searches or views, when available
- profile changes
- posts
- photos
- reviews

Interpretation rules:

- use the exact platform definition
- note whether a metric is sampled or limited
- do not treat an action as a completed sale
- do not combine locations without showing the aggregation method
- explain tracking changes
- annotate profile edits and outages
- do not infer user intent beyond the data

## Geogrid reporting

A geogrid scan is a location-based snapshot for a specific query.

Top-three coverage is the primary directional measure for phase decisions. It is not a universal rank, a guarantee, or proof of causation.

Record:

- keyword
- date
- platform
- grid size
- radius or spacing
- center point
- maximum tracked rank
- business identifier
- competitor set
- scan provider

Compare scans only when settings are consistent or differences are explained.

Useful outputs:

- top-three coverage
- average measured rank
- visibility share
- strong and weak zones
- competitor presence
- change over time

Use these directional gates with the Roadmap SOP:

- 10–15% after 8–10 weeks of correct foundation: evaluate Core 30 and technical/trust issues.
- 30–40%: evaluate geographic expansion.
- Plateau despite correct implementation: evaluate high-trust local authority and technical issues.

Do not:

- call one grid point the business's universal rank
- compare different radii without explanation
- claim causation from one before-and-after scan
- convert visibility into leads without a supported model
- report modeled leads as actual leads
- hide red or unranked points

Use plain client language while preserving the metric definition.

## Search Console scope

Search Console shows performance for the connected website property in Google Search and related reports. It does not provide a complete measure of Google Maps ranking.

An in-depth Max refresh preserves a bounded sample of query and page rows (up to
50 of each) alongside aggregate clicks and impressions. Queries with meaningful
impressions but no clicks become evidence-backed opportunities for title and
description testing; they are not treated as guaranteed ranking or traffic
outcomes.

Core metrics:

- clicks
- impressions
- click-through rate
- average position

Dimensions may include:

- query
- page
- country
- device
- date
- search appearance
- search type

## Search Console interpretation

## Report evidence provenance

Every generated report includes an evidence-provenance index. Each source row
identifies the source class, status, observation date (or reporting period),
and any recorded access limitation. Recommendations in the 30/60/90 plan carry
the matching finding source when one exists; otherwise they are explicitly
labeled as a portfolio-audit recommendation. When a plan item becomes a task,
that provenance is retained in the task's source finding so fulfillment and
outcome measurements can be audited later.

Do not present a recommendation as an observed result. If a source could not
be reached, keep the limitation visible and list the access or verification
needed to continue.

### Clicks

Clicks show recorded visits from supported Google Search results to the property under Google's counting rules.

Do not call clicks leads or sales without conversion evidence.

### Impressions

Impressions show eligible result visibility under Google's counting rules.

An impression does not mean the user read the page or noticed the business.

### Click-through rate

CTR equals clicks divided by impressions.

A CTR change may be affected by:

- position
- result layout
- query mix
- brand demand
- title and snippet
- seasonality
- device mix
- search features

Do not diagnose a title problem from CTR alone.

### Average position

Average position is the average topmost position recorded under Google's method.

It is not:

- an exact rank for every user
- a map pack rank
- a stable position
- a complete measure of visibility

Analyze trends for a defined query or page instead of relying only on property-wide average position.

## Search Console analysis workflow

1. Confirm the correct property.
2. Record the last complete date.
3. Exclude preliminary periods when stability matters.
4. Choose an exact date range.
5. Compare to the previous equivalent period.
6. Compare year over year when seasonality matters.
7. Segment branded and non-branded queries.
8. Segment commercial, local, and informational intent.
9. Segment by page.
10. Segment by device and country when relevant.
11. check canonical page assignment.
12. note anonymized and omitted query limitations.
13. connect findings to analytics or CRM only when identifiers support it.
14. record observations and hypotheses separately.

## Local query groups

Create documented query groups such as:

- brand
- primary service
- secondary service
- emergency
- cost
- local place names
- near me
- informational
- careers
- unrelated
- unknown

Use saved regular expressions or a reproducible classification rule when possible.

Do not hide informational traffic. Report it separately.

## Page interpretation

### High impressions and rising clicks

Possible observation:

- visibility and traffic increased

Do not state why until evidence supports the cause.

### High impressions and low clicks

Possible hypotheses:

- lower position
- result feature competition
- weak title or snippet
- mismatched intent
- brand mix
- broad query exposure

Review the query and page before recommending a rewrite.

### Clicks down, impressions stable

Possible hypotheses:

- CTR changed
- result layout changed
- average position changed
- brand demand changed
- device mix changed

### Impressions down

Possible hypotheses:

- demand changed
- indexing changed
- ranking changed
- page targeting changed
- seasonality
- canonical changes
- reporting filters changed

### Traffic down after content cleanup

A decline can be acceptable when removed traffic was irrelevant and qualified actions improve.

Verify with:

- query intent
- conversions
- calls
- assisted conversions
- local visibility
- target page performance

Do not celebrate lower traffic without business evidence.

## Blog reporting

Report blogs by purpose:

- direct local lead support
- assisted conversion
- internal link support
- informational demand
- authority or outreach
- customer education
- seasonal visibility

Metrics may include:

- Search Console clicks and impressions
- engaged sessions
- conversions
- assisted conversions
- links earned
- internal click-through
- refresh date

Do not judge every blog by direct calls alone.

Do not keep low-value posts solely because they receive unrelated traffic.

## Causation language

Use:

- `observation`: what the data shows
- `correlation`: two changes occurred together
- `hypothesis`: possible explanation
- `supported attribution`: several evidence sources support a connection
- `confirmed cause`: direct evidence proves it

Most SEO reports should use observation, correlation, or hypothesis.

Avoid:

- "this change caused the ranking increase" after one scan
- "Google rewarded the page"
- "the schema increased leads"
- "reviews caused the map improvement"

unless direct evidence supports the statement.

## Reporting time frames

Choose based on the question:

- daily for incidents and profile changes
- weekly for active execution and monitoring
- 28-day comparisons for recent Search Console trends
- monthly for client reporting
- quarterly for strategy
- year over year for seasonality

Use exact dates in every report.

## Report content

A client report should include:

- reporting period
- verified sources
- summary
- work proposed
- work approved
- work executed
- work verified
- measured outcomes
- limitations
- risks
- next priorities
- approval requests
- evidence links

Do not combine proposed, executed, and verified work.

## Ranking limitations statement

Include when rankings are discussed:

- local results vary by searcher location and query
- distance is a major factor
- the platform does not publish full weighting
- tools observe only the settings used
- rankings can change
- no top-three result is guaranteed
- no revenue outcome is guaranteed

## Completion standard

Measurement and reporting are complete when:

- data sources and dates are stated
- live and non-live data are separated
- metrics use correct definitions
- organic and map data are separated
- branded and non-branded demand are considered
- observations and causes are separated
- no rankings or customer results are invented
- limitations are visible
- the report passed the Human Writing SOP
