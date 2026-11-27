# ADR 0001: Git is the development handoff source

Status: accepted, 2026-11-27. Scope: development workflow, not operational CRM.

## Context

The public repository has a buildless site, Python engine, tests and GitHub Actions.
Task history was in chat/Notion and temporary workspaces could disappear. Every
model must recover the task without those environments or a previous chat.

## Options

1. Model-specific memory copies: simple, but instructions and task state diverge.
2. External task service: adds access/deployment requirements and cannot ship with code.
3. Git-tracked shared instructions, visible status and immutable event files: works
   offline, reviewable and travels with each source change. Selected.

## Decision

AGENTS.md owns instructions. Provider files only import/link it. PROJECT_STATUS.md
owns the human handoff and points to one immutable checkpoint. Individual JSON
events in `docs/progress/events/` preserve facts, check starts, completions and
reconciliation. Corrections append events. No central mutable database is needed.

Each source version is a SHA-256 of sorted path/mode/Git-blob-identity tuples.
Only status and event files are excluded to avoid self-referential hashes. All
other tracked and nonignored untracked files, including docs/tooling/config, count.
Commit, index and worktree are distinct views. A checkpoint records its context
HEAD and source digest, not a guessed future commit SHA. The digest binds dirty
sources to their eventual commit without a circular commit-hash reference.

Fixed check names log starts before launch and finishes only with observed results.
No finish means unknown. Exit zero with changed source means unknown. Records
contain no shell arguments, environment values or terminal output. Free-text
summaries are intentional public facts and are screened for common credentials.
This screen supplements human review; it cannot recognize every secret.

Local pre-commit verifies the actual index, preserving existing hook settings.
CI verifies committed state and every first-parent commit in the requested range.
CI uses the same runner and uploads metadata artifacts rather than auto-committing
from an untrusted PR. Deployment schedules and runtime flags retain their behavior.

## Consequences and limits

Agents must update status, checkpoint and synchronize Git; instructions cannot
force every model/tool to do so. Local hooks are opt-in and bypassable; requiring
the CI job in branch protection is a separate repository setting. Git history is
the integrity authority, not an adversarial tamper-proof audit ledger. A forced
history rewrite or simultaneous writers sharing one index is outside the guarantee;
use separate worktrees/branches, review merges and rerun checks on the merged sources.
Ignored files, dependencies, OS and credentials are outside the source digest.
Checkout line endings/executable bits may change a worktree digest: inspect the
difference, do not pretend a historical check tested it. Preserve exact repository
bytes (normal Linux checkout is tested).

Uncommitted/local-only records can disappear with a machine/session. Commit before
long work and push before losing the environment when authorized. CI artifacts can
be absent after a hard runner shutdown and have retention limits; consult the
GitHub run ID, retain unknown outcomes, append reconciliation later.

## Verification

Isolated Git fixtures exercise worktree/index/commit separation, immutable events,
check success/failure/source mutation, hard interruption, fresh-clone recovery,
hook preservation/enforcement, commit-range gaps, and architecture violations.
The existing engine/site suites remain the product regression checks.
