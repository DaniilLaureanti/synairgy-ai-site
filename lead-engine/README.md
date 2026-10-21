# SynAirgy Lead Engine v2

A resumable commercial workflow built on the existing SynAirgy Python project.
The public marketing website is preserved; this is not the Crosspost project.

## What works

- Google Places discovery or explicit JSON seed import.
- Public-site evidence extraction with bounded, IP-pinned HTTP requests.
- OpenAI Responses API qualification with Structured Outputs and bounded usage.
- Local durable CRM, job queue, event history, dead-letter/blocked states.
- Private HTML concepts and email drafts.
- Verified-recipient SMTP outbox, optional automatic approval, daily limits,
  two follow-ups, reply cancellation and persistent opt-outs.
- One-time Stripe Checkout with server-side catalog prices and idempotency.
- Signature-verified completed/async payment webhooks and private ZIP packages.
- Authenticated FastAPI control plane, CLI, Docker/Compose and CI.

This is a tested **application contour**, not a live revenue guarantee.
See [ARCHITECTURE.md](ARCHITECTURE.md) for guarantees and explicit limitations.
Domain/DNS deployment, mailbox ingestion, autonomous calls/social messages,
free-form AI negotiation and subscriptions are not implemented in this release.
Only the Landing product has an automatic package-generation adapter.

## Local verification

Python 3.12:

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
PYTHONPATH=src python -m synairgy.cli doctor
```

The tests use synthetic `.example` businesses and fake providers. They make no
OpenAI, SMTP or Stripe calls and charge nothing.

## Run

Set runtime secrets through your deployment's secret store or an ignored local
env file. The program reads environment variables; it does not auto-load env
files. Use the confirmed OpenAI key file only in your shell/runtime, never Git.

```sh
export PYTHONPATH=src
python -m synairgy.cli doctor
python -m synairgy.cli serve
```

`ADMIN_TOKEN` must contain at least 32 random characters before the server starts.
By default it binds to `127.0.0.1:8000`. Configure TLS before public access.

Other commands:

```sh
python -m synairgy.cli discover --query 'Barbershop in Hamburg' --limit 5
python -m synairgy.cli discover --seeds /absolute/path/leads.json --limit 5
python -m synairgy.cli worker --max-jobs 20
python -m synairgy.cli worker --loop
python -m synairgy.cli send
python -m synairgy.cli status
python -m synairgy.cli retry JOB_ID
python -m synairgy.cli reconcile-sends
```

A seed record must include a real company name plus website or address. A seed
file is a JSON list; supplying an email does not automatically verify it.

Missing credentials produce a machine-readable `blocked` summary, not a traceback
or a pretend successful discovery. `doctor` reports configuration presence only;
it does not claim that the provider has balance, scopes, or healthy service.

## Control API

All `/api/*` endpoints require `Authorization: Bearer ADMIN_TOKEN`.

- `GET /api/readiness`, `/api/leads`, `/api/jobs`, `/api/messages`, `/api/orders`, `/api/activity`
- `POST /api/leads`: name, website/address, optional email and verified_contact.
- `POST /api/discover`: query, limit.
- `POST /api/worker/tick`, `/api/outreach/tick`
- `POST /api/leads/{id}/verify-contact`: email.
- `POST /api/messages/{id}/approve`
- `POST /api/leads/{id}/reply`: email, interested.
- `POST /api/leads/{id}/checkout`: request_key.
- `POST /api/suppress`: email.
- `POST /api/jobs/{id}/retry`

The reply endpoint must be fed by an authenticated sender-verifying mailbox
adapter or the owner. It is not an unauthenticated public email webhook.

Public, restricted endpoints:

- `GET /healthz`: no secrets or operational details.
- `GET /preview/{unguessable_token}`
- `GET /delivery/{unguessable_token}/{order_id}`
- `GET /unsubscribe/{token}`: confirmation only (safe for link scanners).
- `POST /unsubscribe/{token}`: durable suppression, including one-click POST.
- `POST /webhooks/stripe`: raw body, Stripe signature required.
- Payment return pages: display only; never authorize delivery.

## Runtime environment

See [.env.example](.env.example). Defaults are non-sending, non-live.
Use a restricted Stripe API key with only required Checkout/Product/Price
permissions, plus a separate webhook signing secret. Test with an isolated
Stripe sandbox first. Do not put these secrets in the public repository.

The original catalog prices are retained. No tax automation is silently
enabled: confirm tax registration, final price presentation and invoices before
taking real orders.

## Automation / storage

GitHub Actions runs tests on changes. Production scheduling is inactive until
`ENGINE_ENABLED=1`, `LEAD_ENGINE_URL` and `LEAD_ENGINE_ADMIN_TOKEN` are configured.
It calls a persistent server and does not try to keep a CRM database on a
disposable GitHub runner. Manual workflow runs default to readiness-only.

Use `docker compose up -d --build` with an ignored `.env.local` and a persistent
volume. Configure a reverse proxy/TLS separately. Never expose the SQLite file
or the `data/` folder as a static directory. Back up and restore-test that volume.

Legacy Notion/Telegram scripts remain in `src/` for compatibility but are not
required or implicitly invoked by the new engine.
