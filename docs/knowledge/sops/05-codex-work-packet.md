---
title: Codex Work Packet
slug: codex-work-packet
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - website generation
  - website edits
  - SEO pages
  - blog content
  - Google Business Profile drafts
  - technical SEO
  - GitHub work
  - Vercel deployment
owner: agency
review_required: true
---

# Codex Work Packet

## Purpose

This SOP defines how Max creates a complete task packet for Codex.

The packet is designed to be copied into a Codex conversation from any device. Codex uses the connected GitHub repository as the source of project files and returns its work for Max to record and verify.

The packet itself should not require Max to make another OpenAI API request. The packet provides context and instructions; Codex performs the repository work through its authorized connection.

## Client repository requirement

Every client must have GitHub-backed project files so the agency can access the work from any device.

Max must store:

- Client ID
- GitHub owner or organization
- Repository name
- Repository URL
- Default branch
- Task branch when created
- Connected Vercel project ID
- Production domain

If the repository or connection is missing, the packet must stop and explain what is needed.

## Packet creation

Max may create a packet:

- Automatically after a task is approved.
- Manually from the client profile.

The packet must contain a unique:

- Packet ID
- Client ID
- Task ID
- Operation key

A packet marked `proposed` cannot authorize work. A packet may authorize work only when its approval state and task state allow it.

Packets expire after seven days unless regenerated.

When an eligible website or SEO task is approved and verified GitHub and website
connections already exist, Max may prepare the packet automatically. Automatic
preparation does not start work, spend model credits, authorize publishing, or
change task status beyond the recorded approval.

## Handoff lifecycle

1. `generated`: the packet can be reviewed and copied, but no work is running.
2. `handed_off`: a named actor confirms the packet was placed into an authorized
   Codex session; the task moves through ready to running after dependency checks.
3. `completed`, `blocked`, or `failed`: Max accepts a structured result containing
   summary, changed files, tests, commits, deployment evidence, blockers, and cost.
4. A completed result creates a non-simulated fulfillment execution but does not
   become verified work until the existing independent verification decision passes.

Returned changed files must remain inside the packet's allowed paths and outside
every prohibited path. A completed result cannot contain a failed test. Blocked
results must state at least one concrete blocker. Credential-like content is rejected.

## Required packet sections

Every packet should include:

1. Task summary
2. Exact requested outcome
3. Client identity
4. Approved client facts required for the task
5. Relevant source labels
6. GitHub repository and branch
7. Vercel project and domain
8. Applicable skills and SOPs
9. Files or directories allowed to change
10. Files or directories that must not change
11. SEO requirements
12. Design requirements
13. Acceptance criteria
14. Tests and checks
15. Cost guidance
16. Approval and publishing state
17. Required final response format

For specialized local SEO work, the packet also includes a work-type acceptance
contract. A completed result must return structured `verification_data`:

- Technical SEO: named checks for indexability/robots, canonicals and status
  codes, sitemap/schema effects when relevant, plus actual test or build output.
- Local service/location page: the exact page path or URL, source of approved
  facts, and confirmation that the page is a real supported intent rather than a
  thin city-swapped doorway page.
- Google Business Profile: connected location, confirmed business facts,
  approval state, and a provider post ID when (and only when) the post was
  actually published.

Max rejects a completed result when these required fields are missing, contain
failed technical checks, or claim GBP publication without provider evidence.

For `local_page` and `blog` packets, a completed Codex result also requires a
separate human content review before independent execution verification. The
review is recorded at `/codex-work-packets/{packet_id}/content-review` or
through the mapped Slack command `approve content review packet PACKET_ID
{JSON}`. It checks approved facts, intent match, human-writing quality,
unsupported or doorway claims, and links/CTA quality. A completed file result
without this review is not verified client work.

The packet should include only task-relevant client information. Internal notes, credentials, tokens, passwords, and private authorization details must never be included.

## Client separation and mismatch protection

The packet must explicitly instruct Codex:

> Use only this client's approved information, repository, domain, assets, and Vercel project. Do not use another client's files, facts, domain, repository, or deployment project.

Codex must stop and report immediately if:

- The repository does not match the client.
- The Vercel project does not match the client.
- The domain does not match the client.
- The expected files are missing.
- The project contains an unexpected client identity.

## Demo Reference Client design reference

Demo Reference Client is the approved reference for the Max 1:1 website design system.

For a 1:1 website task, the packet must instruct Codex to preserve the design style, including:

- Font family and type scale
- Layout system
- Page width
- Spacing system
- Header structure
- Footer structure
- Navigation behavior
- Button style
- Card style
- Section structure
- Component structure
- Image treatment
- Responsive behavior
- Mobile layout
- Overall visual rhythm

