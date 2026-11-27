# Shared agent instructions

This is the canonical instruction file for every model. Provider entry files only
import/link this file. Task state lives in [PROJECT_STATUS.md](PROJECT_STATUS.md)
and the append-only [progress journal](docs/progress/README.md), not in a chat.

## Start or recover

1. Read this file, `PROJECT_STATUS.md`, its referenced checkpoint, and the relevant
   architecture documentation. Run `python scripts/progress.py resume` from the
   repository root. Read unknown checks and pending external operations before retrying.
2. Inspect `git status --short`, branch, HEAD, index and worktree. Preserve others'
   work; never reset, clean, force-push or overwrite it to make checks pass.
3. Confirm the current task, acceptance criteria and exact next step in the status
   file. Check current repository/provider evidence before treating historical
   runtime observations as current. Do not require a previous conversation.
4. Use Python 3.12 and Node 24 (site check); install existing dev dependencies with
   `python -m pip install -r lead-engine/requirements-dev.txt`. No site build exists.
   `python scripts/progress.py install-hooks` enables the local hook without
   replacing existing hook settings. See `docs/progress/README.md` for conflicts.

## Develop and decide

- Preserve the buildless HTML/CSS/ES-module site and existing public URLs.
- The Python application is a modular monolith, single persistent SQLite host.
  Read `docs/ARCHITECTURE.md`, `lead-engine/ARCHITECTURE.md` and
  `docs/DEVELOPMENT_ARCHITECTURE.md`; the latter defines enforceable import boundaries.
- Reuse the catalog, domain invariants, Store transactions/leases/outbox, provider
  ports, settings and existing tests. Do not create a second CRM, pricing source,
  delivery state machine or retry system. Keep network I/O outside write transactions.
- Apply SOLID pragmatically: one clear module responsibility; extend stages through
  existing small contracts; preserve fake/real provider behavior and error contracts;
  inject I/O at composition roots. Add an abstraction only for a concrete need.
- Before changing boundaries, schema, deployment topology, provider contracts or
  commercial semantics, append an ADR in `docs/decisions/` with context, alternatives,
  decision, consequences and verification. Link it from a checkpoint; supersede old
  decisions rather than silently rewriting their history.
- Secrets and runtime data stay outside Git and journals. This public repository
  must contain no credentials, capability links, private leads or terminal dumps.
  The owner's separately authorized private Notion credential backup is not a Git
  handoff store. Do not read credentials for ordinary development/checks.
- A documentation/tooling task does not authorize deployment, paid provisioning,
  messages to clients, live charges or enabling runtime commercial flags.

## Check and checkpoint

- Use `python scripts/progress.py run all` or an appropriate catalog check
  (`architecture`, `tooling`, `engine`, `site`). Each writes start and finish events,
  source fingerprint and exit result, never raw arguments/output/environment.
- A start without completion is **unknown**, including after a killed session.
  Inspect evidence and append `resolve` or run a new check; never infer a pass.
  A result on different sources does not validate current code. A check is not a
  live service test. See the progress guide for exact recovery commands.
- Update status + append a checkpoint after each substantial milestone, before a
  long check or external action, and before ending the session. Include facts,
  decisions, blockers, next action and external operation IDs/URLs when available.
  Persist the pre-operation checkpoint to Git before an expensive/irreversible action.
- Do not edit or delete journal events. Add corrections as new events. Record the
  source snapshot after edits; do not touch an old entry to make it look current.
- Before committing: run `verify --scope worktree`, stage the intended code **with**
  status and new events, then `verify --scope index`. For partial staging use
  `checkpoint --scope index` after reviewing staged content and stage its state files.
  An index checkpoint does not validate unstaged work. Never use `git add .` blindly.
- CI checks committed history and dependency boundaries; preserve existing CI and
  runtime settings. New source-changing commits must each include a new checkpoint.

## Handoff

Update the visible status, append the final checkpoint, run index verification and
commit code, state and journal together. Push the authorized branch when access
allows; otherwise state explicitly that changes are local. A different computer
receives only pushed commits, not a local worktree or temporary environment.
Record PR/run/deployment IDs and unresolved outcomes before stopping. Report actual
checks, limitations, commit/branch/remote state and the next executable action.
Notion may link this Git state; it must not become a competing development status.
