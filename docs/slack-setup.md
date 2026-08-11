# Slack connection setup

Max uses one public agency-workspace Slack channel for each client. The internal Max notification
record remains the source of truth, and Slack is a replaceable delivery adapter.

## Authorization flow

This first version is a single-agency-workspace installation. Create a Slack app
from `docs/slack-app-manifest.yaml`, review its seven bot scopes, and install it in
the agency workspace. Slack then issues a bot token beginning with `xoxb-`.
Store that token only in `.env` locally and as an encrypted Vercel environment
variable. Max sends it in the HTTP Authorization header and never stores it in
the database, logs, reports, or messages.

Store the app's Signing Secret as `SLACK_SIGNING_SECRET`. Max verifies the raw
request signature and five-minute timestamp window before accepting an approval
button or app mention. Set the Interactivity request URL to
`https://your-deployment.example.com/slack/actions`. Enable Event Subscriptions at
`https://your-deployment.example.com/slack/events`, subscribe the bot to `app_mention`
and `message.im`, and reinstall the app after adding the DM scope/event.

## Minimum permissions

The checked-in manifest is the source of truth for the installed app. Reconcile the
Slack app configuration with it before production use; do not retain unrelated
scopes from an older or generated manifest. The installed app must include the
`message.im` bot event for owner DMs to reach Max.

- `channels:manage`: create public client channels and add configured agency owners.
- `channels:read`: verify a mentioned channel's current ID and name after recreation.
- `groups:read`: verify invited private channels while keeping client mappings isolated.
- `im:history`: receive direct messages sent to Max so configured owners can operate from Slack DMs.
- `chat:write`: post Max messages as the Max bot in channels it belongs to.
- `app_mentions:read`: receive messages that explicitly mention Max.
- `users:read`: verify configured agency-owner IDs are active human members during
  the production Slack connectivity probe.

Max does not request permission to read arbitrary channel history, impersonate a user,
upload files, or receive messages that do not mention it. The `im:history` scope is
used only for direct messages addressed to Max, and only configured owners are answered.

## Workspace and client verification

Before creating a channel, Max calls Slack `auth.test` and compares the returned
workspace ID with `SLACK_WORKSPACE_ID`. A mismatch stops immediately. Each saved
channel mapping has unique client and channel IDs. Every delivery checks the
notification client, mapping client, and Slack response channel before recording
success.

## Environment values

```text
SLACK_BOT_TOKEN=xoxb-...
SLACK_WORKSPACE_ID=T...
SLACK_OWNER_USER_IDS=U...,U...
SLACK_SIGNING_SECRET=...
```

`SLACK_OWNER_USER_IDS` contains comma-separated Slack member IDs that Max adds
to each public client channel so their membership is explicit and auditable.
In a full production profile, the release probe requires every configured ID to
resolve to an active human member.

## Failure handling

- Missing or invalid authorization is recorded as failed delivery.
- Workspace or channel mismatches stop immediately.
- Rate limits and Slack outages are marked retryable, but Max does not loop or spam.
- A notification has one unique Slack delivery record.
- Slack receives the internal notification ID as its idempotency key.
- A Slack failure never deletes the permanent internal notification.

## Current boundary

Max sends meaningful notifications outward and answers direct `@Max` questions
or configured-owner DMs from verified Max records. Client channels receive only that client's context;
configured owners may ask agency-wide questions from another public channel.

Signed mentions from a configured owner support these audited controls:

- `create a new client called BUSINESS NAME starting YYYY-MM-DD`
- `create a task to REQUEST` from the client's channel
- `approve task TASK_ID`
- `reject task TASK_ID because REASON`
- `retry task TASK_ID` or `mark task TASK_ID blocked because REASON`
- `start onboarding` from the client's channel
- `request website generation as replicate` from the client's channel
- `prepare content task TASK_ID as local_page|blog` from the client's channel;
  this creates a scoped Codex content brief from approved facts and saved
  Search Console opportunities, but does not publish automatically.
