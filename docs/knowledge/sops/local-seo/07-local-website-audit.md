---
title: Local website audit SOP
slug: local-website-audit
knowledge_type: sop
version: "1.0.0"
status: proposed
owner: agency
humanizer_required: true
---

# Local website audit SOP

## Purpose

This SOP tells Max how to audit a local business website from setup through final recommendations.

It combines technical evidence, page intent, Local SEO facts, Search Console data, internal links, structured data, and business outcomes into one prioritized action plan.

## Audit principles

- Inspect before recommending.
- Record the source and date of every finding.
- Review the whole site before judging one page.
- Separate a technical failure from a content weakness.
- Separate a ranking observation from a cause.
- Do not delete content based only on traffic.
- Do not create pages for services or places the business does not support.
- Do not report work as completed until the live result is verified.
- Do not promise rankings, leads, revenue, or completion timing.

## Required inputs

Collect when available:

- approved client brief
- canonical domain
- website platform
- production access
- sitemap
- robots.txt
- Search Console property
- analytics property
- conversion source
- call-tracking source
- crawl export
- current URL list
- approved services
- approved locations and service areas
- Google Business Profile landing page
- profile identifiers
- known migrations or recent changes
- previous audits
- audit goal
- reporting period

Missing access should be listed as a limitation, not filled with assumptions.

## Phase 1: Establish scope

Record:

- client
- location or brand scope
- domain
- subdomains included
- country and language
- audit date
- last complete data date
- target service clusters
- target place clusters
- known business priorities
- known incidents
- excluded systems
- output destination
- approval level

Choose one audit type:

- full site
- priority-page
- technical
- content
- internal-link
- migration
- index recovery
- location-page
- blog inventory
- conversion-path
- follow-up verification

## Phase 2: Confirm the canonical site

Test the main variations:

- HTTP
- HTTPS
- www
- non-www
- trailing slash patterns
- uppercase or lowercase paths when relevant
- common parameter versions

Record:

- preferred host
- preferred protocol
- redirect behavior
- canonical behavior
- duplicate access
- mixed internal links

Do not assume a redirect exists because a browser lands on the preferred URL.

## Phase 3: Create the URL inventory

Use available sources:

- crawl
- XML sitemap
- Search Console
- analytics
- internal links
- content system export
- server or CDN logs when approved
- backlinks
- manual navigation

Deduplicate by canonical URL while retaining alternate versions as evidence.

Classify every important URL:

- homepage
- category page
- service page
- emergency service page
- physical location page
- service-area page
- service and place page
- blog post
- FAQ
- project or case-study page
- about page
- contact page
- conversion page
- policy or utility page
- tag or archive page
- media file
- redirect
- error
- duplicate
- unknown

Store:

- URL
- page type
- title
- H1
- status code
- index directive
- canonical
- sitemap presence
- internal-link count
- clicks
- impressions
- conversions
- backlinks
- last update
- approved service
- approved place
- proposed action

Do not label missing tool values as zero unless zero is confirmed.

## Phase 4: Crawl and index review

Check:

- response codes
- redirect chains
- redirect loops
- soft 404s
- broken internal links
- noindex
- robots.txt blocks
- canonical conflicts
- sitemap conflicts
- orphan pages
- duplicate titles
- duplicate H1s
- duplicate metadata
- duplicate or near-duplicate pages
- raw and rendered content
- inaccessible main content
- internal links that depend on scripts
- pages with no clear purpose
- important pages outside the sitemap
- redirected or blocked pages inside the sitemap

For each finding, record the affected URLs and exact evidence.

A page can be technically available and still fail to serve its intended query.

## Phase 5: Review priority pages

Review the homepage, profile landing page, category pages, priority service pages, priority place pages, and high-value blogs.

For each page, confirm:

### Purpose

- one primary intent
- clear target reader
- clear service
- accurate place
- clear next action

### Search elements

- accurate title
- clear H1
- useful opening copy
- natural use of service and place
- no keyword stuffing
- no vague slogan replacing the topic
- no competing primary page for the same intent

### Business truth

- approved business name
- correct phone
- correct address handling
- accurate hours
- accurate services
- accurate service areas
- approved prices
- approved qualifications
- approved guarantees
- traceable proof

### Usefulness

- explains what the customer needs
- states what is included
- addresses important questions
- includes real proof where available
- avoids filler
- links to the right next steps
- supports mobile use
- avoids intrusive elements that block the main action

### Local integrity

- physical location language is truthful
- service-area language does not imply an office
- local details are real
- location reviews belong to that location
- staff and assets belong to that location
- no city-swapped duplicate exists

## Phase 6: Review content coverage

Build a service-by-place matrix.

For each approved service and place, identify:

- existing page
- page quality
- intent match
- index status
- Search Console evidence
- conversion evidence
- internal links
- duplication
- content gap
- action

Allowed actions:

- keep
- improve
- expand
- refresh
- merge
- redirect
- remove
- noindex
- reposition
- add internal links
- create replacement
- create new page
- create blog post
- add FAQ section
- needs client confirmation

A new page is not the default answer.

