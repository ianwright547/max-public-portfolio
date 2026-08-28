# Max

max.ianmwright.com

Agency software for local SEO and website work. You onboard a client, connect whatever accounts they'll actually give you access to, and then ask for things in plain language instead of clicking through a bunch of forms. It turns that into reports, plans, daily tasks and handoffs.

The demo is read only and every client in it is made up. There are six of them sitting at different stages so the screens aren't all showing the same happy path. One of them has a deliberately broken Search Console connection, which is honestly the part I care about most, because the whole point is that when it can't verify something it says so instead of dropping a zero in and pretending that's the answer.

Shape of it is client context, evidence, diagnosis, plan, approval, the actual work, then verification. Anything that writes to a real provider needs explicit approval plus a live access check right before it runs, since the failure mode I was worried about was it confidently doing something to a client's Google listing.

Python and FastAPI, SQLAlchemy on Postgres, server rendered HTML. Slack and Google APIs, GitHub and Vercel adapters. Built with AI tools in the loop.

If you're looking through it, app/report_builder.py and app/client_provider_verification.py are where the evidence and permission boundaries actually live. The tests cover report provenance, provider failures and the approval gates.
