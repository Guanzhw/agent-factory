# pyright: reportMissingImports=false
"""Input custody regressions without PostgreSQL, guardian, or ML execution."""
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import test_autoresearch_scientific_children_postgres as fixture
from agent_factory import research_local_driver
from agent_factory.research_staging import _read


@unittest.skipUnless(os.name == 'posix', 'POSIX exact private file modes')
class ScientificFixtureInputTests(unittest.TestCase):
    inputs = fixture.ScientificChildrenPostgresTests.inputs

    def test_all_inputs_remain_private_with_public_default_umask(self):
        token = {'sha256': 'a' * 64, 'sizeBytes': 128}
        with tempfile.TemporaryDirectory() as area:
            root = Path(area)
            old = os.umask(0o022)
            try:
                with patch.object(research_local_driver, 'build_training_bundle', return_value=fixture.generated_bundle()):
                    _, _, pins = self.inputs(root, token)
            finally:
                os.umask(old)
            folder = root / 'inputs'
            files = list(folder.iterdir())
            self.assertEqual(len(files), 6)
            self.assertEqual(len(pins), 3)
            fd = os.open(folder, os.O_RDONLY)
            try:
                for path in files:
                    with self.subTest(name=path.name):
                        info = path.stat()
                        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
                        self.assertEqual(info.st_nlink, 1)
                        self.assertEqual(_read(fd, path.name, info.st_size, collect=True), path.read_bytes())
            finally:
                os.close(fd)
            with self.assertRaises(FileExistsError):
                fixture.write_private_input(files[0], b'cannot overwrite pinned input')
