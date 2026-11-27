# SynAirgy project status

Updated: 2026-11-27. Canonical development handoff; historical Notion notes are context.

<!-- progress-state {"checkpoint":"20261127T160043109092Z-e721fb11bee1","source_digest":"e10a0029168d01d0193885646dd683733eb5c146c7a1cfe22cd17172cee28ed7"} -->

## Current task

Completed: shared agent rules, Git-backed checkpoints, check evidence and recovery
guards are implemented, verified and integrated into `main` through PR #5.
Merge: `903aa69b193725bd5243311c1f160f1630116e9a`; baseline was `fa12511`.
This final handoff updates only status and journal; the verified source digest is unchanged.

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
- Final complete run passed: 30 recovery/tooling tests, 99 engine tests, architecture
  and site checks. Atomic event publication prevents partial final JSON; referenced
  check evidence must be staged with its checkpoint.
- Installed the local hook without replacing existing settings (none existed).
- Published every implementation source tree and its journal, verified identical
  tree hashes, merged PR #5 and fetched main back into this clean local checkout.
- Updated the existing Notion passport to link Git as the canonical development
  state, preserving its business history and separate private credentials page.

## Next step

For the next agent: fetch/pull `main`, read AGENTS.md, then run
`python scripts/progress.py resume`. This implementation task is complete.
The next queued business task is cloud launch: first establish the current Render
account/service and Telegram runtime state, using `lead-engine/CLOUD_LAUNCH.md`.
Do not infer an active service from old local October observations or health alone.

## Blockers and questions

- No current runtime/Render deployment has been verified. Old local Telegram
  polling and temporary data from October must not be assumed to survive.
- Commercial launch is a separate task: cloud runtime, funded AI, search, SMTP,
  sandbox payments, public customer delivery and accounting still need verification.
- Existing customer/public-site behavior and commercial flags must be preserved.
- No blocker remains for the development-handoff feature. Local hooks must be
  installed in each clone (existing custom hooks are preserved). Branch-protection
  settings were not changed; instruction adherence and forced history rewrites
  are not an enforcement guarantee. Ignored files/secrets/dependency environments
  and unpushed work are outside Git recovery. Provider agent CLIs were not launched;
  entrypoint formats were checked against their official documentation.

## Verification

- Final source snapshot `e10a0029168d01d0193885646dd683733eb5c146c7a1cfe22cd17172cee28ed7`:
  architecture passed; 30 tooling tests passed; 99 engine tests passed; site passed.
- One existing Starlette/httpx deprecation warning; no product test failure.
- Actual hard-kill → commit → fresh clone recovery passed and retained unknown.
  Stale worktree/index, omitted run evidence, journal mutation/deletion, intermediate
  unjournaled commits, preserved existing hooks and architecture violations tested.
- Worktree, staged index, committed snapshot/range verification and diff whitespace
  checks passed. Earlier results remain in immutable history.
- GitHub PR head `d812040ae79d7e7485e040fa93951b769c051330`:
  Development continuity run 46029247352 succeeded; engine test job 140608522462 in
  run 46029247357 succeeded (99 tests/site); runtime job was skipped as intended.
- A real clean clone of that remote branch recovered all four current-source
  passing checks without old chat, credentials or installed application packages.
  All published source trees were matched against their local tree hashes.
- Final PR head `9b1420e21dc30e401e34b7acae4ad084365cf221`: continuity run
  46029502802 and engine run 46029502818 both completed successfully before merge.
- Merged main `903aa69b193725bd5243311c1f160f1630116e9a`: continuity run
  46029613559, engine run 46029613704 and the existing Pages run 46029613438 all
  succeeded. Later metadata-only commits retain the identical tested source digest.

## External operations

- Repository: https://github.com/DaniilLaureanti/synairgy-ai-site
- Git CLI push readiness check found no shell credential. No remote write occurred.
  Used the existing GitHub connection instead; no new token was requested/copied.
- Completed integration: https://github.com/DaniilLaureanti/synairgy-ai-site/pull/5
  merged as `903aa69b193725bd5243311c1f160f1630116e9a`.
- Completed main CI: https://github.com/DaniilLaureanti/synairgy-ai-site/actions/runs/46029613559
  and https://github.com/DaniilLaureanti/synairgy-ai-site/actions/runs/46029613704
- Existing automatic Pages publication completed in run 46029613438. This is the
  marketing repository's existing deployment, not a Render/business runtime launch.
- Completed Notion link update: https://app.notion.com/p/3bafbfa23fa281a89898e4c565a22b68
- No unresolved deployment, payment or client-contact operation was started by this
  task. Standard CI for any following metadata commit is discoverable by its HEAD
  in GitHub Actions; it must not be confused with the specifically verified runs above.
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
