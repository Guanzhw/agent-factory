"""Real temporary filesystem output checks; no PG, process or evaluator launch."""
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent_factory.local_compute import LocalWorkspaceProvider
from agent_factory.process_enforcement import ProcessLimits
from agent_factory.process_provider import ProcessResourceProvider


@unittest.skipUnless(sys.platform == 'linux', 'Linux descriptor-pinned process output reader required')
class ComparisonOutputCustodyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='comparison-output-custody-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / 'provider'
        self.root.mkdir(mode=0o700)
        self.lease = self.root / 'original-lease'
        self.lease.mkdir(mode=0o700)
        self.output = self.lease / 'custody.output'
        self.output.write_bytes(b'{"synthetic":"completed"}\n')
        self.output.chmod(0o600)
        info = self.lease.stat()
        self.record = {'released': True, 'directoryIdentity': [info.st_dev, info.st_ino]}
        self.snapshot = {'state': 'COMPLETED', 'exitCode': 0, 'stoppedProof': True, 'capacityHeld': False}
        self.provider = object.__new__(ProcessResourceProvider)
        self.provider.limits = ProcessLimits(file_size_bytes=1024)
        self.provider._root_guard = LocalWorkspaceProvider(SimpleNamespace(), self.root)
        self.provider.root = self.root

        @contextmanager
        def transaction():
            yield None

        @contextmanager
        def adapter(record):
            self.assertIs(record, self.record)
            yield None, self.snapshot

        self.load = Mock(return_value=self.record)
        self.addCleanup(patch.stopall)
        patch.object(self.provider, '_transaction', transaction).start()
        patch.object(self.provider, '_load', self.load).start()
        patch.object(self.provider, '_adapter', adapter).start()

    def read(self):
        return self.provider.read_completed_output('original-lease', 'alice')

    def test_original_released_success_returns_exact_bytes_with_owner_lookup(self):
        self.assertEqual(self.read(), b'{"synthetic":"completed"}\n')
        self.load.assert_called_once_with(None, 'original-lease', 'alice')

    def test_unknown_nonzero_or_nonreleased_refuses_before_output_read(self):
        for update in ({'state': 'UNKNOWN'}, {'exitCode': 3}, {'stoppedProof': False}, {'state': 'CANCELLED'}):
            original = dict(self.snapshot)
            self.snapshot.update(update)
            with self.subTest(update=update), patch('agent_factory.process_provider.os.read') as read:
                with self.assertRaises(ValueError):
                    self.read()
                read.assert_not_called()
            self.snapshot = original
        self.record['released'] = False
        with self.assertRaises(ValueError):
            self.read()

    def test_symlink_directory_and_fifo_cannot_be_read_as_result(self):
        self.output.unlink()
        outside = self.base / 'outside'
        outside.write_bytes(b'outside bytes must not be read')
        self.output.symlink_to(outside)
        with self.assertRaises((OSError, ValueError)):
            self.read()
        self.output.unlink()
        self.output.mkdir(mode=0o700)
        with self.assertRaises((OSError, ValueError)):
            self.read()
        self.output.rmdir()
        getattr(os, 'mkfifo')(self.output, 0o600)
        original_open = os.open
        with patch('agent_factory.process_provider.os.open', wraps=original_open) as opened:
            with self.assertRaises(ValueError):
                self.read()
            calls = [call for call in opened.call_args_list if call.args[0] == 'custody.output']
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0].args[1] & getattr(os, 'O_NONBLOCK'))

    def test_hardlinks_oversize_empty_and_public_mode_rejected(self):
        os.link(self.output, self.lease / 'alias')
        with self.assertRaises(ValueError):
            self.read()
        (self.lease / 'alias').unlink()
        for raw in (b'x' * 1025, b''):
            self.output.write_bytes(raw)
            with self.assertRaises(ValueError):
                self.read()
        self.output.write_bytes(b'valid-sized')
        self.output.chmod(0o644)
        with self.assertRaises(ValueError):
            self.read()

    def test_lease_directory_replacement_never_adopts_new_output(self):
        self.lease.rename(self.root / 'retained-original')
        self.lease.mkdir(mode=0o700)
        self.output.write_bytes(b'foreign replacement')
        self.output.chmod(0o600)
        with self.assertRaises(ValueError):
            self.read()

    def test_original_provider_root_identity_is_required(self):
        self.root.rename(self.base / 'retained-provider')
        self.root.mkdir(mode=0o700)
        self.lease.mkdir(mode=0o700)
        self.output.write_bytes(b'foreign replacement')
        self.output.chmod(0o600)
        with self.assertRaises(ValueError):
            self.read()

    def test_write_during_read_cannot_be_returned_as_stable_output(self):
        original_read = os.read
        def changing_read(fd, maximum):
            raw = original_read(fd, maximum)
            with self.output.open('ab') as writer:
                writer.write(b'changed')
            return raw
        with patch('agent_factory.process_provider.os.read', side_effect=changing_read):
            with self.assertRaises(ValueError):
                self.read()


if __name__ == '__main__':
    unittest.main()
