---
title: Model Selection and Cost Control
slug: model-selection-and-cost-control
knowledge_type: sop
version: "1.0.0"
status: proposed
applies_to:
  - OpenAI usage
  - Codex packets
  - AI workflows
  - cost tracking
owner: agency
review_required: true
---

# Model Selection and Cost Control

## Purpose

Max should use AI where it adds value and use normal application code for predictable work.

## Use code instead of AI for

- Validation
- Calculations
- Date and period comparisons
- Duplicate detection
- Required-field checks
- Status transitions
- Source labels
- Report tables
- Link checks

## Model routing

Use the efficient model for:

- Extraction
- Classification
- Formatting
- Short blog drafts
- Metadata
- Summaries
- Routine content adaptation

Use the balanced model for:

- Normal interpretations
- Standard SEO planning
- Reports requiring explanation
- Moderate ambiguity

Use the strongest model for:

- 1:1 website work
- Major website changes
- Complex SEO strategy
- Conflicting information
- High-risk plans
- Difficult verification explanations

For Local SEO strategy, rank-map phase decisions, Core 30 decisions, and GBP-to-landing-page recommendations, use `gpt-5.6-sol` with medium reasoning effort.

For routine local content, blog drafts, Google posts, formatting, and summaries, use DeepSeek Flash when the provider is enabled and the context has been redacted appropriately.

## Budgets

Start with a $50 monthly Max API safety budget.

Suggested alerts:

- $25 warning
- $40 strong warning
- $50 stop nonessential AI work

Every substantial task should include an estimated cost, client, model role, and budget.

If a task is likely to exceed its budget, stop and notify the agency owner.

## Saving cost

- Reuse approved facts and components.
- Cache equivalent requests.
- Send only relevant context.
- Summarize long history before reuse.
- Batch compatible work.
- Limit retries.
- Avoid AI calls for routine calculations.
- Do not re-interpret unchanged intake information.

Codex work packets should rely on the connected GitHub repository and should not cause an unnecessary Max API call.

## Records

Record when available:

- Model role
- Model name
- Input and output token counts
- Estimated cost
- Actual cost
- Client
- Task
- Retry count
- Budget result

## Final checklist

- Is AI needed?
- Is the model role appropriate?
- Is the task budget known?
- Can code handle the task?
- Is relevant context limited?
- Are retries limited?
- Would caching help?
- Should work stop at the budget threshold?