## Phase 7: Review blogs

Classify each post by purpose:

- local lead support
- service education
- cost or decision support
- seasonal issue
- local rule
- project evidence
- internal-link support
- outreach support
- general informational
- unrelated
- unknown

Review:

- query intent
- factual accuracy
- current relevance
- Search Console data
- conversions and assisted conversions
- backlinks
- internal links
- overlap with other content
- service or place supported
- update need

Do not remove a blog because it is not a direct service page.

Do not keep a blog only because it receives unrelated traffic.

Before removal or merger, check backlinks, conversions, assisted conversions, seasonality, internal links, rankings, and replacement options.

## Phase 8: Review internal links

Map:

- homepage to categories
- categories to services
- services to places
- places to available services
- blogs to related services
- service pages to supporting blogs
- nearby places where useful
- breadcrumbs
- calls to action

Find:

- orphan priority pages
- broken links
- redirecting links
- links to noncanonical URLs
- repeated exact-match anchors
- pages linked from every page without need
- deep pages with no clear path
- unrelated cross-links
- missing links from high-authority pages

Recommend links by reader need and topic relationship.

## Phase 9: Review Local SEO identity

Compare the website with approved profile records:

- business name
- public address or hidden-address status
- primary phone
- website
- hours
- primary category
- services
- service areas
- location names
- location pages

Flag material conflicts.

Do not treat punctuation differences as equal to a wrong phone or old address.

## Phase 10: Review structured data

Check the rendered page.

Review:

- Organization entity
- LocalBusiness or subtype
- location identifiers
- address handling
- phone
- hours
- area served
- services
- breadcrumbs
- FAQs when appropriate
- review markup
- sameAs links
- factual match with visible content

Validate with approved tools.

Do not invent ratings, locations, services, or hours in markup.

Do not promise that schema will improve rankings.

## Phase 11: Review Search Console

Use exact dates and the correct property.

Review:

- page indexing
- sitemap processing
- URL Inspection for priority pages
- clicks
- impressions
- CTR
- average position
- query groups
- page groups
- device
- country
- search appearance
- branded and non-branded demand
- commercial and informational intent

Do not use Search Console average position as a universal exact rank.

Do not call Search Console clicks map pack clicks.

Do not diagnose a cause from one metric.

## Phase 12: Review performance and mobile access

Review available evidence for:

- Core Web Vitals
- mobile usability
- slow server response
- heavy scripts
- large media files
- layout movement
- delayed interaction
- blocked main content
- form failures
- click-to-call failures
- navigation failures
- consent or pop-up interference

Use field data when available. Lab tests are diagnostic and can vary.

Do not promise ranking changes from a performance score.

## Phase 13: Assign severity and priority

Severity:

- `critical`: blocks access, creates major policy risk, exposes private data, or breaks core conversion
- `high`: materially harms indexing, local identity, eligibility, or priority intent
- `medium`: weakens relevance, usability, internal discovery, or measurement
- `low`: limited impact or isolated cleanup
- `observation`: useful context without a required correction
- `test`: measurable hypothesis

Priority:

- `P0`: dangerous or blocking
- `P1`: high-value correction
- `P2`: important improvement
- `P3`: supporting improvement
- `P4`: optional measured test

Score each finding using:

- business impact
- visibility impact
- evidence strength
- confidence
- effort
- policy risk
- dependency
- reversibility

A numeric score may help order work. It must not be presented as a ranking forecast.

## Phase 14: Build the execution plan

Group work into:

### Stabilize

- eligibility
- wrong business facts
- index blocks
- broken conversion paths
- severe errors
- private information exposure

### Correct

- status codes
- canonicals
- redirects
- sitemap
- broken links
- duplicate targeting
- profile landing-page conflicts

### Strengthen

- page intent
- service coverage
- place coverage
- internal links
- proof
- blogs
- structured data
- conversion paths

### Test

- optional page experiments
- title changes
- consolidation tests
- measured service-area content
- optional crawler files

For each action, include:

- finding ID
- exact change
- affected URL
- owner
- approval
- dependency
- effort
- risk
- rollback
- verification
- expected customer value
- evidence class

## Phase 15: Produce the report

Use `templates/local-seo/local-website-audit-report.md`.

The report must separate:

- facts
- measured observations
- policy rules
- hypotheses
- recommendations
- approved work
- completed work
- verified work

Run the Universal Human Writing SOP before final delivery.

## Verification

After approved corrections:

- recrawl affected URLs
- retrieve live pages
- confirm status codes
- confirm canonicals
- confirm index directives
- confirm raw and rendered content
- test forms and phone links
- validate structured data
- confirm sitemap and robots.txt
- inspect Search Console when data becomes available
- record evidence
- mark results as verified only after confirmation

## Completion standard

The audit is complete when:

- scope and limitations are clear
- the URL inventory is reproducible
- priority pages were reviewed
- findings contain evidence
- page actions are assigned
- no page is removed from traffic alone
- local facts remain accurate
- recommendations have approval and verification requirements
- unsupported claims are removed
- the final report passed the Human Writing SOP
