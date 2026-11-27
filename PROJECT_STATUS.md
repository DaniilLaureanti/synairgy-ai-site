# SynAirgy project status

Updated: 2026-11-27. Canonical development handoff; historical Notion notes are context.

<!-- progress-state {"checkpoint":"20261127T155349582242Z-9b5943c3bc35","source_digest":"e10a0029168d01d0193885646dd683733eb5c146c7a1cfe22cd17172cee28ed7"} -->

## Current task

Implement shared agent instructions, durable checkpoints and recovery checks in
this repository. Branch: `codex/project-continuity-20261127`; baseline main
`fa12511` (includes the Telegram console and subsequent Meta domain verification).

## Acceptance criteria

- Shared root AGENTS.md plus thin Claude/Gemini/Copilot entry files.
- Visible state and append-only Git checkpoints, source-bound check records.
- Detect stale worktree, partially staged index and committed changes; retain
  unknown interrupted checks and reject mutation of journal history.
- Enforce documented Python dependency boundaries without rewriting runtime code.
- Exercise recovery, interrupted commands, hooks and CI; commit and synchronize
  code and journal together where permissions allow.

## Completed

- Recovered repository from GitHub after temporary workspace cleanup.
- Inspected current architecture, Python/Node tests, GitHub Actions and Notion handoff.
- No existing AGENTS.md, task CLI or custom Git hook configuration was present.
- Implemented shared entry files, stdlib progress runner, immutable source-bound
  check events, index-aware pre-commit hook, CI and architecture dependency checks.
- ADR 0001 records the chosen Git handoff design and limits.
- First complete run passed: 26 recovery/tooling tests, 99 engine tests, architecture
  and site checks. Added atomic journal publication and three additional cases
  after review; the final source snapshot still needs a new full run.
- Installed the local hook without replacing existing settings (none existed).

## Next step

Run the final 30 recovery/tooling tests and existing offline suites, then record
the results, push the implementation branch and verify the GitHub checks.

## Blockers and questions

- No current runtime/Render deployment has been verified. Old local Telegram
  polling and temporary data from October must not be assumed to survive.
- Commercial launch is a separate task: cloud runtime, funded AI, search, SMTP,
  sandbox payments, public customer delivery and accounting still need verification.
- Existing customer/public-site behavior and commercial flags must be preserved.

## Verification

- Source snapshot `7acaa8306fcc78e08afca12594590843887081d3ad3460ee22bc0edcc1b0476d`:
  architecture passed; 26 tooling tests passed; 99 engine tests passed; site passed.
- One existing Starlette/httpx deprecation warning; no product test failure.
- The atomic-publication revision is not yet validated; prior results are retained
  in immutable events and do not claim to cover the new source snapshot.
- Intermediate atomic-publication snapshot `d038531d2bcfcc5664f2d12d2d8b5d58f831cafa2c6f96c2041c1b9813212a84`
  passed 29 tooling tests, 99 engine tests and architecture/site checks. Review then
  added enforcement that checkpoints carry their referenced check evidence in Git.

## External operations

- Repository: https://github.com/DaniilLaureanti/synairgy-ai-site
- Git CLI push readiness check found no shell credential. No remote write occurred.
  Use the connected GitHub tools to synchronize the branch and inspect CI; do not
  request or copy a new token for this task. Remote branch/PR IDs are not yet created.
- Prior merged Telegram implementation: PR #4. No deployment or billing operation
  is started by this development-continuity task.

## Business continuation after this task

SynAirgy Lead Engine researches sectors before admitting companies, tests several
sectors and later allocates 70% of new-company intake to evidenced profitable
sectors / 30% exploration. SQLite is the operational CRM; Telegram is the owner UI.
Notion documents: https://app.notion.com/p/3bafbfa23fa281a89898e4c565a22b68
The current Git runtime implements a modular FastAPI/SQLModel monolith and an
optional owner-only Telegram poller. Render configuration is prepared, not evidence
of a running service. `DELIVERY_READY` means a private ZIP exists, not a published
customer site. Read `lead-engine/CLOUD_LAUNCH.md` and `ARCHITECTURE.md` before launch.
Recheck current provider versions/prices and deployment ownership before acting.
