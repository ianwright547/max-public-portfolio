---
title: Google Business Profile Workflow
slug: google-business-profile
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - Google Business Profile connections
  - profile optimization
  - scheduled posts
  - review responses
  - profile metrics
owner: agency
review_required: true
---

# Google Business Profile Workflow

## Purpose

This SOP defines how Max reads, drafts, validates, and updates Google Business Profile information and posts.

The workflow should be mostly hands-off for enabled clients while keeping profile edits, access changes, and client identity protected.

## Connection requirement

Each client connection stores:

- Client ID
- Google account or resource ID
- Location ID
- Business name
- Domain
- Verification status
- Permission status
- Connection status
- Last successful synchronization
- Last error

Before reading or changing a profile, Max must verify that the location belongs to the same client and domain.

If no live Google Business Profile API connection is linked to Max, skip that client's scheduled workflow. Record `skipped_no_live_connection` without creating unnecessary AI work or a failed task.

## Read data

When connected, Max may read:

- Business name
- Address or service area
- Phone
- Website
- Hours
- Categories
- Services
- Attributes
- Photos
- Posts
- Reviews
- Rating
- Profile metrics when available

Live data is labeled `live`. Manual, mock, and imported information must retain their own labels.

## Read-only inspection

Before recommending GBP changes, Max may inspect the connected location through
the Business Information API and retrieve aggregate review metrics. Inspection
records the location identity, categories, hours availability, service-area
presence, open state, review count, and average rating. Review text is not
persisted in Max. Authorization failures, an unverified location, and provider
outages remain explicit blockers in the client update and report.

## Approval rules

The following always require approval before changing:

- Business description
- Categories
- Services
- Hours
- Phone
- Website
- Service areas
- Attributes
- Photos
- Ownership
- Permissions
- Account settings

Weekly posts are a separate pre-approved workflow. When the client enables scheduled posts, a validated Monday post may publish automatically without another Slack approval.

The agency owner and authorized team members have final authority.

## Weekly post schedule

For every client with the scheduled-post workflow enabled and a verified live connection:

1. Run every Monday at the configured agency-wide time.
2. Default time: 9:00 AM America/Chicago.
3. Create the post content.
4. Select or create an eligible visual.
5. Run factual, SEO, and policy checks.
6. Check recent post history for duplicates.
7. Publish automatically when all checks pass.
8. Record the live result.

Clients without a live connection are skipped quietly and recorded as skipped.

## Post content

Routine posts use DeepSeek Flash. OpenAI Terra may be used for difficult strategy or conflicting information.

Each post should include:

- Topic
- Copy
- Relevant service
- Location relevance when supported
- Call to action
- Source facts
- Scheduled period
- Validation result

Max must not invent:

- Phone numbers
- Prices
- Promotions
- Offers
- Reviews
- Results
- Locations
- Certifications
- Rankings
- Guarantees
- Business history

“Halal” for this workflow means honest and non-deceptive content with no fabricated facts, numbers, people, offers, or results. Additional client-specific faith or industry requirements are stored as client preferences.

## Visuals

Use images already present on the connected Google Business Profile first, then approved client assets.

If no suitable image exists, Max may create a simple non-photorealistic, Canva-style flyer using approved facts, colors, logo, and assets.

This is a design style, not a Canva integration.

Visuals must:

- Contain no people or human figures.
- Contain no invented phone numbers, prices, offers, or claims.
- Use approved client brand elements.
- Avoid photorealistic AI people.

If no suitable visual can be created, publish text-only when the platform permits it. Do not use placeholders unless explicitly requested.

## Duplicate prevention

Max must prevent duplicate posts using a key based on:

- Client
- Scheduled Monday period
- Content fingerprint

Previous posts and failed attempts remain visible.

## Profile optimization

Max may recommend improvements to descriptions, categories, services, hours, service areas, attributes, photos, and website links.

Recommendations create proposals. Profile changes require approval before publishing.

## Reviews

Max may draft review responses. Review responses require approval before publishing unless a separate approved workflow is created later.

Max must never create fake reviews, encourage fake reviews, use review gating, or offer prohibited incentives.

## Permissions and errors

Minimum required permissions should be used.

If authorization expires:

- Mark the connection expired.
- Stop changes.
- Notify Slack.

If permission is missing:

- Mark missing access.
- Skip the affected action.
- Notify Slack when agency action is needed.

Rate limits, network failures, and temporary Google outages may retry using the existing retry policy. After the limit, preserve the failure and notify Slack when needed.

## Conflicts and mismatches

If phone, hours, domain, business name, service, or location conflicts with Max's official profile, skip the affected post or change and notify Slack for clarification.

If the Google location or domain may belong to another client, stop immediately.

## History and reporting

Save:

- Draft content
- Image source
- Source facts
- Validation results
- Scheduled period
- Publication result
- Live post reference
- Errors
- Previous versions

Reports must label Google Business Profile information as live only when it came from the verified live connection.

## Final checklist

- Live connection present?
- Correct client and location?
- Domain verified?
- Workflow enabled?
- Monday schedule and time correct?
- Content factual and honest?
- No invented numbers or offers?
- No people in the visual?
- Existing profile image used when suitable?
- Flyer uses approved brand elements?
- Duplicate post prevented?
- Profile edits separated from post automation?
- Publication result saved?
