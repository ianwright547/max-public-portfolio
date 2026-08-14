# Max — public portfolio project report

> Portfolio copy for recruiters and technical reviewers. This document describes the system design and engineering decisions; it is not a claim that this repository is a production SaaS or a live client account.

## What this app does

Max is an agency-operations platform for local SEO and website fulfillment. An agency owner can onboard a client, capture business context, connect permitted providers, and ask for work in natural language. Max turns that request into grounded recommendations, reports, tasks, and fulfillment handoffs.

The core loop is:

`client context → evidence collection → diagnosis → prioritized plan → approval → fulfillment handoff → verification → outcome update`

The system can assemble client updates from website observations, Google Search Console/Business Profile data when connected, analytics, and prior work. It identifies missing or unverifiable items instead of inventing results. It can produce a simple or in-depth report, a 30/60/90-day plan, daily tasks, and a Codex-ready work packet. External mutations remain approval-gated and are checked against live provider access immediately before execution.

## What it is used for

- Client onboarding and structured intake
- Local SEO audits, progress reports, and 30/60/90-day plans
- Tangible daily fulfillment tasks with owners, dependencies, and expected outcomes
- Slack and dashboard workflows for asking for reports or requesting work conversationally
- Explicitly named owner-DM commands (for example, removing one client) with ambiguity-safe client resolution
- Evidence-backed recommendations with clear gaps and “what is needed to continue” messages
- Codex handoff packets for website, content, technical SEO, and GBP work
- Optional provider workflows for website changes, GitHub/Vercel deployments, and GBP publishing
- Auditable approvals, execution evidence, and client-safe shareable reports

## Why I built it

I wanted to build something useful for an agency rather than a small demo: a system that reduces the distance between a client request and completed, verifiable fulfillment. The project let me use Claude and Codex as development partners while learning how to design the state, boundaries, failure modes, and audit trail around an AI-enabled workflow.

## System-design work outside my previous scope

The interesting work is the system around the model, not just the chat UI:

- **Durable workflows:** onboarding, plans, reports, approvals, jobs, retries, and outcomes are persisted rather than held only in a conversation.
- **Evidence-first reporting:** every important conclusion has a source, freshness, confidence, and verification status. Unknown access is reported as unknown.
- **Human-in-the-loop fulfillment:** recommendations and Codex packets can be generated cheaply; consequential external writes require explicit authorization and a final provider-health check.
- **Provider boundaries:** Slack, websites, GitHub, Vercel, Search Console, and GBP are adapters with safe failure codes instead of hidden side effects.
- **Security and authorization:** secrets stay in runtime configuration, client/agency scope is enforced, privileged job routes require a separate secret, and audit events record who requested and completed sensitive actions.
- **Resilience and cost control:** cached evidence, short-lived chat context, explicit durable memory, idempotent jobs, and packet-based handoffs reduce unnecessary model/provider calls.
- **Operational visibility:** readiness checks, provider verification, scheduler health, execution evidence, and outcome tracking make failures diagnosable.

## Stack

Python 3.9+, FastAPI, Pydantic, SQLAlchemy, Alembic, SQLite/Postgres, server-rendered HTML/CSS, Slack APIs, Google APIs, GitHub/Vercel adapters, browser-worker integrations, pytest, and GitHub Actions.

## Security and public-copy boundary

The public portfolio version is deliberately separate from the private working project. It contains dummy/example data only. It must not contain provider tokens, Slack history, production databases, private client manifests, private product specifications, or real client reports. Runtime secrets are supplied through environment variables and are never committed.

The public copy also labels integrations as optional and shows what the system does when access is unavailable: it returns a specific provider/access gap and the next requirement, rather than fabricating a report or silently attempting a write.

## Verification snapshot

The private working project has an automated test suite, migration checks, compile checks, and deployment smoke-test contracts. The sanitized public checkout also bootstraps a test schema and currently passes all 409 tests with dummy configuration. This remains a review artifact, not a live performance guarantee.

## Suggested recruiter review path

1. Read this report and `README.md`.
2. Inspect `app/report_builder.py`, `app/client_provider_verification.py`, and the route/job modules for the evidence and authorization boundaries.
3. Review the tests for report provenance, provider failures, approvals, and scheduler protection.
4. Run the test and migration commands in the project documentation.

This project is intentionally presented as a learning-driven system-design portfolio: useful enough to demonstrate product thinking, but honest about the provider credentials and operational setup required for production.
