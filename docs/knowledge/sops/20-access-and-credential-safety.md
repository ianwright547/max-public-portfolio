---
title: Access and Credential Safety
slug: access-and-credential-safety
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - API keys
  - OAuth tokens
  - GitHub
  - Vercel
  - Slack
  - Google services
  - AI providers
owner: agency
review_required: true
---

# Access and Credential Safety

## Purpose

This SOP protects client access, provider credentials, and external resources used by Max.

## Secret storage

Credentials belong only in environment variables or an approved secret manager.

Never place secrets in:

- Slack
- Reports
- Prompts
- Codex packets
- GitHub files
- Logs
- Screenshots
- Database notes

## Minimum access

Use the minimum permissions required for the current action.

Read-only access is preferred for data collection. Write access is used only when the approved workflow requires it.

## Client-resource verification

Before reading or writing an external resource, verify:

- Client ID
- Domain
- External account or property
- Resource or project ID
- Connection owner
- Permission scope

An uncertain or mismatched resource stops processing immediately.

## Missing and expired access

Missing permissions block the affected work and create a Slack notification when agency action is needed.

Expired authorization stops the affected integration until it is reconnected.

Temporary network failures may retry. Permission failures must not be retried as if they were temporary.

## Exposure response

If a secret may have been exposed:

1. Stop affected work.
2. Redact the secret from future output.
3. Rotate or revoke it.
4. Record the incident without storing the secret.
5. Notify the agency owner.

## AI-provider safety

Send only task-relevant, redacted context to AI providers. Before enabling a provider for client data, review current retention and training terms.

## Audit

Record access changes with client, provider, actor, scope, time, and result. Never record the credential value.

## Final checklist

- Secret stored safely?
- Minimum permission used?
- Correct client resource?
- Domain verified?
- Expiration monitored?
- No secret in output?
- Access change audited?

