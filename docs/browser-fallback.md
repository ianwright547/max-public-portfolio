# Browser fallback

API execution is preferred. Tasks that require browser control use an external
worker configured with `BROWSER_WORKER_URL` and `BROWSER_WORKER_TOKEN`. Browser
control also requires a separate, explicit owner approval scoped to the task and
reason; approving the task alone is not enough.

Max sends only the client ID, task ID, HTTPS target URL, and scoped instructions.
It does not send provider credentials. Worker jobs are recorded as normal
fulfillment executions and remain `running` until polled.

```text
approved task
    ↓
POST /tasks/{task_id}/browser-approval (owner, exact scope/reason)
    ↓
POST /tasks/{task_id}/browser-executions
    ↓
running execution + worker job ID
    ↓
POST /browser-executions/{execution_id}/poll
    ↓
completed / failed / blocked
    ↓
independent verification
```

The worker must return evidence references rather than secrets. Max never marks
the task verified automatically.
