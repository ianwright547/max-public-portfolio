# Security policy for the portfolio copy

This repository is a recruiter-facing demonstration of Max. It contains dummy
client data and test-only provider placeholders. It is not authorized to access
real client accounts and must not receive production tokens, Slack history,
databases, or private reports.

## Reporting a problem

If you find a credential-like value or private data in this copy, do not use it.
Remove the local checkout, report the file and commit privately to the project
owner, and rotate the affected credential if it could be real. Public issues
should describe the category of problem without reproducing a secret.

## Runtime boundary

Provider credentials belong in a private environment. External writes remain
approval-gated and provider-verified. The public audit command is intended to
run before publishing a new portfolio copy.
