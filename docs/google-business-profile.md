# Google Business Profile workflow

Google Business Profile locations are client-bound records. Max never uses a
single global location for multiple clients, and the same account/location pair
cannot be linked twice.

Posts follow this state machine:

```text
draft → approved → published
   └──────────────→ failed
```

Creating a draft does not contact Google. Publishing requires an explicit owner
approval and uses the configured OAuth refresh token only in memory. Duplicate
operation keys return the original draft, while a provider failure is stored as
a safe error code without exposing credentials.
