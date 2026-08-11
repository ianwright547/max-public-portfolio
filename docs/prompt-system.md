# Versioned prompt system

Max compiles task-specific prompt artifacts instead of keeping one global
prompt. A compiled artifact records:

- the client and immutable intake or approved profile used as input;
- the purpose and model role;
- the reusable SOP and skill files included;
- the complete system and user prompt;
- a content hash and prompt version;
- an audit event linking compilation to the client record.

## API

`POST /clients/{client_id}/prompt-artifacts` accepts:

```json
{
  "operation_key": "unique-operation-key",
  "purpose": "website_generation",
  "model_role": "balanced",
  "task_id": "optional-approved-task-id"
}
```

Onboarding interpretation may be compiled before profile approval by supplying
`intake_id`. Fulfillment, website, GBP, and reporting prompts require the
client's official approved profile.

The operation key is idempotent. Repeating it returns the original artifact;
using it for another client or purpose is rejected. Prompt artifacts are
traceability records, not authorization to execute external changes.
