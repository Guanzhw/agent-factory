"""Private synthetic file tests; no real FICLONE or namespaces are exercised."""
import errno
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'probe_research_storage_capabilities.py'
spec = importlib.util.spec_from_file_location('storage_capabilities_probe', SCRIPT)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class MountFactsTests(unittest.TestCase):
    def test_longest_mount_and_no_path_output(self):
        text = ('1 0 1:1 / / rw - overlay hidden rw\n'
                '2 1 1:2 / /private\\040space ro - btrfs secret ro\n')
        self.assertEqual(probe.mount_facts(text, '/private space/child'),
                         {'filesystem': 'btrfs', 'mountReadOnly': True})

    def test_unknown_mount_is_not_inferred(self):
        self.assertEqual(probe.mount_facts('', '/a'),
                         {'filesystem': 'UNKNOWN', 'mountReadOnly': None})


@unittest.skipUnless(sys.platform == 'linux', 'Linux dirfd protocol')
class PrivateProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fd = probe._root(str(self.root))
        self.addCleanup(os.close, self.fd)

    @staticmethod
    def clone_copy(source, destination):
        os.write(destination, getattr(os, 'pread')(source, probe.SIZE, 0))
        return 'CLONED'

    def test_synthetic_clone_flow_cleanup(self):
        with patch.object(probe, '_bounded_clone', self.clone_copy):
            result = probe.private_probe(self.fd)
        self.assertEqual(result, {'status': 'CLONED', 'copyOnWriteVerified': True, 'cleanupComplete': True})
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unsupported_never_falls_back_to_copy(self):
        with patch.object(probe, '_bounded_clone', return_value='UNSUPPORTED'):
            result = probe.private_probe(self.fd)
        self.assertFalse(result['copyOnWriteVerified'])
        self.assertTrue(result['cleanupComplete'])
        self.assertEqual(result['status'], 'UNSUPPORTED')

    def test_false_success_is_detected(self):
        with patch.object(probe, '_bounded_clone', return_value='CLONED'):
            result = probe.private_probe(self.fd)
        self.assertEqual(result['status'], 'ISOLATION_FAILED')
        self.assertTrue(result['cleanupComplete'])

    def test_unconfirmed_stop_retains_owned_files(self):
        with patch.object(probe, '_bounded_clone', side_effect=RuntimeError('STOP_UNCONFIRMED')):
            result = probe.private_probe(self.fd)
        self.assertFalse(result['cleanupComplete'])
        self.assertEqual(result['status'], 'STOP_UNCONFIRMED')
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_foreign_entry_never_deleted(self):
        def inject(source, destination):
            child = next(self.root.iterdir())
            (child / 'foreign').write_bytes(b'not-owned')
            return 'UNSUPPORTED'
        with patch.object(probe, '_bounded_clone', side_effect=inject):
            result = probe.private_probe(self.fd)
        self.assertFalse(result['cleanupComplete'])
        self.assertEqual(next(self.root.iterdir()).joinpath('foreign').read_bytes(), b'not-owned')

    def test_shared_or_symlink_root_rejected(self):
        shared = self.root / 'shared'
        shared.mkdir(mode=0o755)
        shared.chmod(0o755)
        with self.assertRaises(ValueError):
            probe._root(str(shared))
        link = self.root / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            probe._root(str(link))

    def test_replaced_directory_is_not_adopted_for_cleanup(self):
        def replace(source, destination):
            child = next(self.root.iterdir())
            child.rename(self.root / 'original')
            child.mkdir(mode=0o700)
            (child / 'foreign').write_bytes(b'preserve')
            return 'UNSUPPORTED'
        with patch.object(probe, '_bounded_clone', side_effect=replace):
            result = probe.private_probe(self.fd)
        self.assertFalse(result['cleanupComplete'])
        self.assertEqual((self.root / 'original' / 'source').stat().st_size, probe.SIZE)
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_insufficient_scratch_no_clone(self):
        from types import SimpleNamespace
        with patch.object(os, 'fstatvfs', return_value=SimpleNamespace(f_bavail=0, f_frsize=4096)), \
                patch.object(probe, '_read', return_value=''), \
                patch.object(probe, 'private_probe') as clone:
            result = probe.probe(str(self.root))
        clone.assert_not_called()
        self.assertFalse(result['minimumScratchAvailable'])
        self.assertEqual(result['status'], 'INSUFFICIENT_SCRATCH')
        self.assertNotIn(str(self.root), str(result))
        self.assertFalse(result['completeInventoryCloneVerified'])

    def test_errno_allowlist_no_raw_error(self):
        import fcntl
        for code, expected in [(errno.EXDEV, 'UNSUPPORTED'), (errno.EPERM, 'DENIED_OR_FAILED')]:
            with self.subTest(code=code), patch.object(fcntl, 'ioctl', side_effect=OSError(code, 'private text')):
                self.assertEqual(probe._clone(1, 2), expected)

    def test_timeout_kills_original_child_and_reaps(self):
        with patch.object(os, 'fork', return_value=4321), \
                patch.object(probe.select, 'select', return_value=([], [], [])), \
                patch.object(os, 'kill') as kill, \
                patch.object(os, 'waitpid', return_value=(4321, 0)):
            self.assertEqual(probe._bounded_clone(1, 2), 'TIMEOUT')
        kill.assert_called_once_with(4321, probe.signal.SIGKILL)

    def test_interrupt_cleans_original_child(self):
        with patch.object(os, 'fork', return_value=4321), \
                patch.object(probe.select, 'select', side_effect=KeyboardInterrupt), \
                patch.object(os, 'kill') as kill, \
                patch.object(os, 'waitpid', return_value=(4321, 0)):
            with self.assertRaises(KeyboardInterrupt):
                probe._bounded_clone(1, 2)
        kill.assert_called_once_with(4321, probe.signal.SIGKILL)


if __name__ == '__main__':
    unittest.main()