- `submit intake {JSON}` from the client's channel, using the required intake fields shown by `@Max help`
- `connect website|github|search console|gbp {JSON}` from the client's channel; these commands save references only and never accept credentials
- `update client {JSON}`, `archive this client`, or `delete this client` from the client's channel
- `simple report on all clients` for a fast summary of saved Max state
- `in-depth report on all clients` for a fresh bounded website crawl, Search Console and analytics refresh, GBP access diagnosis, and evidence-backed 0–30/31–60/61–90 day actions
- `simple report for this client` or `in-depth audit for this client` from a mapped client channel
- `today's tasks for this client` for a low-cost plan built from saved task and evidence state
- `in-depth SEO plan for this client` for a fresh crawl/integration audit plus tangible 0–30/31–60/61–90 day work
- `fulfillment plan for this client` or `reporting plan for this client` to filter the same deduplicated daily work queue
- `crawl and inspect this website` to run the in-depth client audit directly
- `remember that ...` or `store this in memory: ...` to save a durable agency/client-scoped memory
- `update your response style to ...` to replace the durable style instruction in the current scope
- `what do you remember?`, `update memory MEMORY_ID to ...`, and `forget memory MEMORY_ID` to inspect and control durable memory
- `show intake status` or `show onboarding gaps` from the client's channel
- `record metric {JSON}` or `create report {JSON}` from the client's channel
- `record outcome for task TASK_ID {JSON}` from the client's channel to save a
  post-work measurement. Include `metric_name`, `assessment` (`met`,
  `not_met`, or `inconclusive`), `source_reference`, `evidence`, `notes`, and
  `observed_at`; optional numeric baseline/current values are preserved.
- `create GBP post {JSON}` from the client's channel, then approve and publish it separately
- `approve this`, `approve it`, or `go ahead with it` from a mapped client channel
  approves the single proposed task Max just presented; if multiple tasks are
  pending, Max requires the task ID.
- `approve GBP post GBP_POST_ID`, then `publish GBP post GBP_POST_ID`
- `approve profile PROFILE_VERSION_ID`
- `reject profile PROFILE_VERSION_ID because REASON`
- `approve connection candidate CANDIDATE_ID`
- `reject connection candidate CANDIDATE_ID because REASON`
- `approve report REPORT_ID`
- `send report REPORT_ID`
- `prepare website task TASK_ID as improve`
- `show codex packet PACKET_ID` to preview the complete copyable handoff without starting work
- `handoff codex packet PACKET_ID` to record the handoff and move the task to running
- `record codex result PACKET_ID {JSON}` to return completed, blocked, or failed evidence for separate verification
- `create a task from daily plan item 1` to turn a numbered recommendation into an approval-required task
- `run website task TASK_ID`
- `run browser task TASK_ID at https://example.com to INSTRUCTIONS`
- `poll execution EXECUTION_ID`
- `review execution EXECUTION_ID`
- `confirm verify execution EXECUTION_ID`
- `run health check website available` from the client channel
- `sync search console` from the client channel
- `sync website metrics for 30 days` from an agency channel
- `enable health checks`, `disable website analytics`, or `enable search console` from a client channel
- `run due jobs` from an agency channel
- `mark notification NOTIFICATION_ID read`
- `retry notification NOTIFICATION_ID`
- `mark this client active`, `paused`, or `cancelled`

Use `@Max help` in Slack to see the current command list. Natural-language
questions may use current client, task, finding, onboarding, integration,
notification, execution, and report state plus query-relevant excerpts from
the local SOP library. Common credential formats are redacted before AI
requests and Slack conversation audit storage. Mutations are deterministic and
available to configured owners in DMs and agency channels. In a mapped client
channel, membership is the clearance boundary, so any channel member can run a
recognized client-scoped command or use an approval button. The AI response path
cannot invent or execute a mutation.

