# Max Knowledge System — AI Handoff Context

## Purpose of this document

This document gives another AI enough context to help design Max's knowledge, SOP, skill, prompt, and learning system.

It intentionally does **not** define the SOPs themselves. The user will provide separate instructions about which SOPs to create and how they should be written.

## Product identity

Max is an internal agency operating system for managing client onboarding, fulfillment, SEO, websites, health checks, reporting, and approvals.

The primary user is the agency owner. Max is intended to help one agency manage many clients while keeping the owner in control of important decisions.

Max should make repetitive work faster without hiding what happened or inventing results.

## Core product principle

Slack is the communication and approval interface.

Max is the system of record.

External services provide data or execution.

AI proposes interpretations, plans, prompts, explanations, and drafts.

Human approval is required before consequential external changes.

Every important action, decision, result, failure, and verification must be recorded in Max.

## Intended end-to-end workflow

```text
Client form submitted
        ↓
Original intake stored permanently
        ↓
AI interprets intake into a proposed profile
        ↓
Missing and conflicting information is shown
        ↓
Slack review and questions
        ↓
Human approval or requested corrections
        ↓
Fulfillment plan generated
        ↓
Tasks and dependencies reviewed
        ↓
Approved tasks execute safely
        ↓
Execution results and evidence recorded
        ↓
Human verification
        ↓
Finding resolution, if verification succeeds
        ↓
Metrics and reports generated
        ↓
Weekly or monthly workflows continue
```

## Current product capabilities

Max currently has an existing FastAPI and SQLAlchemy backend with SQLite for local development and PostgreSQL-compatible production support.

Implemented areas include:

- Client creation, retrieval, update, and archive
- Immutable onboarding intakes
- Multiple intake versions per client
- Fake onboarding interpretation service
- Optional replaceable OpenAI interpretation adapter
- Proposed and official client profiles
- Human approval and rejection of proposed profiles
- Metric snapshots, baselines, and history
- Manual, mock, imported, and live-labeled data sources
- Website connections and website metrics
- Rules-based health checks and findings
- Task proposals and task approval
- Safe fulfillment simulator
- Execution retries, costs, evidence, and idempotency
- Verification and finding-resolution workflow
- Internal and client-facing HTML reports
- Internal notifications
- Slack client channels and notification delivery
- Scheduled jobs for health checks and metric synchronization
- Database-aware health endpoint
- Security headers
- Append-only audit events
- Downloadable HTML reports
- Durable automatic onboarding runs and safe backfill for existing clients
- Automatic public Slack channel creation after intake submission
- Read-only Vercel project and GitHub App repository discovery
- Exact-domain provider matching with human review for ambiguous matches
- Persisted website analytics tracker mappings
- Automatic fulfillment-task proposals after profile approval

## Current architecture

```text
app/
├── main.py                  # FastAPI application and route registration
├── models.py                # SQLAlchemy database models
├── schemas.py               # API request and response schemas
├── database.py              # Database engine and session setup
├── routes/                  # HTTP endpoints and dashboard pages
├── interpretation_service.py# Fake onboarding interpretation
├── openai_service.py        # Optional replaceable OpenAI adapter
├── slack_service.py         # Slack adapter and delivery logic
├── job_service.py           # Scheduled-job execution
├── task_rules.py            # Task state and transition rules
├── health_rules.py          # Explainable health-check rules
├── verification_rules.py    # Verification and resolution rules
├── report_builder.py        # Immutable HTML report creation
├── notification_service.py  # Meaningful notification rules
├── fulfillment_simulator.py # Safe fake execution system
└── templates/               # Simple server-rendered dashboard pages
```

The frontend is intentionally simple server-rendered HTML. Do not assume React or add a frontend framework unless explicitly requested.

## Existing project documentation

The primary product-definition document is:

```text
docs/Max Product Definition Main 3b0eba2b3f338077acf6f656a1404efb.md
```

That document describes the desired agency workflow, but several sections are still placeholders. It should be treated as an important product reference, not as a fully completed specification.

## Desired knowledge system

Max should eventually organize reusable knowledge into four related categories:

### SOPs

Process instructions and operating rules. An SOP explains how a workflow is performed from inputs through validation and completion.

### Skills

Reusable expertise such as local SEO, website architecture, conversion copywriting, technical SEO, accessibility, performance, Google Business Profile optimization, and reporting interpretation.

### Templates

Required output shapes such as reports, website briefs, Google posts, Slack messages, task proposals, and fulfillment plans.

### Checklists

Verification criteria used to determine whether an output is complete, safe, and accurate.

Recommended future directory structure:

```text
docs/knowledge/
├── sops/
├── skills/
├── templates/
├── checklists/
└── examples/
```

## Important distinction

Do not merge all knowledge into one giant prompt.

The future prompt system should assemble a task-specific context from:

```text
Approved client facts
        +
Relevant SOPs
        +
Relevant skills
        +
Output template
        +
Verification checklist
        +
Task requirements
        +
Historical feedback
```

The resulting prompt should be saved as a versioned artifact so Max can show which information and knowledge produced an output.

## Website-generation context

Website generation is a major desired workflow.

The website prompt system should eventually support multiple modes:

- `new_build`: create a new website from an approved profile
- `replicate`: closely match an approved reference website
- `improve`: preserve the brand while improving structure, conversion, accessibility, or SEO
- `repair`: fix a defined problem without changing unrelated parts

Website prompts should account for:

- Approved business facts
- Brand colors and assets
- Existing website content
- Existing headings and page structure
- Services and service areas
- Target keywords
- Internal linking
- Metadata
- Accessibility
- Mobile layout
- Performance
- Image requirements
- Do-not-change rules
- Human approval requirements