The design system is what stays consistent. Client-specific content and branding are what change.

Codex should replace or adapt:

- Business name
- Phone number
- Email
- Domain
- Services
- Service areas
- Business facts
- Brand colors
- Logo
- Photos and videos
- SEO keywords
- Calls to action
- Page-specific content

The packet must not ask Codex to redesign the reference system unless the task explicitly authorizes a design change.

## Website modes

Packets may use one of these modes:

- `new_build`: build a new site using the approved design system.
- `replicate`: preserve the Demo Reference Client design system while swapping client content and branding.
- `improve`: preserve the design system while making approved structural or conversion improvements.
- `repair`: fix a defined issue without changing unrelated components.

Missing important fonts, logos, or reference assets require a question or blocker. Minor missing assets may use the closest approved replacement and must be reported.

## SEO requirements

Every website packet includes the approved SEO fundamentals skill and relevant local SEO knowledge.

Codex must preserve or create, when required by the task:

- Correct H1 and H2 structure
- Page titles
- Meta descriptions
- Service keywords
- Service-area keywords
- Internal links
- Image alt text
- Local business information
- Relevant structured data
- Sitemap behavior
- Mobile and accessibility requirements

Codex must not invent services, locations, reviews, results, rankings, credentials, or other client facts.

## Files and repository scope

Codex must inspect the repository before editing.

The packet must list:

- Allowed files or directories
- Files or directories that must not change
- New files that may be created
- Tests or commands to run

Codex may create new files when required. Codex must not delete files without explicit approval.

If the project structure is unexpected or important files are missing, Codex must stop and report instead of guessing.

## Publishing rules

Codex may publish to Vercel only when the packet contains:

```text
approved: true
publish_allowed: true
```

Before publishing, Codex must confirm:

- Correct client
- Correct repository
- Correct Vercel project
- Correct domain
- Required tests pass
- No unexpected files changed
- No unresolved client mismatch

Codex must not change DNS records. If DNS work is needed, it must report the exact action required.

Once the team or agency owner approves the work and the packet says publishing is allowed, no second publish confirmation is required. Approval is the authorization to proceed.

Max may still stop the work for a client mismatch, missing required access, unresolved dependency, or safety violation. The team and agency owner have final authority over whether approved work proceeds.

Temporary deployment failures may be retried. After the retry limit, Codex must report the failure. Automatic rollback is not allowed unless an approved rollback instruction exists.

## Tests and verification

Codex must run relevant existing tests before editing and again after editing.

For major work, pre-existing test failures block the task. For small work, an unrelated baseline failure may be recorded and the task may continue.

1:1 website work requires visual comparison against the Demo Reference Client reference and a report of anything that could not be verified.

The final response must include:

- Changed files
- Created files
- Tests run
- Test results
- Build result
- Deployment result
- Deployment URL
- Screenshots or visual evidence when applicable
- SEO checks
- Accessibility checks
- Mobile and desktop checks
- Unexpected changes
- Known limitations
- Acceptance checks: one entry for every packet acceptance criterion, each marked
  passed or failed with the evidence that supports it

## Model and cost guidance

The packet should recommend:

- Strongest model: 1:1 design implementation, major changes, complex SEO strategy, and high-risk work.
- Efficient model: routine content swapping, metadata, simple blogs, formatting, summaries, and small fixes.

The packet should include an estimated budget and tell Codex to stop and report if the work is likely to exceed it.

The packet should tell Codex to inspect only relevant files, reuse existing components, and avoid resending irrelevant project context.

For `local_page` and `blog` work, Max also includes an evidence-backed content
brief. It identifies the task/finding intent, approved-fact source, any saved
Search Console query opportunities, a bounded outline, page requirements, and
prohibited claims. Codex must not turn the brief into invented services,
locations, reviews, credentials, guarantees, or city-swapped doorway pages.

## Final response format

Codex must return:

```text
Status
Client
Task
Repository
Branch
Files changed
Files created
Tests run
Tests passed
Build result
Deployment result
Deployment URL
Evidence
Acceptance checks (criterion, status, evidence)
Unexpected changes
Known limitations
Recommended next step
```

Max saves the response as execution evidence. The agency owner may paste the result back into Max for verification.

Max may create a short Slack update from the verified result.

## Final checklist

- Is the packet approved?
- Is the client identity correct?
- Is the GitHub repository connected?
- Is the correct branch identified?
- Is the Vercel project connected?
- Is the domain verified?
- Is the Demo Reference Client design reference included for 1:1 work?
- Are client content and colors clearly separated from the preserved design system?
- Are SEO requirements included?
- Are allowed and prohibited files listed?
- Are credentials excluded?
- Is publishing explicitly allowed?
- Are tests and verification requirements included?
- Is the packet within its expiration period?
