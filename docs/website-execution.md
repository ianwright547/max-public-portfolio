# Website execution

`POST /tasks/{task_id}/website-generation-preview` generates and stores an
immutable draft with file hashes and a manifest without committing or deploying
anything. Reviewers can inspect it through `GET /website-previews/{preview_id}`
and see the baseline preview plus added, removed, changed, and unchanged paths.
The preview also includes a deterministic technical audit: generated-page
inventory, HTML parsing/title/H1 checks, sitemap and robots presence, and
pass/fail counts. These checks describe the draft file set only; production
deployment and independent verification remain separate.

When a draft omits them, Max adds `public/sitemap.xml` and
`public/robots.txt` deterministically from the approved packet domain and
detected application/HTML routes. This keeps fulfillment packets shareable and
gives the implementer a concrete crawl-discovery baseline; the live sitemap and
robots response still need to be checked after deployment.

Website changes execute only through an existing, client-bound Codex work
packet. The packet supplies the verified GitHub repository, branch, Vercel
project, allowed paths, prohibited paths, and publishing state.

`POST /tasks/{task_id}/website-executions` validates every submitted file before
calling the GitHub App API:

- absolute paths, traversal, duplicates, prohibited paths, and out-of-scope
  paths are rejected;
- private keys and common provider secret assignments are rejected;
- the task must be approved or ready, and dependencies must be verified;
- publishing packets require a `ready` task;
- the operation key is idempotent;
- commit SHAs, changed paths, branch, client, task, and Vercel project are
  permanently recorded in the execution evidence.
- a `website_artifact_audit` records the same page inventory and technical
  checks for the exact files that were committed;

The linked Vercel deployment is recorded as pending by default. Set
`MAX_ENABLE_EXTERNAL_WRITES=true` only in a controlled production environment
to trigger the Vercel deployment API after the commit. Deployment failures are
recorded on the execution instead of losing the GitHub commit. No task is
marked verified automatically; the existing execution-verification workflow
remains the final evidence gate.

To undo an approved GitHub execution, call `POST
/website-executions/{execution_id}/rollback` with an operation key and reason.
Max creates one provider-native revert commit from the recorded SHA, stores the
rollback evidence, moves the task back to `blocked`, and requires fresh
independent verification.

`POST /tasks/{task_id}/website-generation` is the AI-backed entry point. It
requires the same approved task and packet, compiles the versioned
`website_generation` prompt from the official profile, validates the returned
file set, and then calls the exact same execution endpoint. Each direct OpenAI
generation reserves the configured monthly AI budget and commits its usage
ledger entry before output parsing/validation, so malformed provider output
cannot be retried without accounting for the spend. AI generation never bypasses
packet existence/expiry checks, task approval, packet scope, approval, or the
budget stop.