Max must not invent business facts, services, locations, testimonials, rankings, revenue, or results.

“Exact 1:1” website replication should be treated as a controlled matching goal, not a guarantee. Differences can result from missing assets, fonts, browser rendering, source-code access, and hosting behavior. The system should preserve references, produce a preview or proposal, and require review before publishing.

## SEO and reporting context

Desired SEO workflows include:

- Website audits
- Local keyword and service-area planning
- On-page SEO
- Technical SEO
- Internal linking
- Local schema
- Google Business Profile optimization
- Google Business Profile post drafts
- Weekly blog drafts
- Search Console reporting
- Website analytics reporting
- Baselines and period comparisons

The system must distinguish manual, mock, imported, and live data. AI may explain measured data but must not manufacture rankings, leads, revenue, causes, or completed work.

## Slack context

Each client has a dedicated Slack channel. Slack is intended to support:

- Intake notifications
- Missing-information questions
- Interpretation review
- Prompt review
- Fulfillment-plan review
- Task approval and rejection
- Execution failures
- Verification review
- Report delivery
- Weekly post and blog approval

Slack actions must be connected to Max records and include the actor, time, client, related record, and decision. Emojis may be used as a convenient interface, but important approvals should have a clear, auditable confirmation action.

## Safety and data rules

These rules apply to every future SOP, skill, prompt, and integration:

- Every record belongs to exactly one client.
- One client's data must never appear under another client.
- Original onboarding information is immutable.
- Historical metric snapshots are preserved.
- Historical task, execution, report, finding, and verification records remain visible.
- Archive records instead of permanently deleting history.
- Proposed work is not completed work.
- Approved work is not verified work.
- Completed work does not automatically resolve a finding.
- External changes require explicit approval.
- Mock and manual data must never be represented as live data.
- Credentials must never appear in logs, prompts, reports, or Slack messages.
- Possible external-account or client mismatches stop processing immediately.
- Uncertainty should be reported instead of hidden.

## AI improvement and learning context

Max should improve through a controlled feedback loop, not silent self-modification.

For important AI work, Max should eventually record:

- Input snapshot
- Relevant SOP and skill versions
- Prompt version
- Model and model role
- Estimated and actual token/cost usage
- Generated output
- Human edits
- Approval or rejection
- Rejection reason
- Verification result
- Later measurable outcome

Repeated mistakes can produce a proposed knowledge update. That update should be tested against prior examples and approved before becoming active.

The AI must not automatically rewrite production SOPs, permissions, safety rules, or client facts.

## Cost-control context

Max should conserve API credits by:

- Using normal application code for validation and calculations
- Using smaller models for extraction, classification, and formatting
- Using stronger models for strategy, ambiguity, and high-risk planning
- Caching identical or equivalent requests
- Avoiding repeated full-context submissions
- Summarizing long histories before reuse
- Deduplicating repeated work
- Limiting retries
- Applying per-task and per-client budgets
- Stopping when required information is missing
- Recording model selection and cost estimates

## Current limitations

The current release candidate now includes owner authentication, signed and
channel-scoped Slack control, explicit migrations, approved PDF/share delivery,
provider adapters for GBP and Search Console, packet-scoped website execution
and rollback, and persisted website previews/comparisons. It still needs these
production validations or follow-on capabilities:

- Fine-grained per-client roles beyond the agency-wide capability policy and
  mapped Slack client-channel clearance boundary
- Production-grade monitoring, alert routing, and incident runbooks
- A configured Vercel Cron (or equivalent external scheduler) in the deployed
  environment
- Real provider sandbox tests with each agency's Google, GitHub, Vercel, Slack,
  and billing credentials
- Encrypted off-host backup retention plus an isolated restore rehearsal (the
  backup artifact workflow is documented in `docs/operations-backups.md`)
- Optional presentation-style client decks; the current client deliverable is a
  readable, approval-gated PDF

Task completion and business outcomes remain separate facts. The current
release candidate now persists source-backed post-fulfillment outcome
measurements with an explicit `met`, `not_met`, or `inconclusive` assessment and
shows them in subsequent reports. It still does not infer improvement from a
completed task without recorded provider or owner evidence.

## Automatic onboarding milestone (2026-08-13)

An immutable intake now queues a database-backed onboarding run. The signed job
runner processes OpenAI interpretation, Slack channel creation, Vercel and
GitHub discovery, and website analytics matching. Unique exact matches are
saved automatically. Uncertain or multiple matches become owner-review
candidates and cannot be used until approved.

Temporary provider failures retry no more than three times. Missing credentials,
authorization failures, budget exhaustion, rejected matches, and exhausted
retries pause the run and create an actionable internal notification. Existing
verified mappings are never overwritten by a run or backfill.

When all required connections are resolved, the run waits for official profile
approval. Approval resumes the run, creates proposed tasks for enabled workflows,
and marks the client ready for fulfillment. It does not execute or publish work.
- Knowledge/SOP library management
- Prompt versioning and compilation
- Formal AI evaluation datasets

## Guidance for the assisting AI

Before proposing implementation:

1. Read the primary product-definition document.
2. Inspect the existing project before suggesting file changes.
3. Avoid adding unnecessary frameworks or abstractions.
4. Preserve the existing FastAPI, SQLAlchemy, and simple HTML architecture.
5. Separate reusable knowledge from client-specific facts.
6. Make every generated artifact traceable to its inputs and versions.
7. Explain what should be implemented, what should remain manual, and what requires human approval.
8. Add tests for normal behavior, failure cases, data separation, idempotency, and historical preservation.
9. Do not connect real external services unless explicitly authorized.
10. Do not silently expand the scope of a requested phase.
