# pyright: reportMissingImports=false
"""Filesystem-only regressions for completed ORX log directory races."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import cast
import tempfile
import unittest
from unittest.mock import patch

from agent_factory.openresearch import OpenResearchError
from agent_factory.orx_local import TaskLocalORXAdapter


@unittest.skipUnless(os.name == "posix", "Requires POSIX directory descriptors")
class CompletedLogScopeTests(unittest.TestCase):
    def fixture(self, root):
        scope = root / "task-scope"
        logs = scope / "orx-store" / "run-logs"
        logs.mkdir(parents=True)
        (logs / "run.log").write_bytes(b"original")
        outside = root / "outside"
        outside_logs = outside / "orx-store" / "run-logs"
        outside_logs.mkdir(parents=True)
        (outside_logs / "run.log").write_bytes(b"outside-forbidden")
        adapter = SimpleNamespace(scope=scope, max_output_bytes=64, _id=lambda value: value,
            observe_existing=lambda: {"state": "done", "run_id": "run", "stop_evidence": {"allStopped": True}})
        return cast(TaskLocalORXAdapter, adapter), scope, outside

    def test_parent_replacement_before_open_or_after_pin_cannot_redirect_log(self):
        for relative in (Path("."), Path("orx-store"), Path("orx-store/run-logs")):
            for before_leaf in (False, True):
                with self.subTest(parent=str(relative), before_leaf=before_leaf), tempfile.TemporaryDirectory() as directory:
                    adapter, scope, outside = self.fixture(Path(directory))
                    target = scope / relative
                    replacement = outside / relative
                    trigger = "run.log" if before_leaf else target.name
                    real_open = os.open
                    replaced = False

                    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
                        nonlocal replaced
                        if not replaced and Path(path).name == trigger:
                            target.rename(target.with_name(target.name + "-pinned-original"))
                            target.symlink_to(replacement, target_is_directory=True)
                            replaced = True
                        return real_open(path, flags, mode, dir_fd=dir_fd)

                    with patch("agent_factory.orx_local.os.open", side_effect=racing_open):
                        if before_leaf:
                            result = TaskLocalORXAdapter.read_completed_logs(adapter)
                            self.assertEqual(result.stdout, "original")
                        else:
                            with self.assertRaises(OpenResearchError) as raised:
                                TaskLocalORXAdapter.read_completed_logs(adapter)
                            self.assertEqual(raised.exception.code, "INVALID_OUTPUT")
                    self.assertTrue(replaced, "Race injection must reach the selected open boundary")

    def test_leaf_symlink_swapped_at_open_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, scope, outside = self.fixture(Path(directory))
            real_open = os.open
            replaced = False

            def racing_open(path, flags, mode=0o777, *, dir_fd=None):
                nonlocal replaced
                if Path(path).name == "run.log":
                    leaf = scope / "orx-store/run-logs/run.log"
                    leaf.unlink()
                    leaf.symlink_to(outside / "orx-store/run-logs/run.log")
                    replaced = True
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with patch("agent_factory.orx_local.os.open", side_effect=racing_open):
                with self.assertRaises(OpenResearchError) as raised:
                    TaskLocalORXAdapter.read_completed_logs(adapter)
            self.assertTrue(replaced)
            self.assertEqual(raised.exception.code, "INVALID_OUTPUT")

    def test_external_hardlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, scope, outside = self.fixture(Path(directory))
            leaf = scope / "orx-store/run-logs/run.log"
            leaf.unlink()
            os.link(outside / "orx-store/run-logs/run.log", leaf)
            with self.assertRaises(OpenResearchError) as raised:
                TaskLocalORXAdapter.read_completed_logs(adapter)
            self.assertEqual(raised.exception.code, "INVALID_OUTPUT")

    def test_directory_open_capability_is_required_before_any_open(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter, _, _ = self.fixture(Path(directory))
            for value in (None, 0, "unsupported"):
                with self.subTest(value=value), patch.object(os, "O_DIRECTORY", value, create=True), patch.object(os, "open") as opener:
                    if value is None:
                        delattr(os, "O_DIRECTORY")
                    with self.assertRaises(OpenResearchError) as raised:
                        TaskLocalORXAdapter.read_completed_logs(adapter)
                    self.assertEqual(raised.exception.code, "UNSUPPORTED_PLATFORM")
                    opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
