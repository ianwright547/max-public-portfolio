---
title: Official Client Profile
slug: official-client-profile
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - official client profiles
  - profile updates
  - client facts
  - client preferences
  - website generation
  - SEO workflows
  - reporting
  - Slack communication
owner: agency
review_required: true
---

# Official Client Profile

## Purpose

The official client profile is Max's trusted working record for one client. It gives website, SEO, fulfillment, reporting, and Slack workflows a single client-specific source of context.

The profile must remain easy to update while preserving every previous version and the original onboarding information.

## Profile sections

Every official profile may contain:

- Business information
- Contact information
- Services
- Service areas
- Business hours
- Website and domain
- Brand information
- Google Business Profile information
- SEO information
- Workflow settings
- Client assets
- Pricing information
- Client goals
- Competitors
- Internal notes

Internal notes are not included in client-facing reports or other client-facing output.

## Facts, observations, and preferences

Max must distinguish different kinds of profile information.

### Verified information

Verified information may come from:

- The agency owner
- An authorized team member
- A connected source that Max can inspect
- A visible value observed on the client's website or Google Business Profile
- A verified imported document

Examples include the business phone number supplied by the owner and the number of reviews visibly shown on a connected profile.

Max must record the source and time for important verified information.

### Client preferences

Preferences describe how the client wants work performed or presented.

Examples include:

- Preferred writing tone
- Preferred design style
- Preferred colors
- Preferred call-to-action style
- Preference for short or detailed reports

Max may infer a possible preference from approved examples, but an inferred preference must be labeled as inferred until the agency confirms it. An inferred preference must not override a verified fact or safety rule.

### Interpretations

AI interpretations may help organize the profile, but they are not official facts until confirmed by the agency or a verified source.

## Sources

Important profile fields should show their source, such as:

- Original intake
- Agency owner update
- Team-member update
- Connected website
- Google Business Profile
- Imported document
- AI interpretation
- Manual observation

Source labels must be preserved when the profile is used in prompts, Slack, reports, or tasks.

## Updating the profile

The agency owner or an authorized team member may update the profile directly. Profile updates save immediately.

Every update must still create a historical profile version containing:

- Previous value
- New value
- Field changed
- Person or system that changed it
- Reason, when available
- Timestamp
- Source

The update must never rewrite the original intake or delete a previous profile version.

## Fields requiring additional checks

Max should warn before changing:

- Business name
- Domain
- Phone number
- Email
- Service areas
- Services
- Brand colors
- Google Business Profile reference
- Workflow settings

Changing the business name triggers a duplicate-client check.

Changing the domain requires verification that the domain belongs to the same client.

Changing the phone number or email should request confirmation when the change could affect contact, reporting, or external access.

## Conflicting information

When a new value conflicts with the official profile, Max should save the new value as a clearly marked conflict or proposed replacement rather than silently hiding either value.

Max should use judgment based on risk:

- Low-risk information: preserve both values, label the conflict, and continue safe work.
- Identity, domain, access, legal, or publishing information: stop the affected workflow and request clarification.
- Client-facing claims: do not publish until the conflict is resolved.

Conflicts should not automatically block every unrelated workflow, but they must block work that depends on the disputed field.

If a live website or connected profile disagrees with the official profile, Max should show both values and identify the source. It should not silently decide that the live value is correct. The agency owner or team member can resolve the conflict.

## Profile versions

The current official version and previous versions remain visible in Max.

Each version should show:

- Version number
- Creation time
- Person or system responsible
- Changed fields
- Source information
- Reason for change

Max should not delete or overwrite an old version.

The agency may use an older version as the starting point for a new update. Restoring an older version creates a new current version rather than erasing the intervening history.

## Visibility rules

Profile information may appear in Slack, internal reports, and client reports according to sensitivity and audience.

- Internal notes: internal Max and authorized internal Slack only.
- Verified business facts: may appear in appropriate client-facing output.
- Preferences: may guide writing and design but should not be presented as factual claims.
- Credentials and secrets: never appear in profiles, Slack, prompts, or reports.
- Source labels: remain available internally and are included when needed to support a claim.

Client assets should be accessible from the profile when the viewer has permission to view that client.

## Workflow settings

Workflow settings may be managed per client for:

- Website generation
- Website publishing
- SEO work
- Google Business Profile work
- Weekly blogs
- Google Business Profile posts
- Health checks
- Metric collection
- Reports
- Slack notifications

Disabling a workflow stops related automatic work and task creation. Existing history remains visible.

If a disabled workflow is requested manually, Max should explain that it is disabled and ask whether the agency owner wants to enable it.

Workflow-setting changes are saved in profile history.

## Profile readiness

An official profile should contain, at minimum:

- Business name
- Phone number
- Service start date
- At least one verified contact method
- Approved service information
- Client ID
- No unresolved client-identity conflict

Optional information may be missing without preventing the profile from becoming official. Missing optional information should remain visible as a follow-up item.

Recommended profile statuses are:

```text
incomplete
ready_for_review
official
needs_update
archived
```

Archived client profiles remain readable and continue to preserve history.

## Slack notification

Max should notify Slack when an important official profile change occurs, provided the notification does not trigger unnecessary AI processing or meaningful extra cost.

The message should identify:

- Client
- Field changed
- Old and new values when safe to show
- Person or system that changed it
- Source
- Next action, if needed

## Final checklist

Before using a profile in a consequential workflow, Max should confirm:

- Is the client ID correct?
- Is the current official profile version being used?
- Are facts separated from preferences and interpretations?
- Are important sources recorded?
- Are there unresolved conflicts affecting this task?
- Is the domain verified for website work?
- Are workflow settings enabled?
- Are internal notes excluded from client-facing output?
- Are previous versions preserved?

