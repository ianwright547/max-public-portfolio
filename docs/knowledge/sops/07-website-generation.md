---
title: Website Generation
slug: website-generation
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - new websites
  - 1:1 website builds
  - website content
  - local SEO
  - GitHub projects
  - Vercel deployments
owner: agency
review_required: true
---

# Website Generation

## Purpose

This SOP defines how Max creates a client website using the approved Demo Reference Client design system, client-specific information, Local SEO knowledge, GitHub files, and Vercel deployment.

The design system stays consistent. Client content, colors, assets, services, locations, keywords, and calls to action change for each client.

## Required inputs

Before generation, Max should have:

- Correct client ID
- Approved client profile
- Business name
- Phone number
- Service information
- Service areas when applicable
- Domain
- GitHub repository
- Vercel project
- Approved client assets when available
- Website mode
- Requested outcome

Missing optional information should not automatically stop the build. Missing identity, domain, repository, project, or required service information must stop the affected workflow.

## Website modes

- `new_build`: create a website using the approved design system.
- `replicate`: preserve Demo Reference Client design system while replacing client-specific information.
- `improve`: preserve the design system while making approved structural or conversion improvements.
- `repair`: fix a defined issue without changing unrelated components.

## Demo Reference Client design system

Demo Reference Client is the approved reference for the design style.

The build must preserve unless the task explicitly authorizes a design change:

- Font family and type scale
- Layout system
- Page width
- Spacing system
- Header and footer structure
- Navigation behavior
- Button style
- Card style
- Section order
- Component structure
- Image treatment
- Responsive behavior
- Mobile layout
- Overall visual rhythm

The following may change for the new client:

- Business name
- Phone and email
- Domain
- Services
- Service areas
- Business facts
- Brand colors
- Logo
- Photos and videos
- SEO keywords
- Calls to action
- Page-specific copy

## Pages

The default site includes:

- Home
- About
- Services
- Service Areas
- Contact
- Blog when enabled

Max may create additional service, location, or informational pages when they are supported by approved client services, useful search intent, or a clear business goal.

Max must not create thin duplicate location pages that only replace a city name.

## Content rules

Max may write useful general content based on approved services, audiences, and locations.

Do not use placeholders unless the agency owner explicitly requests them.

Do not leave generic AI commentary in the website.

Max must not invent:

- Reviews or testimonials
- Prices
- Awards
- Certifications
- Rankings
- Customer counts
- Results
- Guarantees
- Years in business
- Partnerships
- Specific business history

If an important fact is missing, omit the specific claim or ask for the fact. Use a reasonable general explanation only when it does not imply an unsupported client-specific fact.

## Keyword management

Max owns the keyword system for the website.

It should research, select, organize, and apply:

- Primary keywords
- Secondary keywords
- Service keywords
- Location keywords
- Supporting topic keywords

Keywords must match the client's actual services and locations. Max may select new relevant keywords as part of routine SEO planning. It must not force an inaccurate keyword into the website.

Keyword use must remain natural. Do not keyword-stuff, hide keywords, or create misleading pages.

## SEO fundamentals

Every website build should address when applicable:

- One clear H1 per page
- Logical H2 structure
- Page titles
- Meta descriptions
- Internal links
- Image alt text
- Local business information
- Service-area accuracy
- Structured data
- Sitemap behavior
- Mobile usability
- Accessibility
- Performance basics

Use the relevant Local SEO skills, SOPs, templates, and publication checklist.

## Assets

Use approved client images, videos, logos, and brand files first.

If an important asset is missing, stop and ask. For a minor asset, use the closest approved replacement and record it. Do not claim that a replacement is a client-owned asset.

## Codex and repository workflow

Website generation uses the Codex Work Packet SOP.

The packet must include:

- Client facts needed for the task
- Demo Reference Client design reference
- Keyword and SEO requirements
- GitHub repository and branch
- Vercel project
- Domain
- Allowed and prohibited files
- Tests
- Publishing state
- Expected final response

Codex must inspect the repository before editing and must stop on a client, repository, Vercel, or domain mismatch.

## Publishing

Approved work may publish without another confirmation when:

- The correct client is verified.
- The repository is correct.
- The Vercel project is correct.
- The domain is correct.
- Tests pass.
- No unexpected files changed.
- Publishing is allowed in the task packet.

Codex must not change DNS records. DNS requirements are reported to the agency owner.

## Verification

Completion means the website was built and deployed. Verification requires evidence confirming:

- Correct client
- Correct repository
- Correct Vercel project
- Correct domain
- Requested content exists
- Design system was preserved
- SEO checks passed
- Mobile and desktop checks were completed
- No unexpected files changed
- Deployment evidence exists

Website completion does not automatically resolve a health finding.

## Final checklist

- Is the client correct?
- Is the domain present and verified?
- Is the repository connected?
- Is the Vercel project connected?
- Is the Demo Reference Client design system preserved?
- Are colors and content correctly changed for this client?
- Are keywords relevant and natural?
- Are unsupported claims absent?
- Are placeholders absent unless requested?
- Are tests and visual checks complete?
- Is publishing authorized?
- Is deployment evidence saved?

