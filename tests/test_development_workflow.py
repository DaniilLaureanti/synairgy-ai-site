"""Behavioral recovery tests in disposable repositories; no live services/secrets."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import progress as p
import check_architecture as architecture


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synairgy-progress-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Workflow fixture")
        self.git("config", "user.email", "fixture@example.test")
        self.write(".gitignore", ".env\n__pycache__/\n.progress-status-*\ndocs/progress/events/.pending-*.tmp\n")
        self.write("app.py", "value = 1\n")
        self.write("scripts/progress.py", (ROOT / "scripts/progress.py").read_text())
        self.write(".githooks/pre-commit", (ROOT / ".githooks/pre-commit").read_text())
        (self.root / ".githooks/pre-commit").chmod(0o755)
        sections = ("Current task", "Acceptance criteria", "Completed", "Next step", "Blockers and questions", "Verification", "External operations")
        self.write(p.STATUS, "# Fixture task\n\n<!-- progress-state {} -->\n\n" + "\n".join(f"## {s}\n\nExplicit fixture handoff.\n" for s in sections))
        self.commit("Before progress initialization")
        self.checkpoint()
        self.commit("Initialize progress handoff")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()

    def write(self, path, content):
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)

    def git(self, *args, success=True, root=None):
        result = subprocess.run(["git", "-C", str(root or self.root), *args], capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-m", message)

    def checkpoint(self, scope="worktree", summary="Observed fixture milestone", root=None):
        args = argparse.Namespace(scope=scope, task="Recoverable fixture task", summary=[summary], next="Run the next fixture verification", decision=[], blocker=[], external=[])
        with redirect_stdout(io.StringIO()):
            return p.checkpoint(root or self.root, args)

    def rows(self, root=None):
        return p.records(p.View(root or self.root))

    def run_fixture(self, program, executable=None):
        command = [executable] if executable else [sys.executable, "-c", program]
        with patch.dict(p.CHECKS, {"fixture": (".", command)}), redirect_stdout(io.StringIO()):
            return p.run_check(self.root, "fixture")

    def test_three_views_and_committed_fingerprint_agree(self):
        digests = {p.View(self.root, scope).digest() for scope in ("worktree", "index", "commit")}
        self.assertEqual(len(digests), 1)
        for scope in ("worktree", "index", "commit"):
            self.assertEqual(p.verify(self.root, scope), [])

    def test_stale_worktree_and_missing_staged_checkpoint_are_rejected(self):
        self.write("app.py", "value = 2\n")
        self.assertTrue(p.verify(self.root))
        self.checkpoint()
        self.assertEqual(p.verify(self.root), [])
        self.git("add", "app.py")
        self.assertTrue(p.verify(self.root, "index"))
        self.git("add", p.STATUS, p.EVENTS)
        self.assertEqual(p.verify(self.root, "index"), [])
        self.git("commit", "-m", "Code and progress travel together")
        self.assertEqual(p.verify(self.root, "commit", base=self.base), [])

    def test_partial_staging_distinguishes_index_and_worktree(self):
        self.write("app.py", "value = 2\n")
        self.git("add", "app.py")
        self.write("app.py", "value = 3\n")
        self.checkpoint()
        self.git("add", p.STATUS, p.EVENTS)
        self.assertTrue(p.verify(self.root, "index"))
        self.checkpoint("index")
        self.git("add", p.STATUS, p.EVENTS)
        self.assertEqual(p.verify(self.root, "index"), [])
        self.assertTrue(p.verify(self.root, "worktree"))
        self.git("commit", "-m", "Deliberate partial commit")
        self.assertEqual(p.View(self.root, "commit").read("app.py"), b"value = 2\n")
        self.assertEqual((self.root / "app.py").read_text(), "value = 3\n")

    def test_untracked_source_counts_but_ignored_credentials_do_not(self):
        before = p.View(self.root).digest()
        self.write(".env", "private fixture content")
        self.assertEqual(p.View(self.root).digest(), before)
        self.write("new source with spaces.py", "print('new')\n")
        self.assertNotEqual(p.View(self.root).digest(), before)
        self.assertTrue(p.verify(self.root))
        self.checkpoint()
        self.commit("Include new source")
        self.assertEqual(p.View(self.root).digest(), p.View(self.root, "commit").digest())

    def test_deletion_and_executable_mode_are_detected(self):
        before = p.View(self.root).digest()
        (self.root / "app.py").chmod(0o755)
        self.assertNotEqual(p.View(self.root).digest(), before)
        self.assertTrue(p.verify(self.root))
        (self.root / "app.py").unlink()
        self.checkpoint()
        self.commit("Delete source with a checkpoint")
        self.assertEqual(p.verify(self.root, "commit", base=self.base), [])

    def test_history_mutation_is_not_repaired_by_a_new_checkpoint(self):
        old = next((self.root / p.EVENTS).glob("*.json"))
        data = json.loads(old.read_text())
        data["summary"] = ["Rewritten history"]
        old.write_text(json.dumps(data))
        self.checkpoint()
        self.assertTrue(any("history" in e for e in p.verify(self.root)))
        self.git("add", "-A")
        self.assertTrue(p.verify(self.root, "index"))

    def test_history_deletion_is_rejected(self):
        old = next((self.root / p.EVENTS).glob("*.json"))
        old.unlink()
        self.checkpoint()
        self.assertTrue(any("history" in e for e in p.verify(self.root)))

    def test_checks_record_observed_pass_and_failure(self):
        self.assertEqual(self.run_fixture("raise SystemExit(0)"), 0)
        self.assertEqual(self.run_fixture("raise SystemExit(7)"), 7)
        states = p.check_states(self.rows())
        self.assertEqual([r["outcome"] for r in states], ["passed", "failed"])
        serialized = json.dumps(self.rows())
        self.assertNotIn("raise SystemExit", serialized)
        self.assertNotIn("command", serialized)

    def test_zero_exit_with_source_mutation_remains_unknown(self):
        self.assertEqual(self.run_fixture("from pathlib import Path; Path('app.py').write_text('value = 9\\n')"), 2)
        self.assertEqual(p.check_states(self.rows())[-1]["outcome"], "unknown")
        self.assertEqual(self.rows()[-1]["reason"], "sources_changed_during_check")

    def test_unavailable_check_remains_unknown(self):
        self.assertEqual(self.run_fixture("", executable="__synairgy_nonexistent_executable__"), 2)
        self.assertEqual(p.check_states(self.rows())[-1]["outcome"], "unknown")

    @unittest.skipUnless(os.name == "posix", "SIGKILL fixture requires POSIX")
    def test_hard_interruption_survives_commit_and_fresh_clone_as_unknown(self):
        program = (
            "import sys; from pathlib import Path; sys.path.insert(0, 'scripts'); import progress as p; "
            "p.CHECKS['fixture'] = ('.', [sys.executable, '-c', 'import time; time.sleep(30)']); "
            "p.run_check(Path.cwd(), 'fixture')"
        )
        process = subprocess.Popen([sys.executable, "-c", program], cwd=self.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if any(r["kind"] == "check-start" for r in self.rows()):
                    break
                time.sleep(0.01)
            else:
                self.fail("Check did not persist its start before execution")
        finally:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        self.assertEqual(p.check_states(self.rows())[-1]["outcome"], "unknown")
        self.assertFalse(any(r["kind"] == "check-finish" for r in self.rows()))
        self.checkpoint(summary="Check process killed; outcome unknown; inspect before retrying")
        self.commit("Save interrupted handoff")
        clone = Path(self.temporary.name) / "fresh-clone"
        self.git("clone", "--no-local", str(self.root), str(clone))
        result = subprocess.run([sys.executable, "scripts/progress.py", "resume", "--json"], cwd=clone, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["verification_errors"], [])
        self.assertEqual(state["checks"][-1]["outcome"], "unknown")
        self.assertTrue(state["checks"][-1]["current_sources"])
        self.assertIn("Explicit fixture handoff", (clone / p.STATUS).read_text())

    def test_correction_appends_without_modifying_the_original(self):
        start = p.append(self.root, "check-start", source=p.View(self.root).source(), check="fixture")
        old_bytes = (self.root / p.EVENTS / f"{start['id']}.json").read_bytes()
        p.append(self.root, "check-resolved", source=start["source"], run_id=start["id"], check="fixture", outcome="unknown", evidence="No completion exists; inspection confirms interruption")
        self.assertEqual((self.root / p.EVENTS / f"{start['id']}.json").read_bytes(), old_bytes)
        self.assertEqual(p.check_states(self.rows())[-1]["outcome"], "unknown")

    def test_forged_pass_with_nonzero_exit_is_rejected(self):
        source = p.View(self.root).source()
        start = p.append(self.root, "check-start", source=source, check="fixture")
        p.append(self.root, "check-finish", source=source, run_id=start["id"], outcome="passed", returncode=3, after_digest=source["digest"])
        with self.assertRaises(p.ProgressError):
            self.rows()

    def test_common_credential_value_is_rejected_before_writing(self):
        count = len(self.rows())
        with self.assertRaises(p.ProgressError):
            self.checkpoint(summary="token=" + "fixture_sensitive_value_12345678")
        self.assertEqual(len(self.rows()), count)

    def test_commit_range_detects_an_unjournaled_intermediate_commit(self):
        self.write("app.py", "value = 2\n")
        self.commit("Unjournaled source edit")
        self.checkpoint()
        self.commit("Later repair cannot cover the earlier commit")
        self.assertEqual(p.verify(self.root, "commit"), [])
        self.assertTrue(p.verify(self.root, "commit", base=self.base))

    def test_zero_before_sha_uses_final_commit_parent(self):
        self.assertEqual(p.verify(self.root, "commit", base="0" * 40), [])

    def test_existing_hooks_path_is_preserved(self):
        self.git("config", "core.hooksPath", "existing-hooks")
        with self.assertRaises(p.ProgressError):
            p.install_hooks(self.root)
        self.assertEqual(self.git("config", "--get", "core.hooksPath").stdout.strip(), "existing-hooks")

    def test_existing_default_pre_commit_is_preserved(self):
        hook = self.root / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        with self.assertRaises(p.ProgressError):
            p.install_hooks(self.root)
        self.assertEqual(hook.read_text(), "#!/bin/sh\nexit 0\n")

    def test_real_pre_commit_blocks_stale_index_and_accepts_correct_checkpoint(self):
        with redirect_stdout(io.StringIO()):
            p.install_hooks(self.root)
            p.install_hooks(self.root)  # idempotent for this installation
        self.write("app.py", "value = 2\n")
        self.git("add", "app.py")
        attempt = self.git("commit", "-m", "Must fail", success=False)
        self.assertNotEqual(attempt.returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), self.base)
        self.checkpoint("index")
        self.git("add", p.STATUS, p.EVENTS)
        self.git("commit", "-m", "Reviewed staged source and checkpoint")
        self.assertEqual(p.verify(self.root, "commit"), [])

    def test_unknown_check_name_cannot_execute_a_shell_command(self):
        before = len(self.rows())
        result = subprocess.run([sys.executable, "scripts/progress.py", "run", "arbitrary-command"], cwd=self.root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.rows()), before)

    def test_status_without_required_sections_is_rejected(self):
        self.write(p.STATUS, "<!-- progress-state {} -->\n")
        self.assertTrue(p.verify(self.root))

    def test_atomic_publication_contains_complete_json_and_no_pending_source(self):
        original_link = os.link
        published = []

        def publish(source, destination):
            self.assertFalse(Path(destination).exists())
            self.assertIsInstance(json.loads(Path(source).read_text()), dict)
            self.assertEqual(p.View(self.root).digest(), before)
            original_link(source, destination)
            published.append(destination)

        before = p.View(self.root).digest()
        with patch.object(p.os, "link", publish):
            self.checkpoint()
        self.assertEqual(len(published), 1)
        self.assertFalse(list((self.root / p.EVENTS).glob(".pending-*")))

    def test_failed_publication_does_not_leave_partial_events(self):
        before = len(self.rows())
        with patch.object(p.os, "link", side_effect=OSError("publication failed")):
            with self.assertRaises(OSError):
                self.checkpoint()
        self.assertEqual(len(self.rows()), before)
        self.assertFalse(list((self.root / p.EVENTS).glob(".pending-*")))

    def test_malformed_event_is_reported_without_claiming_a_result(self):
        old = next((self.root / p.EVENTS).glob("*.json"))
        old.write_text("[]\n")
        self.assertTrue(any("Malformed journal" in error for error in p.verify(self.root)))


class ArchitectureTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synairgy-boundaries-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / "lead-engine/src", self.root / "lead-engine/src", ignore=shutil.ignore_patterns("__pycache__"))
        for path in ("CLAUDE.md", "GEMINI.md", ".github/copilot-instructions.md"):
            full = self.root / path
            full.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, full)

    def test_existing_architecture_passes(self):
        self.assertEqual(architecture.validate(self.root), [])

    def test_function_local_dependency_inversion_is_detected(self):
        path = self.root / "lead-engine/src/synairgy/domain.py"
        with path.open("a") as stream:
            stream.write("\ndef illegal():\n    from .store import Store\n")
        self.assertTrue(any("forbidden dependency on store" in e for e in architecture.validate(self.root)))

    def test_orchestrator_provider_import_is_detected(self):
        path = self.root / "lead-engine/src/synairgy/workflow.py"
        with path.open("a") as stream:
            stream.write("\nimport requests\n")
        self.assertTrue(any("provider/transport" in e for e in architecture.validate(self.root)))

    def test_new_module_requires_explicit_classification(self):
        (self.root / "lead-engine/src/synairgy/new_component.py").write_text("pass\n")
        self.assertTrue(any("classify" in e for e in architecture.validate(self.root)))

    def test_model_specific_rule_drift_is_detected(self):
        (self.root / "CLAUDE.md").write_text("@AGENTS.md\nDifferent rules\n")
        self.assertTrue(any("thin shared-instructions" in e for e in architecture.validate(self.root)))


if __name__ == "__main__":
    unittest.main()
