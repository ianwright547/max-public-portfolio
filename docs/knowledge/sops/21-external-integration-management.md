---
title: External Integration Management
slug: external-integration-management
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - provider adapters
  - GitHub
  - Vercel
  - Slack
  - Google services
  - analytics
  - AI providers
owner: agency
review_required: true
---

# External Integration Management

## Purpose

Max uses adapters so the core client, task, metric, report, and approval workflows do not depend directly on one external provider.

## Adapter responsibilities

Each adapter handles:

- Provider authentication
- Connection status
- Permission status
- Resource lookup
- Client-resource verification
- Read or write operation
- Provider error mapping
- Rate limits
- Temporary failures
- Idempotency
- Last successful synchronization

## Provider support

Adapters may support:

- GitHub
- Vercel
- Slack
- Search Console
- Google Business Profile
- Website analytics dashboard
- OpenAI
- DeepSeek
- Kimi

Fake and mock adapters remain available for tests and demonstrations.

## Source labeling

Live provider results use `live` or the provider-specific source label. Manual, mock, and imported results retain their own labels.

## Client verification

Every provider resource must be verified against the Max client using available domain, name, project, account, and resource identifiers.

Possible mismatch stops processing immediately.

## Idempotency

Read synchronization and write operations use a unique operation key. Repeated requests reuse or link to the existing result.

Historical snapshots and execution records are never overwritten.

## Provider errors

- Missing permission: block affected action.
- Expired authorization: mark disconnected and request reconnection.
- Rate limit: retry using the retry policy.
- Temporary outage: retry and then preserve failure.
- Unavailable resource: record unavailable data.
- Client mismatch: stop immediately and escalate.

Credentials never appear in provider errors or Max records.

## Replacement

A provider may be replaced by implementing the same adapter contract. Core Max workflow code should not need to change.

## Final checklist

- Adapter used?
- Client-resource verified?
- Source labeled?
- Idempotency key used?
- History preserved?
- Errors mapped safely?
- Credentials protected?
- Replacement path documented?

