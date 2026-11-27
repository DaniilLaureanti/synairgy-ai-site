# Durable development progress

Start at [AGENTS.md](../../AGENTS.md) and [PROJECT_STATUS.md](../../PROJECT_STATUS.md).
Python 3.12 + Git are sufficient for recovery; Node 24 runs the existing site check.
Install engine test dependencies only when running that suite. All commands below
run from the repository root. The site has no build/bundler step.

```sh
python scripts/progress.py resume
python scripts/progress.py install-hooks
python -m pip install -r lead-engine/requirements-dev.txt
python scripts/progress.py run all
```

Use `resume --json` for a compact machine-readable view of fingerprints and checks.
Recovery never starts the business runtime, reads credentials, sends a message or
retries an external operation. Read status/linked checkpoint before continuing.

## Checkpoint after a milestone and before long/external work

First update the human sections in PROJECT_STATUS.md. Then record the current
sources with explicit, reviewed public facts:

```sh
python scripts/progress.py checkpoint --task 'Current task' \
  --summary 'Observed result and remaining work' \
  --decision 'Decision and ADR link, when applicable' \
  --blocker 'Open question, if any' \
  --external 'Pending external operation: provider name, public ID/URL, next inspection' \
  --next 'One precise executable next step'
python scripts/progress.py verify --scope worktree
```

`--summary`, `--decision`, `--blocker`, `--external` may repeat; only task, summary
and next are required. Mark external operations pending/completed/unknown explicitly,
with IDs if known; before starting, record that the ID is not yet known. Reconcile
an ambiguous provider result by querying its state before retrying. No secrets,
private capability URLs or CRM records in these fields.

Each event is flushed and fsynced in an ignored temporary file, then published
atomically without replacing an existing event. A killed writer can leave an
ignored `.pending-*.tmp`, never a partial final event. Such temporary files can be
removed; they are not history. A checkpoint updates only
the status marker atomically; status prose is deliberately written by the agent.
A crash between event creation and status update is detected by verification.
An abrupt filesystem/power failure still depends on the host filesystem; Git push
is the recovery boundary for another machine. Corrections are new checkpoints or
`check-resolved` events, never edits to old JSON. Keep entries concise and factual.

## Run and reconcile checks

```sh
python scripts/progress.py run architecture
python scripts/progress.py run tooling
python scripts/progress.py run engine
python scripts/progress.py run site
```

Only these fixed check names are executed; there is no arbitrary-shell wrapper.
Normal output goes to the terminal and is not captured in Git. Events record check
name, UTC time, source fingerprint/context HEAD, Python/platform, exit result, and
optional GitHub run URL. Start/finish are separate append-only files. A finish is
passed only with exit 0 on identical source bytes. Missing executable, interruption,
signal termination or changed sources means unknown. Nonzero normal exit means failed.
Missing dependencies therefore fail the check; they are not silently skipped.

After a session dies, `resume` lists starts without finishes as unknown. A rerun
is a new run with its own evidence; it does not rewrite the unknown original.
When evidence about an old run is recovered, append a reconciliation:

```sh
python scripts/progress.py resolve RUN_ID --outcome unknown \
  --evidence 'Runner was terminated; no completion evidence exists. New run ID ... verifies the current snapshot.'
```

Passed/failed reconciliation requires observed evidence on the **original** source
snapshot (e.g. a specific CI run), not a guess or a successful run on newer code.
Environment and external-provider state are outside the digest; a unit test result
is not deployment readiness. There are no live service calls in these catalog checks.

## Stage and commit the same state

```sh
git status --short
# Review and stage the specific intended source files, status, and new event files.
python scripts/progress.py verify --scope index
git commit -m 'Describe the concrete change'
python scripts/progress.py verify --scope commit
git push -u origin YOUR_BRANCH
```

Source fingerprints cover **all** tracked/nonignored files except PROJECT_STATUS.md
and `docs/progress/events/`. Filenames, executable modes and blob contents count;
deleted files disappear. Ignored credentials/runtime data are not read into records.
Git object IDs bind content, and the canonical manifest is SHA-256. No dependency
installation or local data directory is needed to reproduce a committed fingerprint.

Worktree includes nonignored untracked/unstaged edits; index uses only staged blobs;
commit uses only a committed tree. A worktree checkpoint is insufficient if only
part of that tree is staged. For an intentional partial commit, review the staged
diff, use `checkpoint --scope index`, then stage its new event and status marker.
Leave the remaining edits visible and record another worktree checkpoint before
handoff. Do not claim the index's passing checks cover unstaged source differences.

The local hook verifies the index. Installation changes only this clone's local
`core.hooksPath` and refuses if an existing hooksPath or pre-commit hook would be
replaced. Chain the printed verify command into your own hook in that case.
Uninstall only an installation you made: `git config --local --unset core.hooksPath`.
Linked worktrees share some Git config; inspect existing hooks before installing.

CI verifies committed snapshots and append-only history. Its `--base` is the merge
base for PRs or the before SHA for pushes; each first-parent source-changing commit
in that range needs a new matching checkpoint in the same commit. Initial pushes
without a before SHA inspect the last commit against its parent. Changes on a
diverged branch require an explicit fetched merge base, not a guessed parent.

CI check metadata is uploaded as an artifact even on check failure when the runner
can execute finalization. It is not auto-committed. Local check records must be
committed by the agent with the source/status. Hard runner cancellation may prevent
artifact upload: inspect the GitHub run, keep unknown, append the later evidence.

## Handoff contract

The next agent reads only the clone: task + criteria + completed facts + next action
+ blockers + real verification + pending external IDs are in status and its checkpoint.
Run `resume`; reconcile source differences and unknown operations; continue the exact
next action. Before ending, update prose, checkpoint, verify index, commit and push.
Report the branch/commit and whether remote synchronization was actually confirmed.
No tool can recover edits or check output that were never durably saved or pushed.
Use separate worktrees for concurrent agents; the status file is one merge-reviewed
handoff pointer, while separate event files avoid a shared append-file conflict.
