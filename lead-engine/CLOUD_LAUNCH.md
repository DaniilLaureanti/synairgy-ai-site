# Launch the existing engine on Render

The owner console can be connected locally first; see
[Telegram setup](TELEGRAM_CONSOLE.md). Later the same web service starts its
polling thread with `TELEGRAM_ENABLED=1`, a private bot token and a bound owner.
No second Render service or Telegram webhook is required.

Deployment entry point:

[Deploy SynAirgy](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FDaniilLaureanti%2Fsynairgy-ai-site)

## 1. Create the runtime

Sign in to your Render account, review the Blueprint and its quote, and approve
only after accepting the paid service. It defines one Python 3.12 web service in
Frankfurt (0.5 CPU/512 MB), a 1 GB disk mounted at `/var/data`, a health check and
an automatically generated 256-bit administrative token. At the pricing checked
on 2026-10-21, base compute is $7/month and disk is $0.25/month. Taxes, excess
usage and third-party services are additional. No resources are created merely
by adding the Blueprint to GitHub.

The native Python runtime uses `.python-version` in the repository root. The
service starts on Render's `$PORT` with exactly one worker. Database, previews
and delivery archives use the persistent disk. The application takes its public
HTTPS address from `RENDER_EXTERNAL_URL`; set `PUBLIC_BASE_URL` only when using
an explicitly configured custom domain. No domain purchase is required to start.

There is intentionally no provider-key prompt in the initial Blueprint: deploy
the runtime first, then connect the actual accounts. `ADMIN_TOKEN` is generated
by Render and appears in the service's Environment settings; never place it in
a public URL, a repository, an issue or a chat message. `/healthz` is public;
`/api/*` requires this token. The base URL is an API service, not the marketing
site or an already built administrative dashboard.

Auto-deploys are off. To apply a later merged update, select Manual Deploy for
the service after CI passes. Commercial schedules are separate from code deploys.
One SQLite instance is supported; do not enable replicas. Configure consistent
database backups and verify a restore before paid orders.

## 2. Connect the application accounts

Set the following through Render's private Environment settings, then restart
the service. The repository contains names/examples only, not live credentials.

| Capability | Required configuration | Acceptance check |
| --- | --- | --- |
| Research/AI | Existing approved `OPENAI_API_KEY`, funded API account | A bounded research request completes with sources |
| Company search | `GOOGLE_PLACES_API_KEY` for Places API (New) | A bounded query returns real companies |
| Mail | `SMTP_HOST`, `SMTP_PORT`, username/password where required, `SENDER_EMAIL`, `SENDER_POSTAL_ADDRESS` | One explicitly authorized test recipient receives a message |
| Payments | Restricted sandbox `STRIPE_API_KEY`, endpoint signing `STRIPE_WEBHOOK_SECRET` | A signed test payment creates exactly one attributed order and package |

The existing local project OpenAI key can be transferred through an authorized
private configuration channel; do not create a replacement or paste it in chat.
The last confirmed probe had no API balance. A service key must be configured
on the runtime: a connected ChatGPT plugin does not provide runtime credentials.
Use SMTP 465/587 on the paid service; Render blocks port 25.

Keep `OUTREACH_ENABLED=0`, `AUTO_APPROVE_OUTREACH=0` and `STRIPE_LIVE_MODE=0`
while connecting accounts. `doctor` and `/api/readiness` only check configuration
presence; they do not prove that balances, authentication or delivery work.

## 3. Rehearse the complete transaction

Use an explicitly owned/authorized test business and email recipient, not a
random prospect. Check research, discovery, website inspection, concept links,
draft generation, a controlled test email, an ingested reply, sandbox Checkout,
signed payment ingestion and the delivered ZIP. Then rehearse actual website
publication and customer acceptance through an authorized hosting/domain path.
The ZIP itself does not implement that last step.

Automatic reply reading and actual-cost/refund/dispute accounting still require
adapters; the authenticated reply and money-import routes are the current
boundaries. Record these steps explicitly during an assisted first pilot. The
70/30 optimizer cannot claim verified profit while costs remain unknown.

## 4. Start the first bounded pilot

After the rehearsal and a clear deliverable/price, research several sectors and
review the source-linked hypotheses. Begin with a small batch; keep the current
20 new-company/day and shared send caps until the complete workflow is measured.
The initial business target is one accepted, paid and delivered order, with its
costs recorded. Do not treat queued leads, drafts or checkout creation as sales.

For GitHub scheduling, store the Render URL in `LEAD_ENGINE_URL` and the generated
token in the `lead-engine` environment secret `LEAD_ENGINE_ADMIN_TOKEN`. Run the
workflow with `dry_run=true` first. Enable `ENGINE_ENABLED=1` only after an actual
bounded run works. Daily weekday intake triggers weekly research and weekly (or
configured monthly) allocation reviews; it does not run from the empty server
merely because its health check is green.

References: [Blueprint spec](https://render.com/docs/blueprint-spec),
[Python version](https://render.com/docs/python-version),
[default variables](https://render.com/docs/environment-variables),
[pricing](https://render.com/pricing).
