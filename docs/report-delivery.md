# Report delivery

Reports are immutable snapshots. Generation creates a `draft` record and
stores the exact facts and HTML used for that version. A client-facing report
must be approved by an agency owner before its PDF can be downloaded or
delivered externally.

When paid-mode billing enforcement is enabled, generating a new report or fresh
in-depth update requires an active or currently valid trial subscription. This
does not remove historical reports or prevent read-only review of saved records.

```text
POST /clients/{client_id}/reports
        ↓
POST /reports/{report_id}/approval
        ↓
GET /reports/{report_id}/pdf (owner)
        ↓
POST /reports/{report_id}/slack-delivery
        ↓
GET /reports/{report_id}/share/{token}/pdf (client)
```

The PDF renderer is dependency-free and preserves source labels, verified work,
open findings, and report facts from the saved HTML snapshot. New metrics or
executions cannot mutate an existing report.

Simple and in-depth reports also include an evidence-derived operational
retention-risk summary for the owner. This is a value-communication signal, not
a prediction of client intent. Client reports include a short client-message
draft built only from verified work, source-labeled metrics, next actions, and
explicit access needs. The draft remains approval-gated and is never delivered
automatically.

Every generated 30/60/90 action also names its success metric and verification
window. For example, a title change points to Search Console impressions,
clicks, and click-through rate; a conversion change points to tracked calls,
forms, bookings, or qualified leads. These are measurement targets, not
guarantees of rankings, traffic, or leads.

An owner can turn any saved plan item into a normal proposed task with
`POST /reports/{report_id}/plan-items/{plan_30|plan_60|plan_90}/{item_index}/task`.
Max records the report, plan item, expected result, success metric, and
verification window in the source Finding, then routes the task through the
existing owner-approval and independent-verification lifecycle. Repeating the
same request returns the existing task instead of creating a duplicate.

An in-depth audit also materializes each fresh gap or access blocker as an open,
client-scoped Finding with its source, evidence summary, confidence, severity,
and recommended action. Those Findings can enter the normal proposed-task,
owner-approval, fulfillment, and independent-verification lifecycle without
inventing a separate execution path.

Website analytics snapshots retain their provider period, recording timestamp,
and freshness state in the report. A provider outage, malformed response, or
unmatched tracker site is saved as a report-visible access issue; Max does not
silently relabel an older snapshot as a current result.

The bounded public crawl now also checks up to 20 discovered internal links for
error or unreachable responses. Broken-link counts and the checked-link sample
are preserved in structured website evidence, with a concrete 0–30 day repair
action when failures are found.

Slack delivery is client-bound and idempotent. Max records every attempt,
retries a failed attempt against the same verified channel, and never sends an
internal or unapproved report. Set `MAX_PUBLIC_BASE_URL` to the deployed Max
origin so the Slack message contains an absolute client-share PDF link. The
share token contains no report data, expires after 90 days, and can be revoked
without deleting the immutable report (`POST /reports/{report_id}/share/revoke`).
Owner-authenticated `/reports/{report_id}/pdf` remains separate from the
client link, so publishing a share URL does not expose the internal dashboard.
Client report rendering also excludes the owner-only retention-risk summary,
execution-cost labels, raw finding evidence, and internal task-risk details;
those remain in the internal report and audit history.

Failure details are audience-filtered as well. Secret-like values, provider
exception diagnostics, credential wording, and stack-trace text are replaced by
an actionable client-safe explanation; the full diagnostic remains available in
the internal report and audit trail.

The HTML report page is also the owner control surface. It exposes the current
approval and delivery state, provides approve/deliver/retry controls, and shows
the append-only report audit history. Idempotent replays do not create duplicate
delivery events.
