# SynAirgy project status

Updated: 2026-11-27. Canonical development handoff; historical Notion notes are context.

<!-- progress-state {"checkpoint":"20261127T155004652631Z-e473b4714de4","source_digest":"7acaa8306fcc78e08afca12594590843887081d3ad3460ee22bc0edcc1b0476d"} -->

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
- Added initial shared entry files and stdlib progress runner.

## Next step

Finish dependency checks, recovery tests and CI integration; then run the full
offline suite, checkpoint, commit, push and verify the remote result.

## Blockers and questions

- No current runtime/Render deployment has been verified. Old local Telegram
  polling and temporary data from October must not be assumed to survive.
- Commercial launch is a separate task: cloud runtime, funded AI, search, SMTP,
  sandbox payments, public customer delivery and accounting still need verification.
- Existing customer/public-site behavior and commercial flags must be preserved.

## Verification

- Repository inspection only. Historical 99-test result is not a result of this task.
- New checks have not run yet. Check events below are the machine-readable evidence.

## External operations

- None started for this task. Repository: https://github.com/DaniilLaureanti/synairgy-ai-site
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
