# Development boundaries

These rules extend, rather than replace, the [site architecture](ARCHITECTURE.md)
and [engine architecture](../lead-engine/ARCHITECTURE.md). The application remains
a buildless static site plus a Python 3.12 modular monolith, SQLModel/SQLite and
FastAPI. This change introduces no product runtime dependency or new service.

| Responsibility | Modules | Dependency direction |
| --- | --- | --- |
| Business invariants/contracts | domain, ports | Standard library; domain reuses existing catalog |
| Data/configuration/pure rendering | models, settings, demos | No application orchestration or transports |
| Transactions and durable work | store | domain, models |
| External I/O | adapters, safe_http, research | Contracts and domain; existing legacy adapters |
| Business orchestration | workflow, outreach | domain, models, ports, demos; injected providers |
| Payments | billing | domain/models/ports/catalog; existing Stripe adapter stays here |
| Market allocation | portfolio | domain/models/ports/research/settings |
| Owner views/transport | console, telegram | console reads models; telegram composes views/portfolio |
| Composition/control plane | api, cli | Compose application/providers; existing local api/cli imports allowed |
| Remote schedule caller | schedule | HTTP client, no local application/store dependency |
| Development tooling | scripts/ | stdlib + Git; no runtime provider imports or live calls |

`scripts/check_architecture.py` parses ASTs, including lazy imports. It rejects
forbidden internal imports, unknown/nested modules needing classification,
provider dependencies in core orchestration, non-stdlib dependencies in pure
modules, unapproved legacy coupling, and provider entrypoint drift. The policy
does not claim to prove SOLID, dynamically loaded dependencies or every transitive
property. Existing exceptions are explicit: `workflow` reuses normalization from
`ai_analyzer`; `portfolio` retains its research adapter; billing retains Stripe;
api/cli compose each other. Do not expand these exceptions silently.

Apply SOLID through useful behavior, not class count. Keep one clear responsibility,
small provider protocols, stable fake/real-provider contracts, and injection at
composition roots. Reuse catalog pricing, Store claims/fencing, idempotency,
validation, retry taxonomy and migration mechanisms. New stages extend these
mechanisms; do not create parallel ones. No network calls inside SQLite write
transactions. No microservice/ORM/framework migration for a tooling task.

Significant changes need a new numbered ADR in `docs/decisions/` before implementation:
context, options, selected decision, consequences, verification and a supersedes
link when appropriate. Changes to schema, direction of dependencies, payment/
delivery semantics, provider contracts, persistent topology and checkpoint format
qualify. Routine fixes need only a checkpoint. Review the documented policy and
negative tests together if a boundary must change.
