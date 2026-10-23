# Research-led market portfolio

The system starts by investigating a changing set of sectors, then tests several
in parallel. `config.json` has no selected niche. Its initial eight sectors are
research prompts, not recommendations or assertions about where money is.
The web researcher is prompted to discover additional industries on every weekly
refresh, reusing existing keys for known sectors. Only Landing is currently
deliverable automatically; research evaluates demand for that supported product.

## Evidence before company discovery

Each weekly research run uses the existing OpenAI model in two bounded requests:
forced web search (at most six tool calls), followed by schema-constrained
extraction. Both requests consume the existing atomic daily AI-call allowance.
The research date, sector, underlying data date, geographic scope, confidence,
sample size when available, claim and source URL are persisted. Evidence URLs
must belong to the returned source list; future dates are rejected. Source-list
membership establishes provenance, not factual verification of the claim.

Research hypotheses cover demand, trend, ability to pay, digital gaps, service
gaps and fit for a landing page. Missing values are not filled with invented
search volumes or company budgets. National statistics and small samples must
be identified as extrapolations. A service complaint alone does not establish
a problem a website can fix.

A sector needs recent evidence for demand, budget, digital gap and delivery fit
before it can receive capacity. The default maximum data age is 90 days, and
low-confidence evidence (<0.35) is excluded. At least two eligible sectors are
required. Missing/insufficient evidence blocks acquisition instead of reverting
to a default niche. Trusted source-reviewed imports are also accepted through
`POST /api/portfolio/evidence`; that endpoint relies on its authenticated caller
for provenance and does not independently crawl or verify the supplied sources.

## Experiments and feedback

Each allocation period creates sector campaigns with a fixed product/variant
(`landing-v1`). Every newly admitted company gets immutable first-touch
attribution. Rediscovery in another sector leaves the original attribution
unchanged and does not consume another new-company slot. Existing unattributed
leads remain unattributed rather than being assigned retrospectively.

The default period is one week in Europe/Berlin. `cadence: monthly` changes
allocation reviews to calendar months; research still refreshes weekly.
The full decision snapshot persists the input evidence, cohort metrics, policy,
allocation, experiment IDs and reason. Repeated calls in the same period reuse
the snapshot. Historical decisions are not rewritten after late payments.

Operational reports show observed cash and costs immediately. Allocation uses a
separate mature cohort: unique initial SMTP-accepted messages at least 30 days
old and no older than 120 days. Follow-ups are not new contacts, and uncertain
sends are not successful contacts. Replies/interest are deduplicated per lead.
The reply/financial adapters must supply authenticated actual events; no opens,
delivery receipts, replies or sales are inferred from a generated draft.

## Allocation rule

Before winners exist, capacity is spread across up to six researched sectors.
Research quality and low previous exposure guide these pilot weights. New,
under-tested sectors get attention; mature zero-sale or loss-making trials get
a reduced exploration weight. All sectors keep the same offer variant initially
so a sector comparison is not silently mixed with a price/product experiment.

A winner needs at least 30 mature contacts, two net-paying leads and positive
contribution after accounted costs. Counts are configurable policy thresholds,
not a claim of statistical significance. Its campaign accounting must have been
attested complete. New sends or money entries invalidate that attestation.
The ranking shrinks per-contact contribution using 20 additional denominator
contacts to reduce overreaction to tiny samples; it is a ranking heuristic,
not a probability that a sector is best.

Once winners qualify:

- 70% goes to up to two winners, weighted by positive contribution per contact.
- 30% goes to other researched sectors, preferring low-exposure candidates.
- If a lane has no eligible candidates, its share stays reserved.

One capacity unit is **one new company admitted to the pipeline**. For a batch
of 20, the 70/30 split is 14 exploitation and 6 exploration slots. Integer
rounding uses largest remainders. This controls prospecting/qualification
capacity, not exact compute time, cash spend, delivered email or profit.
Outreach retains the global daily cap (including follow-ups), verification,
approval and suppression checks. Qualification and contact availability can make
actual sending proportions differ from intake proportions.

The daily acquisition run searches selected campaign queries, rotates configured
Hamburg districts, imports only its quota of NEW companies and records unused
capacity if the bounded search pool is exhausted. It does not silently redirect
an unused experimental quota into a winner. Daily run keys, leases and first-touch
records prevent duplicate quota consumption after repeats/crashes. Google Places
search is limited to 20 results per sector per run; this is not exhaustive coverage.

## Money and forecasts

Confirmed Stripe payment ingestion appends gross revenue to the attributed
campaign in the same transaction as payment state and fulfillment enqueueing.
Duplicate payment events do not duplicate money. Unpaid/failed checkouts add no
revenue. Unattributed revenue is not credited to an arbitrary market.

The EUR ledger also accepts idempotent acquisition/delivery costs, processor fees,
taxes, refunds and chargebacks. Shared campaign costs are charged conservatively
to the evaluated campaign cohort. Revenue minus refunds, chargebacks and recorded
costs is labelled **recorded contribution**. It becomes verified contribution
only after an authenticated accounting adapter/owner attests completeness.
This is contribution, not a full company P&L with all overhead automatically
allocated. Returning no cost records does not imply zero cost.

Automatic payment revenue works; automatic actual-fee/refund/dispute, API-cost,
fulfillment-cost and tax imports still require accounting integrations. Until
those exist, accounting must be recorded/attested explicitly and the portfolio
stays experimental if cost completeness is unknown. This dependency must not be
described as a fully autonomous profit optimizer already running in production.

The report includes an observed payment rate and a descriptive Wilson interval
for mature contacts; zero contacts returns no rate/interval. These intervals
do not correct for adaptive selection or predict future margins. No projected
monthly earnings are fabricated from search trends, unqualified leads or drafts.

## Operations

`PORTFOLIO_ENABLED=1` enables the portfolio path, not live outreach. An empty
scheduled query invokes the portfolio. An explicit manual query is an override
whose untagged leads are excluded from sector comparisons. Cloud runtime,
provider credentials/balance, mailbox ingestion and delivery integrations retain
the activation requirements in SETUP.md.

Research and daily intake use leased, fenced run records. Quota/auth/balance
errors stay blocked instead of being retried daily in the same research period;
use the authenticated retry endpoint after correcting the root cause. A stale
worker cannot commit evidence or replace a completed result. Financial and
portfolio control endpoints require the same administrative authentication.

Schema v2 adds tables without rewriting v1 leads, jobs, messages or orders.
The current store uses schema v3, adding owner-console/control tables on top of
that portfolio schema; v1/v2 upgrades remain additive.
Keep a consistent SQLite backup before upgrade. Tests cover v1 preservation,
backup restoration and refusal of unknown schemas before any new DDL.

Implementation references: [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search),
[Responses limits](https://developers.openai.com/api/reference/python/resources/responses/methods/create).
