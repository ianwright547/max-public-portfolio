---
title: Website Changes and Publishing
slug: website-changes-and-publishing
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - website edits
  - content updates
  - SEO changes
  - form changes
  - GitHub changes
  - Vercel publishing
owner: agency
review_required: true
---

# Website Changes and Publishing

## Purpose

This SOP defines how Max safely edits and publishes an existing client website while preserving the approved design system and historical records.

## Small changes

Small, reversible changes may proceed automatically when the workflow is enabled and the task permits them:

- Typo corrections
- Broken-link fixes
- Metadata corrections
- Sitemap updates
- Image compression
- Accessibility labels
- Simple spacing corrections
- Minor mobile-layout fixes
- Routine technical corrections

Small changes must still be connected to the correct client and recorded.

## Major changes

Major changes require approval before execution:

- Major layout changes
- Navigation changes
- URL changes
- Branding or design-system changes
- Primary-content changes
- Changes affecting many pages
- High-risk technical changes
- Changes affecting external systems

Every website form change requires approval.

## Design preservation

During normal website edits, preserve the Demo Reference Client design system:

- Fonts
- Layout
- Spacing
- Components
- Navigation
- Buttons
- Page structure
- Responsive behavior

Colors, content, assets, services, locations, keywords, and calls to action may change when included in the approved request.

A design-system change requires an explicitly approved design task.

## Content and keyword changes

Max may write reasonable content based on approved client information and manage the website's keyword strategy.

Do not use placeholders unless explicitly requested.

Do not invent specific client facts, testimonials, reviews, prices, rankings, results, certifications, or guarantees.

Existing H1s, H2s, titles, and metadata should remain unless the approved task changes them.

## Approval and execution

Approval authorizes execution. Once the agency owner or authorized team member approves the task, no second publish confirmation is required.

Max may still stop for:

- Client mismatch
- Repository mismatch
- Vercel-project mismatch
- Domain mismatch
- Missing required access
- Unresolved dependency
- Safety violation

The agency owner and authorized team members have final authority over whether approved work proceeds.

## Repository scope

Codex must inspect the repository before editing.

The task packet must define:

- Allowed files or directories
- Protected files or directories
- New files permitted
- Tests required
- Publishing state

Codex must not modify unrelated files or delete files without explicit approval.

Unexpected project structure or unexpected client information requires an immediate stop and report.

## Testing and deployment

Run relevant tests before and after changes.

For major changes, pre-existing test failures block execution. For small unrelated changes, a baseline failure may be recorded and the task may continue.

Before publishing, verify:

- Correct client
- Correct GitHub repository
- Correct branch
- Correct Vercel project
- Correct domain
- Tests pass
- No unexpected files changed

Codex must not change DNS records. DNS requirements are reported to the agency owner.

## Deployment failures

Temporary failures may be retried using the existing retry policy.

After the retry limit:

1. Preserve the failure.
2. Mark the task blocked or failed.
3. Notify Slack.
4. Ask for next steps.

Automatic rollback is not allowed unless an approved rollback procedure exists.

## Completion and verification

Deployment success means the requested deployment completed. It does not prove that the output is correct.

Verification must confirm:

- Requested changes exist
- Correct client was affected
- Design style remains correct
- Content and colors match the approved request
- SEO requirements pass
- Mobile and desktop behavior were checked
- Tests passed
- Evidence exists
- No unexpected systems or files changed

Only verified work may resolve a finding or appear as verified completed work in reports.

## Failure limits

- Major work stops after two permanent failures.
- Small work stops after three permanent failures.
- Temporary failures use retries before counting as permanent.

When the limit is reached, Max blocks the task, notifies Slack, and asks for next steps.

## History

Every website change must preserve:

- Original request
- Approval record
- Packet version
- Files changed
- Tests
- Deployment result
- Evidence
- Verification result
- Rejected or failed attempts

Do not silently replace a previous request, result, or version.

## Final checklist

- Is the change small or major?
- Is approval required and recorded?
- Is the client correct?
- Is the repository correct?
- Is the Vercel project correct?
- Is the domain correct?
- Is the Demo Reference Client design system preserved?
- Are colors and content changed only as requested?
- Are placeholders absent unless requested?
- Are keywords relevant and natural?
- Did tests pass?
- Were unexpected files avoided?
- Is publishing allowed?
- Is deployment evidence saved?
- Is verification complete?

