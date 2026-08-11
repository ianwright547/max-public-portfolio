---
title: Client Onboarding
slug: client-onboarding
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - internal onboarding form
  - client creation
  - client profile updates
  - onboarding intakes
  - Slack setup
  - website-generation requests
  - SEO readiness
owner: agency
review_required: true
---

# Client Onboarding

## Purpose

This SOP defines how the agency creates a client, captures onboarding information, stores files, creates the client Slack channel, and determines when the client is ready for fulfillment.

The onboarding form is internal-facing. The agency owner or a team member completes it. Clients do not receive the form link in this workflow.

## Client creation

The agency may create a client manually from Max.

The minimum information required to create a client is:

- Business name
- Phone number

Max must assign a unique client ID and detect obvious duplicate clients.

When a possible duplicate is found, Max must show a warning containing the matching business name, existing client ID, creation date, and reason for the warning.

The agency owner may override the warning. An overridden duplicate must remain visibly distinguishable with a label such as `Business Name 2.0`, while the exact submitted business name remains preserved as the canonical historical value.

The agency may update the client profile later from the client profile page. Profile updates save immediately because the agency owner or team member is making the change. Updating a profile must not overwrite original onboarding history.

## Internal onboarding form

The form is completed by the agency owner or an authorized team member.

The form may capture:

- Business name
- Phone number
- Email
- Website and domain
- Brand colors
- Logo and other assets
- Photos and videos
- Business hours
- Service areas
- Google Business Profile reference
- Enabled workflows
- Additional notes

The domain is required whenever a website is being generated or connected. It must be captured as its own field rather than inferred from free-form notes.

The minimum form submission must contain enough information to identify the client and contact them. At minimum, business name and phone number are required.

The form may be submitted without every optional field. Missing optional information should be recorded and shown for follow-up rather than silently invented.

## Files and assets

The form may include image and video uploads, along with PDFs, documents, screenshots, brand guides, spreadsheets, and website exports.

Files are saved under the correct client record and remain available as historical onboarding assets.

Files must not be copied to another client's record.

The system should not silently discard a submitted file. Files may be converted into a usable format later when needed. Unsafe files should not be used until cleared.

## New intake versus profile update

A new onboarding form submission creates a new client when the agency is onboarding a new business.

Updates to an existing client are made from that client's profile rather than creating a new client accidentally.

Original intake submissions remain preserved. A profile update may create a new profile version, but it must not rewrite the original intake.

## Slack channel creation

When an onboarding form is submitted, Max creates or connects the client's Slack channel.

The first Slack message includes:

- Client name
- Intake status
- Submitted information summary
- Missing information
- Conflicting information
- Available next actions
- Link to the Max record

The Slack channel is the working conversation for that client. Questions may be asked in the client conversation by mentioning `@max`. Max should answer or perform a clear, low-risk task immediately when the client and requested action are known.

Max should use the client context and the message thread to understand which client the question concerns.

A general public agency channel named `Max` should be available for questions that do not belong to one client. Max must ask for or identify the client before attaching a client-specific answer or action.

Client channels remain public within the Slack workspace.

Slack questions and answers that affect onboarding must be saved in Max and connected to the correct client or intake.

## Website-generation request

The client profile should provide an explicit action such as:

```text
Submit and generate website
```

The same action may be available from both the onboarding form and the client profile after the required client information is present.

Selecting the action creates a website-generation request with the client context. It must not silently use another client's information.

Website generation should use the approved client facts, uploaded assets, applicable website skills, and required SEO information.

For the current workflow, Max creates a Codex work packet. The packet must instruct Codex to:

- Use the future approved 1:1 website-generation skill.
- Use the approved SEO fundamentals skill.
- Read the client's approved facts, domain, assets, and existing website context.
- Preserve required keywords, headings, and factual business information.
- Build the requested website in the connected repository.
- Run the required checks.
- Publish to the correct Vercel project.
- Verify that the domain belongs to the same client before pointing or configuring it.
- Return changed files, test results, deployment information, and evidence.

The packet must include the domain as a required field and must never contain credentials.

## SEO readiness

SEO work may begin when at least one of the following is connected to the client:

- A verified website
- A verified Google Business Profile

If neither is connected, Max should identify the missing connection and avoid claiming that SEO work has started.

## Publishing

The agency has chosen to allow a website to be published to Vercel immediately when the requested workflow permits it.

This does not remove the approval rules from the Agency Operating Principles SOP. Major, high-risk, form, or otherwise approval-required changes must still follow that SOP.

The publication result, target project, client, files, tests, and timestamp must be recorded.

## Onboarding statuses

Recommended statuses:

```text
received
processing
needs_information
ready_for_review
approved
rejected
complete
```

`approved` means the onboarding information has been approved and the client is ready for fulfillment.

`complete` means the approved onboarding work is recorded and the client has entered the fulfillment workflow.

The normal transition is:

```text
received → processing → approved → complete
```

If required information is missing, Max should notify Slack and ask for the next step. Low-risk work may continue when the missing information does not affect cost, safety, client identity, or the requested outcome. Major work remains blocked until the required information is available.

## Safety rules

- Every intake belongs to exactly one client.
- Every uploaded file belongs to exactly one client.
- A new-client form must not accidentally update an existing client.
- An existing-client update must not create a duplicate client.
- Original onboarding information remains unchanged.
- Missing information is shown instead of invented.
- Conflicting information is shown instead of silently selected.
- Slack messages must identify the client clearly.
- A general-channel question must not be attached to a client until the client is known.
- Website generation must use the selected client's approved context.
- SEO status must reflect whether a website or Google Business Profile is actually connected.

## Final checklist

Before accepting an onboarding submission, Max should confirm:

- Is this a new client or an existing-client update?
- Is the business name present?
- Is the phone number present?
- Is the client ID correct?
- Are uploaded files attached to the correct client?
- Were missing fields recorded?
- Were conflicts recorded?
- Was the client Slack channel created or found?
- Is website generation requested?
- Is a website or Google Business Profile connected for SEO work?
- Was the status saved?