Simple reports do not call external sources. In-depth reports refresh supported
read-only integrations, inspect up to six public HTML pages per client plus
robots.txt and sitemap.xml, and label every source. Missing or failed access is
reported under “Could not verify” and “Needed to continue”; inaccessible facts
are never inferred. Google Business Profile publishing is supported today, but
live category, hours, review, photo, and completeness inspection remains blocked
until GBP read scope/API access is enabled.

Daily plans are stored once per client and calendar day and refreshed in place,
so repeated requests do not create duplicate plans. Existing approved/ready tasks
come first, followed by work needing verification or approval, blockers, and fresh
audit recommendations. Recommendations are not falsely marked as completed work;
they include a concrete expected result, success metric, and verification window,
plus the next step needed to scope them into the normal task, execution-evidence,
and verification workflow. Creating or reusing a client Slack
channel enables a simple daily planning job. Owners can say `enable in-depth daily
plans` to switch that client’s persisted job to the deeper audit mode. Scheduled
jobs also retain a focus (`all`, `seo`, `fulfillment`, or `reporting`) and may be
configured to create an internal or client report after the plan. In-depth work
records provider blockers when access is unavailable rather than inventing facts.
If one provider fails during a portfolio audit, Max keeps the other client
updates and marks only the affected client as partially blocked with a concrete
retry/access requirement.

`DELETE /clients/{client_id}` uses the same lifecycle semantics as `delete this
client` in Slack: the client leaves active lists, historical records remain for
audit, and its mapped Slack channel is archived. If Slack is temporarily
unavailable, the connection is marked `archive_pending` for retry instead of
pretending cleanup completed.

For recurring fulfillment, `enable in-depth daily plans with tasks` persists a
scheduled planner that converts recommendations and access blockers into proposed
approval tasks. It never approves, executes, or publishes those tasks.

Slack memory has two bounded layers. Recent conversational continuity uses at
most six turns from the same thread—or recent channel context for a new top-level
message—and ignores turns older than 24 hours. Questions and answers are clipped
to a 6,000-character input budget. Explicit durable memories are stored until
forgotten, scoped either to the agency or the mapped client, and retrieved only
when relevant; style and preference memories are always eligible. At most six
durable memories and 2,400 characters are added to an AI request. Credential-like
content is redacted and rejected from durable memory.

Recognized exact commands use deterministic parsing first. If wording appears to
request an action but does not match literally, Max uses a small structured AI
classification call to translate synonyms, misspellings, and conversational
phrasing into one existing allowlisted command. The classifier cannot execute
arbitrary code or invent required IDs/JSON. It must return high confidence, and
questions, hypotheticals, negative instructions, missing targets, and unsupported
requests stay conversational instead of executing. Failures are explained with
the next safe step in the same Slack conversation; users are not redirected to
an admin process or generic “check Max” message.

Each Slack AI call reserves the monthly budget before contacting the provider
and persists its usage ledger entry before any interpreted action or response
can fail later. A downstream rollback therefore cannot erase recorded spend.

Max does not read arbitrary channel history or messages that do not mention it.
Configured owners may also DM Max directly; DMs are treated as agency-scoped
requests and are never attached to a client without a verified client channel.
For an explicit app-mention thread, Max stores only a bounded,
credential-redacted turn ledger and supplies the recent turns from that exact
channel/thread to the next AI question. Approval does not mark work completed or verified, and risky
external work remains subject to the task and verification gates. Execution
verification is deliberately two-stage: the owner must request the saved
evidence review before the signed confirmation command is accepted.

## Not Yet Executable

The current MVP contract does not claim to execute every proposed knowledge SOP.
Blogs, service/location-page content, citation and review operations, competitor
research, and fully automatic GBP/report schedules remain planning or review work
until their provider adapters and durable records are implemented. Max can answer
questions about those SOPs, identify missing inputs, and propose an allowlisted
task, but it must not claim that the work was drafted, published, or verified.
Credentials, billing, client communication, and arbitrary browser actions are
also outside the current Slack mutation surface.
