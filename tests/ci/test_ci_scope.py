"""Stdlib tests for CI routing, real Git rename coverage and required outcomes."""
from contextlib import chdir, redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ci_scope


BEFORE, AFTER = "1" * 40, "a" * 40


class ScopeTests(unittest.TestCase):
    def test_strict_document_allowlist(self):
        for path in (*ci_scope.ROOT_DOCS, ".github/pull_request_template.md", "docs/intro.md", "docs/topic/deep.md"):
            with self.subTest(path=path):
                self.assertTrue(ci_scope.docs_path(path))
        for path in ("notes.md", "README.MD", "apps/README.md", "docs/tool.py", "docs/index.html", "docs.md",
                     ".github/workflows/ci.yml", ".github/ISSUE_TEMPLATE/bug.md", "docs/no-extension"):
            with self.subTest(path=path):
                self.assertFalse(ci_scope.docs_path(path))

    def test_events_select_exact_ranges_and_full_only_by_dispatch(self):
        pull = {"pull_request": {"base": {"sha": BEFORE}, "head": {"sha": AFTER}}}
        push = {"before": BEFORE, "after": AFTER}
        result = subprocess.CompletedProcess([], 0, b"README.md\0docs/with space.md\0")
        for event, body, separator in (("pull_request", pull, "..."), ("push", push, "..")):
            with self.subTest(event=event), patch.object(ci_scope.subprocess, "run", return_value=result) as run:
                self.assertEqual(ci_scope.classify(event, body), ("docs", BEFORE + separator + AFTER))
                self.assertEqual(run.call_args.args[0],
                    ["git", "diff", "--name-only", "-z", "--no-renames", BEFORE + separator + AFTER, "--"])
        with patch.object(ci_scope.subprocess, "run") as run:
            self.assertEqual(ci_scope.classify("workflow_dispatch", None), ("full", None))
            for event in ("schedule", "pull_request_target", "unknown", ""):
                self.assertEqual(ci_scope.classify(event, push), ("fast", None))
            run.assert_not_called()

    def test_missing_new_branch_and_invalid_shas_fall_back_to_fast(self):
        bodies = [None, [], {}, {"created": True, "before": BEFORE, "after": AFTER}]
        bodies += [{"before": value, "after": AFTER} for value in
            (None, "0" * 40, "--option", "a" * 39, "a" * 41, "g" * 40)]
        bodies += [{"before": BEFORE, "after": "0" * 40}]
        with patch.object(ci_scope.subprocess, "run") as run:
            for body in bodies:
                with self.subTest(body=body):
                    self.assertEqual(ci_scope.classify("push", body), ("fast", None))
            for body in ({}, {"pull_request": []}, {"pull_request": {"base": {}, "head": {"sha": AFTER}}}):
                self.assertEqual(ci_scope.classify("pull_request", body), ("fast", None))
            run.assert_not_called()

    def test_empty_mixed_and_failed_diff_never_skip_code_checks(self):
        body = {"before": BEFORE, "after": AFTER}
        for status, raw in ((0, b""), (0, b"README.md\0platform/main.py\0"),
                            (0, b"docs/line\nbreak.py\0"), (128, b"README.md\0")):
            with self.subTest(status=status, raw=raw), patch.object(ci_scope.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], status, raw)):
                self.assertEqual(ci_scope.classify("push", body)[0], "fast")
        with patch.object(ci_scope.subprocess, "run", side_effect=OSError):
            self.assertEqual(ci_scope.classify("push", body), ("fast", None))

    def test_real_git_source_rename_to_docs_still_selects_fast(self):
        with TemporaryDirectory() as directory, chdir(directory):
            def git(*args):
                return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL).decode().strip()
            git("init")
            Path("source.py").write_text("# unchanged bytes\n")
            git("add", ".")
            git("-c", "user.name=CI Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "source")
            before = git("rev-parse", "HEAD")
            Path("docs").mkdir()
            git("mv", "source.py", "docs/moved.md")
            git("-c", "user.name=CI Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "move")
            after = git("rev-parse", "HEAD")
            self.assertEqual(ci_scope.classify("push", {"before": before, "after": after})[0], "fast")

    def test_cli_outputs_os_and_docs_whitespace_failure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            event = root / "event.json"
            event.write_text(json.dumps({"before": BEFORE, "after": AFTER}))
            for name, mode, code, systems in (("push", "docs", 2, ["ubuntu-latest"]),
                    ("workflow_dispatch", "full", 0, ["ubuntu-latest", "windows-latest"])):
                output = root / (mode + ".txt")
                with patch.dict(os.environ, {"GITHUB_EVENT_NAME": name, "GITHUB_EVENT_PATH": str(event),
                        "GITHUB_OUTPUT": str(output)}), redirect_stdout(io.StringIO()), \
                        patch.object(ci_scope.subprocess, "run", side_effect=[
                            subprocess.CompletedProcess([], 0, b"README.md\0"),
                            subprocess.CompletedProcess([], code)]) as run:
                    self.assertEqual(ci_scope.main([]), code)
                    self.assertEqual(output.read_text(), f"mode={mode}\nos={json.dumps(systems)}\n")
                    if mode == "docs":
                        self.assertEqual(run.call_args.args[0], ["git", "diff", "--check", BEFORE + ".." + AFTER, "--"])
                    else:
                        run.assert_not_called()


class SummaryTests(unittest.TestCase):
    @staticmethod
    def needs(mode):
        result = {name: {"result": "skipped" if mode == "docs" else "success"}
            for name in ("frontend", "python", "postgres")}
        return {"scope": {"result": "success", "outputs": {"mode": mode}}, **result}

    def test_expected_docs_fast_full_results_pass(self):
        for mode in ("docs", "fast", "full"):
            with self.subTest(mode=mode):
                accepted, report = ci_scope.summarize(self.needs(mode), "workflow_dispatch" if mode == "full" else "push")
                self.assertTrue(accepted)
                self.assertIn(f"**{mode}**", report)
                self.assertIn("fast checks do not replace full verification", report)
        self.assertFalse(ci_scope.summarize(self.needs("full"), "push")[0])
        for mode in ("docs", "fast"):
            self.assertFalse(ci_scope.summarize(self.needs(mode), "workflow_dispatch")[0])

    def test_failure_cancel_and_unexpected_skip_or_execution_fail(self):
        for mode in ("docs", "fast", "full"):
            original = self.needs(mode)
            for name in ci_scope.JOBS:
                expected = original[name]["result"]
                for result in ("failure", "cancelled", "skipped", "success", None):
                    if result == expected:
                        continue
                    needs = deepcopy(original)
                    needs[name]["result"] = result
                    with self.subTest(mode=mode, job=name, result=result):
                        self.assertFalse(ci_scope.summarize(needs, "workflow_dispatch" if mode == "full" else "push")[0])

    def test_missing_jobs_modes_and_malformed_payload_fail(self):
        for name in ci_scope.JOBS:
            needs = self.needs("fast")
            del needs[name]
            self.assertFalse(ci_scope.summarize(needs, "push")[0])
        for value in (None, {}, [], {"scope": {"result": "success", "outputs": {"mode": []}}}):
            self.assertFalse(ci_scope.summarize(value, "push")[0])
        with TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"CI_NEEDS": "{broken", "GITHUB_STEP_SUMMARY": str(summary)}), \
                    redirect_stdout(io.StringIO()):
                self.assertEqual(ci_scope.main(["--summary"]), 1)
            self.assertIn("CI result: failed", summary.read_text())


if __name__ == "__main__":
    unittest.main()
