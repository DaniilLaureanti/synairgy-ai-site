#!/usr/bin/env python3
"""Git-backed handoff and bounded check runner. Python 3.12 stdlib only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

EVENTS = "docs/progress/events/"
STATUS = "PROJECT_STATUS.md"
MARKER = re.compile(r"<!-- progress-state (\{[^\n]*\}) -->")
SCHEMA = 1
CHECKS = {
    "architecture": (".", ["{python}", "scripts/check_architecture.py"]),
    "tooling": (".", ["{python}", "-m", "unittest", "discover", "-s", "tests", "-p", "test_development_workflow.py", "-v"]),
    "engine": ("lead-engine", ["{python}", "-m", "pytest", "-q"]),
    "site": (".", ["node", "tests/site-structure.mjs"]),
}
SENSITIVE = re.compile(
    r"sk-(?:proj-)?[A-Za-z0-9_-]{16,}|\b\d{8,12}:[A-Za-z0-9_-]{25,}|"
    r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|https?://[^\s/]+:[^\s/]+@|"
    r"(?i:authorization\s*[:=]\s*bearer\s+\S+|(?:password|api_key|token|secret)\s*=\s*\S{8,})"
)


class ProgressError(ValueError):
    pass


def git(root, *args, data=None, ok=True):
    result = subprocess.run(["git", "-C", str(root), *args], input=data, capture_output=True)
    if ok and result.returncode:
        # Do not copy Git stderr/arguments: they may contain private URLs or values.
        raise ProgressError("Git operation failed; inspect the repository locally.")
    return result


def repository():
    return Path(git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.decode().strip())


def source_path(path):
    return path != STATUS and not path.startswith(EVENTS)


class View:
    """Read exactly one of worktree, index or a committed tree (never mix them)."""

    def __init__(self, root, scope="worktree", ref="HEAD"):
        self.root, self.scope, self.ref = Path(root), scope, ref
        self.head = git(root, "rev-parse", "HEAD").stdout.decode().strip()
        self.entries = {}
        if scope == "commit":
            self.ref = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").stdout.decode().strip()
            rows = git(root, "ls-tree", "-r", "-z", self.ref).stdout.split(b"\0")
            for row in filter(None, rows):
                metadata, path = row.split(b"\t", 1)
                mode, kind, oid = metadata.decode().split()
                if kind != "blob":
                    raise ProgressError("Submodules require an explicit snapshot policy.")
                self.entries[os.fsdecode(path)] = (mode, oid)
        else:
            for row in filter(None, git(root, "ls-files", "--stage", "-z").stdout.split(b"\0")):
                metadata, path = row.split(b"\t", 1)
                mode, oid, stage = metadata.decode().split()
                if stage != "0":
                    raise ProgressError("Resolve the Git index conflict before taking a checkpoint.")
                self.entries[os.fsdecode(path)] = (mode, oid)
            if scope == "worktree":
                paths = set(self.entries)
                paths.update(os.fsdecode(p) for p in git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout.split(b"\0") if p)
                algorithm = git(root, "rev-parse", "--show-object-format").stdout.decode().strip()
                self.entries = {}
                for path in sorted(paths):
                    full = self.root / path
                    try:
                        info = full.lstat()
                    except FileNotFoundError:
                        continue
                    if stat.S_ISLNK(info.st_mode):
                        mode, content = "120000", os.fsencode(os.readlink(full))
                    elif stat.S_ISREG(info.st_mode):
                        mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
                        content = full.read_bytes()
                    else:
                        raise ProgressError("Unsupported file type in snapshot.")
                    oid = hashlib.new(algorithm, b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
                    self.entries[path] = (mode, oid)

    def read(self, path):
        if path not in self.entries:
            raise ProgressError(f"Required repository file is missing: {path}")
        if self.scope == "worktree":
            return (self.root / path).read_bytes()
        return git(self.root, "cat-file", "blob", self.entries[path][1]).stdout

    def digest(self):
        rows = [[p, *self.entries[p]] for p in sorted(self.entries) if source_path(p)]
        return hashlib.sha256(json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()

    def source(self):
        return {"digest": self.digest(), "scope": self.scope, "head": self.ref if self.scope == "commit" else self.head}


def safe(value):
    if SENSITIVE.search(json.dumps(value, ensure_ascii=False)):
        raise ProgressError("Possible secret rejected. Store credentials outside the public progress journal.")
    return value


def append(root, kind, **fields):
    now = datetime.now(timezone.utc)
    identity = now.strftime("%Y%m%dT%H%M%S%fZ-") + uuid4().hex[:12]
    record = safe({"schema": SCHEMA, "id": identity, "kind": kind, "at": now.isoformat(), **fields})
    directory = Path(root) / EVENTS
    directory.mkdir(parents=True, exist_ok=True)
    # Publish a complete event atomically and exclusively. A killed writer cannot
    # leave a truncated final JSON file; ignored pending files are not events.
    path = directory / f"{identity}.json"
    fd, pending = tempfile.mkstemp(dir=directory, prefix=".pending-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, path)  # Same filesystem, no replacement of existing ID.
    finally:
        os.unlink(pending)
    return record


def records(view):
    result = []
    for path in sorted(p for p in view.entries if p.startswith(EVENTS)):
        if not re.fullmatch(re.escape(EVENTS) + r"\d{8}T\d{12}Z-[a-f0-9]{12}\.json", path):
            raise ProgressError("Unexpected file in immutable event directory.")
        try:
            row = json.loads(view.read(path))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProgressError("Invalid journal JSON.") from exc
        if not isinstance(row, dict) or not isinstance(row.get("source"), dict):
            raise ProgressError(f"Malformed journal event: {path}")
        safe(row)
        if row.get("schema") != SCHEMA or row.get("id") != Path(path).stem:
            raise ProgressError("Journal schema or event identity mismatch.")
        if row.get("kind") not in {"checkpoint", "check-start", "check-finish", "check-resolved"}:
            raise ProgressError("Unknown journal event type.")
        if not re.fullmatch(r"[a-f0-9]{64}", row.get("source", {}).get("digest", "")):
            raise ProgressError("Journal event has no valid source fingerprint.")
        if row["kind"] == "checkpoint" and not all(row.get(k) for k in ("task", "summary", "next_step")):
            raise ProgressError("Checkpoint lacks task, facts or next step.")
        if row["kind"] == "check-start" and not isinstance(row.get("check"), str):
            raise ProgressError("Check start lacks a check name.")
        result.append(row)
    starts = {r["id"]: r for r in result if r["kind"] == "check-start"}
    for row in result:
        if row["kind"] in {"check-finish", "check-resolved"}:
            start = starts.get(row.get("run_id"))
            if not start or row["source"]["digest"] != start["source"]["digest"]:
                raise ProgressError("Check completion has no matching start and source.")
            if row.get("outcome") not in {"passed", "failed", "unknown"}:
                raise ProgressError("Invalid check outcome.")
            if row["kind"] == "check-resolved" and not row.get("evidence"):
                raise ProgressError("Reconciliation requires explicit evidence.")
            if row["kind"] == "check-finish" and row["outcome"] == "passed":
                if row.get("returncode") != 0 or row.get("after_digest") != row["source"]["digest"]:
                    raise ProgressError("Passed check must have exit 0 on unchanged sources.")
    return result


def state_marker(view):
    status = view.read(STATUS).decode()
    matches = MARKER.findall(status)
    if len(matches) != 1:
        raise ProgressError("PROJECT_STATUS.md must have exactly one progress-state marker.")
    try:
        marker = json.loads(matches[0])
    except ValueError as exc:
        raise ProgressError("Invalid status marker.") from exc
    if not isinstance(marker, dict):
        raise ProgressError("Status marker must be an object.")
    required = ("Current task", "Acceptance criteria", "Completed", "Next step", "Blockers and questions", "Verification", "External operations")
    if any(f"## {name}\n" not in status for name in required):
        raise ProgressError("PROJECT_STATUS.md is missing a required handoff section.")
    return marker


def verify_one(view, baseline=None):
    errors = []
    try:
        rows = records(view)
        marker = state_marker(view)
        checkpoint = next((r for r in rows if r["id"] == marker.get("checkpoint") and r["kind"] == "checkpoint"), None)
        if not checkpoint or checkpoint["source"]["digest"] != view.digest() or marker.get("source_digest") != view.digest():
            errors.append("Stale checkpoint/status: record the current source snapshot, then stage status and events with the code.")
        if baseline:
            for path, value in baseline.entries.items():
                if path.startswith(EVENTS) and view.entries.get(path) != value:
                    errors.append("Journal history was edited or deleted; restore it and append a correction.")
                    break
            if view.digest() != baseline.digest():
                added = {Path(p).stem for p in view.entries if p.startswith(EVENTS) and p not in baseline.entries}
                if not checkpoint or checkpoint["id"] not in added:
                    errors.append("Source changes require a new checkpoint in this same Git view.")
    except (ProgressError, KeyError, TypeError, UnicodeDecodeError) as exc:
        errors.append(str(exc) if isinstance(exc, ProgressError) else "Malformed handoff data.")
    return errors


def verify(root, scope="worktree", ref="HEAD", base=None):
    if scope != "commit":
        return verify_one(View(root, scope), View(root, "commit"))
    view = View(root, "commit", ref)
    if base and set(base) == {"0"}:
        base = None  # Initial branch push has no before SHA; inspect its final commit.
    if not base:
        parents = git(root, "rev-list", "--parents", "-n", "1", view.ref).stdout.decode().split()
        return verify_one(view, View(root, "commit", parents[1]) if len(parents) > 1 else None)
    base = View(root, "commit", base).ref
    if git(root, "merge-base", "--is-ancestor", base, view.ref, ok=False).returncode:
        raise ProgressError("The validation base must be an ancestor; fetch history and select the merge base.")
    commits = git(root, "rev-list", "--first-parent", "--reverse", f"{base}..{view.ref}").stdout.decode().split()
    errors = verify_one(view)
    # Each source-changing commit must carry its own checkpoint, not a later repair.
    for commit in commits:
        parents = git(root, "rev-list", "--parents", "-n", "1", commit).stdout.decode().split()
        current = View(root, "commit", commit)
        parent = View(root, "commit", parents[1]) if len(parents) > 1 else None
        errors.extend(f"{commit[:12]}: {message}" for message in verify_one(current, parent))
    return errors


def check_states(rows):
    states = {r["id"]: {**r, "outcome": "unknown", "reason": "no completion recorded"} for r in rows if r["kind"] == "check-start"}
    for row in rows:
        if row["kind"] in {"check-finish", "check-resolved"}:
            states[row["run_id"]].update({k: row[k] for k in ("outcome", "reason", "evidence", "returncode") if k in row})
    return list(states.values())


def resume(root, as_json=False):
    view = View(root)
    rows = records(view)
    state = {"worktree": view.digest(), "index": View(root, "index").digest(), "head": View(root, "commit").digest()}
    state["verification_errors"] = verify_one(view, View(root, "commit"))
    state["checks"] = [{"run_id": r["id"], "check": r["check"], "outcome": r["outcome"], "source_digest": r["source"]["digest"], "current_sources": r["source"]["digest"] == view.digest()} for r in check_states(rows)]
    if as_json:
        print(json.dumps(state, indent=2))
    else:
        print(view.read(STATUS).decode())
        print("\nGit snapshot fingerprints (SHA-256):")
        for scope in ("worktree", "index", "head"):
            print(f"  {scope}: {state[scope]}")
        print("\nRecorded checks (a missing finish means UNKNOWN):")
        for row in state["checks"]:
            freshness = "current source" if row["current_sources"] else "different source"
            print(f"  {row['run_id']} {row['check']}: {row['outcome']} ({freshness})")
        for error in state["verification_errors"]:
            print(f"ATTENTION: {error}")
    return state


def checkpoint(root, args):
    view = View(root, args.scope)
    records(view)  # Fail rather than building on malformed history.
    status = (Path(root) / STATUS).read_text()
    if len(MARKER.findall(status)) != 1:
        raise ProgressError("Add the single progress-state placeholder to PROJECT_STATUS.md first.")
    record = append(root, "checkpoint", source=view.source(), task=args.task, summary=args.summary,
                    next_step=args.next, decisions=args.decision, blockers=args.blocker, external_operations=args.external,
                    checks=[{"run_id": r["id"], "check": r["check"], "outcome": r["outcome"]}
                            for r in check_states(records(view)) if r["source"]["digest"] == view.digest()])
    marker = "<!-- progress-state " + json.dumps({"checkpoint": record["id"], "source_digest": view.digest()}, separators=(",", ":")) + " -->"
    updated = MARKER.sub(lambda _: marker, status)
    # Atomic status update. A crash before this leaves a visible verification failure.
    fd, name = tempfile.mkstemp(dir=root, prefix=".progress-status-", text=True)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, Path(root) / STATUS)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print(f"Checkpoint {record['id']} ({args.scope}, {view.digest()})")
    if args.scope == "index":
        print("Stage the new event and PROJECT_STATUS.md; source index was not modified.")
    return record


def run_check(root, name):
    cwd, command = CHECKS[name]
    command = [sys.executable if part == "{python}" else part for part in command]
    source = View(root).source()
    fields = {"source": source, "check": name, "python": sys.version.split()[0], "platform": sys.platform}
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if run_id.isdigit() and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        fields["external_run"] = f"https://github.com/{repo}/actions/runs/{run_id}"
    started = append(root, "check-start", **fields)
    print(f"Check started: {name} / {started['id']} / {source['digest']}", flush=True)
    code, reason, child = None, "completed", None
    try:
        # Only the fixed catalog is accepted; no raw arguments, env or output in Git.
        child = subprocess.Popen(command, cwd=Path(root) / cwd)
        code = child.wait()
    except KeyboardInterrupt:
        reason = "interrupted"
        if child:
            child.send_signal(signal.SIGINT)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    except OSError:
        reason = "could_not_start"
    after = View(root).digest()
    outcome = "unknown" if code is None or code < 0 or after != source["digest"] else ("passed" if code == 0 else "failed")
    if after != source["digest"]:
        reason = "sources_changed_during_check"
    append(root, "check-finish", source=source, run_id=started["id"], check=name,
           outcome=outcome, returncode=code, after_digest=after, reason=reason)
    print(f"Check finished: {name}: {outcome} (exit {code})", flush=True)
    return 0 if outcome == "passed" else (code if code and code > 0 else 2)


def install_hooks(root):
    configured = git(root, "config", "--local", "--get", "core.hooksPath", ok=False).stdout.decode().strip()
    effective = git(root, "config", "--get", "core.hooksPath", ok=False).stdout.decode().strip()
    desired = str(Path(root) / ".githooks")
    if configured == desired and effective == desired:
        print("Project hooks are already installed.")
        return
    legacy = Path(git(root, "rev-parse", "--git-path", "hooks/pre-commit").stdout.decode().strip())
    if not legacy.is_absolute():
        legacy = Path(root) / legacy
    if effective or legacy.exists():
        raise ProgressError("Existing hooks preserved. Chain `python3 scripts/progress.py verify --scope index` in your existing pre-commit hook.")
    git(root, "config", "--local", "core.hooksPath", desired)
    print("Installed the tracked pre-commit hook for this clone only.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("resume")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("--scope", choices=("worktree", "index", "commit"), default="worktree")
    p.add_argument("--ref", default="HEAD")
    p.add_argument("--base")
    p = sub.add_parser("checkpoint")
    p.add_argument("--scope", choices=("worktree", "index"), default="worktree")
    p.add_argument("--task", required=True)
    p.add_argument("--summary", action="append", required=True)
    p.add_argument("--next", required=True)
    for name in ("decision", "blocker", "external"):
        p.add_argument(f"--{name}", action="append", default=[])
    p = sub.add_parser("run")
    p.add_argument("check", choices=(*CHECKS, "all"))
    p = sub.add_parser("resolve")
    p.add_argument("run_id")
    p.add_argument("--outcome", choices=("passed", "failed", "unknown"), required=True)
    p.add_argument("--evidence", required=True)
    sub.add_parser("install-hooks")
    args = parser.parse_args(argv)
    root = repository()
    try:
        if args.action == "resume":
            resume(root, args.json)
        elif args.action == "verify":
            errors = verify(root, args.scope, args.ref, args.base)
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            if errors:
                return 1
            print(f"Progress is current for {args.scope}.")
        elif args.action == "checkpoint":
            checkpoint(root, args)
        elif args.action == "run":
            for name in CHECKS if args.check == "all" else (args.check,):
                code = run_check(root, name)
                if code:
                    return code
        elif args.action == "resolve":
            rows = records(View(root))
            start = next((r for r in rows if r["id"] == args.run_id and r["kind"] == "check-start"), None)
            if not start:
                raise ProgressError("Unknown check run ID.")
            append(root, "check-resolved", source=start["source"], run_id=start["id"], check=start["check"],
                   outcome=args.outcome, evidence=args.evidence)
            print("Reconciliation appended; original evidence retained.")
        elif args.action == "install-hooks":
            install_hooks(root)
    except ProgressError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
