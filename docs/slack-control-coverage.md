# Slack Control Coverage

This is the audited Slack surface for the current MVP contract. A command is
executed only when the signed request is from a configured owner and the client
scope is unambiguous. Natural-language questions are read-only unless they
match an allowlisted command below.

## Implemented Controls

| Area | Slack control | Safety boundary |
| --- | --- | --- |
| Clients | Create, update, archive/delete, and change client status | Mapped-channel members can control that client; DMs and unmapped channels remain owner-only; deletion also archives the Slack channel while preserving audit history |
| Client updates | Simple saved-data report or fresh in-depth portfolio/client audit | In-depth mode refreshes supported APIs, crawls bounded public pages, labels blockers and needed access, and returns tangible 0–30/31–60/61–90 day work |
| Daily planning | Simple or in-depth all-work, SEO, fulfillment, or reporting plan | One persisted plan per client/day; prioritizes approved work, verification, approvals, blockers, audit recommendations, and verified work still awaiting a measured outcome without duplicating tasks |
| Plan-to-task handoff | Say `make task from daily plan item 1` in the mapped client channel | The latest persisted plan item is converted into a normal evidence-backed task, duplicate conversion reuses the existing task, and approval remains separate from execution |
| Memory | 24-hour bounded recent context plus explicit durable remember/update/list/forget controls | Memories are agency/client scoped, relevance filtered, character limited, auditable, and reject credentials |
| Natural-language commands | AI fallback maps unfamiliar wording onto the complete existing allowlist | Exact commands remain the low-cost fast path; structured high-confidence output is required; hypotheticals/negations never execute |
| Intake | Submit immutable intake, show intake status/gaps, start or resume onboarding | Client-channel scope; validation remains canonical |
| Profile | Approve, reject, or correct a profile version | Approval and correction preserve immutable history |
| Tasks | Propose, approve, reject, retry, or block a task | Reasons and dependency checks remain required |
| Website planning | Request website generation; prepare a scoped work packet | Requires approved profile and verified domain/repository connections |
| Codex fulfillment handoff | Preview/copy packet, inspect its quality gate, record handoff, and return structured completed/blocked/failed evidence | Packet creation uses no Max model call; file scope, client identity, task approval, acceptance criteria, measurement contract, audit, and separate verification remain enforced |
| Content fulfillment handoff | Prepare an approved local-page or blog task as a scoped Codex packet, then record a human content review | Uses approved facts and saved Search Console opportunities; content publication remains separate, and execution cannot be independently verified until the review checklist is approved |
| Website execution | Run approved website work, poll execution, review evidence, confirm verification | Packet scope, execution, and verification are separate facts |
| Browser fallback | Submit an approved browser task and poll/review/verify it | Requires configured worker; no arbitrary browser action |
| Integrations | Link website, GitHub, Search Console, or GBP references | References only; credentials are never accepted in Slack |
| GBP posts | Create draft, approve, and publish a post | Draft approval is always separate from publication |
| Metrics and reports | Record metrics, create reports, approve, and deliver reports | Saved facts and report snapshots are immutable |
| Outcome measurement | Record whether an approved task's success metric was met after its verification window | Measurements require explicit source, evidence, reviewer, and `met`/`not_met`/`inconclusive` assessment; completed work is never treated as a business-result claim |
| Notifications | Mark notifications read or retry failed Slack delivery | Delivery is idempotent and audited |
| Scheduled workflows | Enable/disable health, website analytics, Search Console, or daily planning; run due jobs | Client channels enable one daily plan job automatically; scheduler authentication and per-client scope remain enforced |
| Questions | Ask agency/client questions using verified records and relevant SOP excerpts | Context is bounded, redacted, and client-isolated |
| AI budget | Ask about agency or client monthly AI spend | Values come from the persisted usage ledger |

Use `@Max help` for the exact command syntax. Owner DMs are agency-scoped;
client-channel commands are restricted to that mapped client.

The agency member directory can map an active Slack user ID to an `owner`,
`admin`, `operator`, or `viewer` role. Mapped client channels remain the
explicit client-scope clearance boundary; unmapped channels and DMs use the
member role (or the legacy configured owner IDs). Billing and member
administration remain owner-controlled, while viewer access is limited
to reading and reporting.

AI wording translation has a confidence gate: low-confidence state-changing
interpretations stop with a clarification request and never fall through to a
read-only AI answer that could imply the action happened. Action failures are
translated into channel-local recovery instructions (approval, access,
connection, or retry) rather than generic admin/process errors.

## Deferred or Read-Only SOPs

The knowledge library contains proposed SOPs whose provider adapters and durable
records are not part of the current MVP. Max may explain these SOPs, identify
missing inputs, or propose a task, but must not claim execution:

- Automatic blog, service-page, and location-page publication (Codex-assisted
  scoped packet preparation is implemented; human writing review and publishing
  remain separate)
- Citation management, review monitoring, review replies, and competitor research
- Multi-location rosters and location-specific content/citation operations
- Fully automatic weekly blog, GBP-post, or report schedules
- Billing, credential management, and direct client communication
- Arbitrary browser actions outside an approved browser task and configured worker

These are product gaps, not Slack parsing failures. Implementing them requires
durable content/research records, provider adapters, approval rules, and tests.

## Production Gates

- Core deployment health/readiness and migration checks must pass.
- Full readiness additionally requires Google Business refresh-token and
  verified account/location configuration.
- Live owner DMs additionally require the installed Slack app to subscribe to
  `message.im` and to match `docs/slack-app-manifest.yaml`.
