# Commercial engine v2 — architecture and operating boundary

## Decisions

This is a **modular monolith**, not ten independently deployed microservices.
The existing Python 3.12 project and Responses API integration are retained.
FastAPI exposes the control plane; SQLModel/SQLite owns operational state.
Each agent is a replaceable stage behind an I/O contract. The public marketing
site and its existing URLs/assets are unchanged. This is separate from Crosspost.

1. `domain.py`: lifecycle, identities, contact and qualification invariants.
2. `ports.py`: inspector/analyzer/sender contracts and provider error taxonomy.
3. `models.py`, `store.py`: persistence and transactional queue/outbox.
4. `workflow.py`: inspect → analyze → demo → draft; paid order → delivery package.
5. `adapters.py`, `safe_http.py`: OpenAI, public-web inspection, SMTP.
6. `outreach.py`: approval, recipient verification, bounded follow-ups and suppression.
7. `billing.py`: server-priced Checkout and signature-verified payment ingestion.
8. `api.py`, `cli.py`: authenticated composition roots and operations.
9. `schedule.py`: GitHub schedules call the persistent runtime, not an ephemeral DB.
10. `research.py`: bounded web research and structured source-linked hypotheses.
11. `portfolio.py`: mature cohorts, money attribution and immutable allocation plans.
12. `console.py`, `telegram.py`: owner-only Russian views, persisted pause controls,
    one-use confirmations, long polling, a leased notification outbox and reports.

Sector selection now precedes discovery. See [PORTFOLIO.md](PORTFOLIO.md) for the
70/30 policy, measurement boundary and accounting dependencies.

The existing catalog is the only price source. Qualification thresholds remain
in `config.json`. Agents cannot change prices or decide that payment happened.
Only `Landing` has a delivery-package adapter; shoots and custom development
are explicitly routed to manual review. No unsupported service is sold as
already implemented. Only one-time billing is implemented in v2.

## Reliability guarantees

- Lead identity and job/message/order request keys have database uniqueness.
- Queue ownership is leased for five minutes, with a fencing token on commit.
- Result, lifecycle change and next queue item commit in one transaction.
- SQLite writes use short `BEGIN IMMEDIATE` transactions. No network work is
  performed while holding a database write transaction.
- Transient tasks retry with exponential delays, at most four attempts; permanent
  errors enter a dead-letter state. Credential/balance failures become blocked.
- Daily AI-call and send-attempt reservations are atomic. They are caps, not
  monetary accounting; provider budget controls are still required.
- Stripe retries use the same order idempotency key and stable request body.
- SMTP has no universal exactly-once guarantee. An ambiguous send is placed in
  `needs_review`; a process crash leaving `sending` requires explicit reconciliation.
- Replies cancel pending follow-ups. Opt-outs have a durable global suppression
  record, including when discovery later encounters the same recipient again.
- At most two follow-ups are generated: days 7 and 30 after the initial send.
- The administrative control API fails closed unless a 32+ character bearer
  token is configured. Configure a TLS reverse proxy and an external rate limit
  before exposing it to the internet.

This SQLite adapter is for a **single persistent host**. It is not a multi-tenant
SaaS or a multi-region queue. Do not deploy separate replicas with separate local
databases. Before that stage, replace the store with a shared PostgreSQL-backed
implementation, explicit migrations and row-level job claims. Introducing
microservices before this requirement exists would add distributed failure modes.

## Data and security boundaries

- Persist `data/` on a real disk/volume and back up the entire directory (DB,
  previews and delivery files). Use SQLite's backup API or stop the process for
  consistent backups. Test restores before production.
- Database schema version 3 adds Telegram/control tables to portfolio v2 without
  changing v1/v2 business records. Startup accepts only new databases or versions
  1/2/3, serializes the
  additive migration, and commits the DDL/version marker together. Unknown
  versions fail before DDL. Migration and SQLite backup/restore tests cover v1
  lead preservation. Keep a consistent backup before upgrading production.
- Never commit runtime data, keys or lead records. The repository is public.
  GitHub Actions uploads no CRM database or detailed prospect report.
- Public-web scraping rejects private/reserved IPs, pins the checked IP for the
  connection, validates each redirect, limits response size and respects robots.
- HTML/model inputs are untrusted. Model output uses Structured Outputs; the
  renderer escapes content and never executes generated code.
- Preview/download tokens are 256-bit capability links: treat them as secrets.
  Pages use no-store/noindex/no-referrer and a restrictive CSP. An unguessable
  link is not identity authentication; add customer sign-in for sensitive data.
- SMTP uses TLS, a verified sender and bounded recipient selection; no identity
  spoofing, CAPTCHA bypass or provider-limit circumvention exists in this code.
- Stripe uses a `StripeClient`, sandbox mode by default, signed raw-body
  webhooks, event-ID deduplication, and server-owned amounts/currencies. Both
  completed and asynchronous payment events are supported. The success page
  never grants delivery. No raw card data touches the application.
- Stripe Tax is not automatically enabled: tax registrations and invoice
  obligations must be configured before commercial launch.

## Implemented versus still external

Implemented and testable locally: import/discovery adapters, durable CRM and
queue, evidence-based qualification, private static concepts, draft/outbox,
SMTP sending and bounded follow-ups, reply/opt-out handling, Checkout adapter,
verified payment ingestion and private ZIP delivery.

`DELIVERY_READY` means **a package exists for review**, not that a customer site
is publicly deployed. Domain purchase, access to an existing domain, DNS changes,
approved business content, legal pages, TLS, customer acceptance and public
deployment still require an authorized deployment/onboarding adapter.

Also not implemented: autonomous phone calls, Instagram/LinkedIn messaging,
automatic mailbox ingestion, free-form AI negotiation, recurring subscriptions,
cross-platform revenue optimization and a customer-facing portal. The `/reply`
endpoint is an authenticated ingestion boundary, not a mailbox reader.

Market research is an API adapter, not pre-populated current market knowledge.
Model ratings remain hypotheses even when a source URL was retrieved. Accounting
imports/attestations require an authenticated adapter or owner: processor fees,
refunds, taxes and delivery costs are not guessed. Without complete accounting,
a sector cannot become a profit winner. Direct refund/dispute ingestion and
automatic actual-cost accounting remain external integrations.

Legacy Notion/Telegram modules remain available, but are no longer mandatory
dependencies of the core pipeline and are not silently called by v2.
The new owner console is separate from the legacy notifier; see
[TELEGRAM_CONSOLE.md](TELEGRAM_CONSOLE.md). It is optional and cannot enable
commercial runtime flags. Reports require a running process, not an active chat.

## Sources checked

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [SQLAlchemy concurrency/versioning](https://docs.sqlalchemy.org/en/21/orm/versioning.html)
- [FastAPI security](https://fastapi.tiangolo.com/reference/security/)
- [Stripe Checkout fulfillment](https://docs.stripe.com/checkout/fulfillment)
- [Stripe webhook verification](https://docs.stripe.com/webhooks)
- [GitHub scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#onschedule)
