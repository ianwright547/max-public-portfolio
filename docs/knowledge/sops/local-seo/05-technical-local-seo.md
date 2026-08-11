---
title: Technical Local SEO SOP
slug: technical-local-seo
knowledge_type: sop
version: "1.0.0"
status: proposed
owner: agency
---

# Technical Local SEO SOP

## Purpose

This SOP covers crawlability, indexability, status codes, sitemaps, robots.txt, canonicals, redirects, JavaScript visibility, internal technical checks, LocalBusiness structured data, and optional AI crawler files.

## Evidence rule

Technical success means the intended page and markup can be retrieved and verified.

A generated file, successful deployment, plugin setting, or API response is not enough by itself.

## Step 1: Confirm the target inventory

Record:

- canonical domain
- preferred protocol
- preferred host
- important pages
- location pages
- service pages
- blog pages
- pages that should not be indexed
- current sitemap locations
- current robots.txt
- known redirects
- platform
- deployment process
- rollback method

## Step 2: Check crawl access

For each important page:

- returns a valid response
- is not blocked unintentionally
- is not behind a login
- is linked from the site
- has readable text
- has a crawlable canonical
- is included in the intended sitemap
- does not depend on a failed resource
- can be tested with URL Inspection after publication

Robots.txt controls crawling, not guaranteed removal from the index. Use the correct index directive when a page should not appear.

Do not block resources Google needs to understand a page.

## Step 3: Check rendered and raw content

Google can process JavaScript, but rendering can add delay and failure points. Other crawlers may process less JavaScript.

For important local pages:

- inspect raw HTML
- inspect rendered HTML
- confirm the title, H1, main copy, links, canonical, and structured data
- confirm content remains available when optional scripts fail
- prefer server-rendered, pre-rendered, or otherwise reliably accessible main content when the current implementation hides important text
- do not claim that every JavaScript site is invisible
- do not claim that static HTML is always required

Treat crawler accessibility as a test result, not a platform stereotype.

## Step 4: Validate status codes

Expected behavior:

- live page: `200`
- permanent move: approved permanent redirect
- temporary move: approved temporary redirect
- removed page with no replacement: `404` or `410`
- server failure: correct `5xx`

Check for:

- soft 404 pages
- redirect chains
- redirect loops
- all unknown URLs returning `200`
- deleted pages returning a generic homepage
- broken internal links
- mixed protocol redirects
- inconsistent trailing slash behavior
- host duplication

Do not redirect every removed URL to the homepage.

## Step 5: Canonicals

Every indexable page should have a deliberate canonical.

Confirm:

- one preferred protocol and host
- self-referencing canonical on unique pages
- canonical points to an indexable `200` page
- sitemap uses canonical URLs
- internal links use canonical URLs
- redirects support the preferred version
- duplicate parameter and slash versions are controlled
- location pages do not canonicalize to another city when they are intended to rank independently

A canonical is a signal, not an absolute command.

## Step 6: XML sitemaps

A sitemap should:

- include canonical indexable URLs
- exclude redirects, errors, and noindex pages
- update when pages are added or removed
- use accurate last modification dates when possible
- remain accessible
- be submitted in Search Console
- be verified after deployment

A sitemap does not guarantee indexing.

## Step 7: Robots.txt and index directives

Check:

- robots.txt exists
- production does not inherit staging blocks
- important pages are not disallowed
- sitemap references are correct
- noindex is used deliberately
- canonical and noindex instructions do not conflict
- staging and test environments remain protected

Any change requires approval and a rollback plan.

## Step 8: Local structured data

### Main rule

Structured data must match visible, approved facts.

Use the most specific supported LocalBusiness subtype when appropriate.

Possible entities include:

- Organization
- LocalBusiness or a subtype
- WebSite
- BreadcrumbList
- Service
- FAQPage when the content and current eligibility rules support it

Not every schema.org type produces a Google rich result.

### Required controls

- stable `@id`
- correct name
- correct URL
- correct phone
- public address only when appropriate
- accurate hours
- accurate location
- accurate area served
- correct sameAs links
- image rights
- unique location entities for real separate locations
- visible content that supports the markup

### Service-area businesses

Do not expose a private address in public structured data when the address is intentionally hidden.

Use actual areaServed values. Do not add places solely for keywords.

### Ratings and reviews

Do not create `aggregateRating` or review markup from invented, copied, or unsupported reviews.

Check current Google eligibility before adding review markup. A valid schema.org property does not guarantee a search feature.

### Validation

Use:

- Google Rich Results Test
- Schema Markup Validator
- rendered page inspection
- URL Inspection
- a crawl or extraction tool for scale

Fix syntax errors and factual mismatches.

Structured data can help machines understand the page. It does not guarantee ranking or citation by an AI system.

## Step 9: Internal technical linking

Check:

- no orphan priority pages
- links render as crawlable anchors
- links point to canonical URLs
- breadcrumbs are accurate
- important pages are not hidden only behind search or forms
- broken links are fixed
- redirecting internal links are updated
- pagination and archives do not create traps

## Step 10: Removed and duplicate content

Before removing:

- check Search Console
- check analytics
- check backlinks
- check conversions
- check internal links
- identify replacement
- obtain approval

Use:

- merge and redirect when a better replacement exists
- preserve when the page still serves distinct intent
- remove with `404` or `410` when no replacement exists
- noindex when the page must remain available but should not appear in Search

Do not delete pages solely because a transcript or general rule says blogs are harmful.

## Step 11: Optional llms.txt

Treat `llms.txt` as experimental.

Rules:

- core crawling, indexing, content, structured data, and business accuracy come first
- do not claim a ranking benefit
- do not claim confirmed adoption by every AI platform
- use only approved public information
- keep it current
- do not expose private client information
- record it as an experiment

## Step 12: Technical verification

After a change:

- retrieve the live URL
- confirm status
- confirm canonical
- confirm index directive
- confirm raw and rendered content
- confirm structured data
- confirm internal links
- confirm sitemap
- test robots.txt
- inspect Search Console when data becomes available
- save evidence
- record any delay or uncertainty

## Completion standard

Technical work is complete when:

- the live result matches the approved change
- important content is accessible
- status codes are correct
- canonicals are consistent
- sitemaps and robots.txt are accurate
- structured data is valid and truthful
- no private address or invented fact is exposed
- evidence is stored
- no ranking guarantee was made
