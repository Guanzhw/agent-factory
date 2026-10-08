"""Synthetic full-copy materialization; no installs, model or external file access."""
from contextlib import redirect_stderr, redirect_stdout
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('site_copy', Path(__file__).parents[2] / 'scripts/copy_install_site.py')
assert spec is not None and spec.loader is not None
copy = importlib.util.module_from_spec(spec); spec.loader.exec_module(copy)


@unittest.skipUnless(os.name == 'posix', 'Nofollow private full copy is POSIX only')
class FullCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.destination = self.root / 'installed-staging', self.root / 'site-packages'
        self.source.mkdir(mode=0o700)
        (self.source / 'package').mkdir(mode=0o755)
        (self.source / 'package/empty.py').write_bytes(b'')
        (self.source / 'package/module.py').write_bytes(b'original module bytes')
        (self.source / 'binary').write_bytes(b'synthetic executable'); (self.source / 'binary').chmod(0o755)
        self.old = self.root / 'original-env'; self.old.mkdir(mode=0o700)
        self.marker = self.old / 'config-attempt'; self.marker.write_bytes(b'old evidence unchanged')
        self.before = {str(p): (copy.stamp(p.stat()), p.read_bytes() if p.is_file() else None)
                       for p in [self.source, *self.source.rglob('*'), self.old, self.marker]}
        self.free = lambda path: SimpleNamespace(free=copy.MAX_BYTES * 3)
        self.disk_patch = patch.object(copy.shutil, 'disk_usage', side_effect=self.free)
        self.disk_patch.start(); self.addCleanup(self.disk_patch.stop)

    def assert_originals(self):
        after = {name: (copy.stamp(Path(name).stat()), Path(name).read_bytes() if Path(name).is_file() else None)
                 for name in self.before}
        self.assertEqual(after, self.before)

    def test_full_copy_no_reflink_or_hardlink_with_enotsup_platform(self):
        import fcntl
        with patch.object(fcntl, 'ioctl', side_effect=OSError(errno.ENOTSUP, 'synthetic unsupported')) as ioctl, \
                patch.object(os, 'link', side_effect=AssertionError('No hardlink')) as link:
            result = copy.copy_site(self.source, self.destination, disk_usage=self.free)
        ioctl.assert_not_called(); link.assert_not_called()
        self.assertEqual(result['files'], 3)
        self.assertEqual(result['bytes'], sum(p.stat().st_size for p in self.source.rglob('*') if p.is_file()))
        for original in self.source.rglob('*'):
            output = self.destination / original.relative_to(self.source)
            self.assertNotEqual(copy.pin(original.stat()), copy.pin(output.stat()))
            if original.is_file():
                self.assertEqual(original.read_bytes(), output.read_bytes())
                self.assertEqual(output.stat().st_nlink, 1)
                self.assertEqual(output.stat().st_mode & 0o777, 0o700 if original.stat().st_mode & 0o100 else 0o600)
        self.assert_originals()

    def test_only_owner_execute_permission_is_preserved(self):
        (self.source / 'binary').chmod(0o641)
        copy.copy_site(self.source, self.destination, disk_usage=self.free)
        self.assertEqual((self.destination / 'binary').stat().st_mode & 0o777, 0o600)

    def test_insufficient_space_rejects_before_destination_creation(self):
        with self.assertRaisesRegex(copy.CopyRejected, 'INSTALL_COPY_INSUFFICIENT_SPACE'):
            copy.copy_site(self.source, self.destination, disk_usage=lambda _: SimpleNamespace(free=0))
        self.assertFalse(self.destination.exists()); self.assert_originals()

    def test_existing_destination_never_overwritten(self):
        self.destination.mkdir(mode=0o700); existing = self.destination / 'existing'; existing.write_bytes(b'keep')
        with self.assertRaisesRegex(copy.CopyRejected, 'INSTALL_COPY_DESTINATION_EXISTS'):
            copy.copy_site(self.source, self.destination, disk_usage=self.free)
        self.assertEqual(existing.read_bytes(), b'keep'); self.assert_originals()

    def test_source_symlink_and_hardlink_rejected(self):
        bad = self.source / 'alias'; bad.symlink_to('binary')
        with self.assertRaises(copy.CopyRejected): copy.copy_site(self.source, self.destination, disk_usage=self.free)
        bad.unlink(); os.link(self.source / 'binary', bad)
        with self.assertRaises(copy.CopyRejected): copy.copy_site(self.source, self.destination, disk_usage=self.free)
        self.assertFalse(self.destination.exists())

    def test_source_mutation_during_copy_fails_and_removes_only_new_target(self):
        original = copy.os.read; changed = False
        def read(fd, size):
            nonlocal changed
            data = original(fd, size)
            if data and not changed:
                changed = True
                (self.source / 'package/module.py').write_bytes(b'changed by synthetic writer')
            return data
        with patch.object(copy.os, 'read', side_effect=read), self.assertRaises(copy.CopyRejected):
            copy.copy_site(self.source, self.destination, disk_usage=self.free)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.marker.read_bytes(), b'old evidence unchanged')

    def test_destination_content_tamper_detected_and_owned_tree_cleaned(self):
        original = copy.os.rename
        def rename(source, destination, **kwargs):
            original(source, destination, **kwargs)
            fd = os.open(destination, os.O_WRONLY, dir_fd=kwargs['dst_dir_fd'])
            try: os.write(fd, b'tampered')
            finally: os.close(fd)
        with patch.object(copy.os, 'rename', side_effect=rename), self.assertRaises(copy.CopyRejected):
            copy.copy_site(self.source, self.destination, disk_usage=self.free)
        self.assertFalse(self.destination.exists()); self.assert_originals()

    def test_file_bound_and_missing_nofollow_reject_before_copy(self):
        with patch.object(copy, 'MAX_FILE_BYTES', 1), self.assertRaises(copy.CopyRejected):
            copy.copy_site(self.source, self.destination, disk_usage=self.free)
        with patch.object(os, 'O_NOFOLLOW', 0), self.assertRaises(copy.CopyRejected):
            copy.copy_site(self.source, self.destination, disk_usage=self.free)
        self.assertFalse(self.destination.exists()); self.assert_originals()

    def test_cli_safe_receipt_and_errors_no_private_paths(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = copy.main(['--source-root', str(self.source), '--destination-root', str(self.destination),
                              '--receipt', str(self.root / 'receipt.json')])
        self.assertEqual((code, err.getvalue()), (0, ''))
        self.assertEqual(out.getvalue(), 'INSTALL_FULL_COPY_COMPLETED\n')
        receipt = self.root / 'receipt.json'
        self.assertEqual(json.loads(receipt.read_bytes())['kind'], 'INSTALL_FULL_COPY')
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(str(self.root), out.getvalue())
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = copy.main(['--private-canary', str(self.root)])
        self.assertEqual((code, out.getvalue(), err.getvalue()), (2, '', 'INSTALL_FULL_COPY_FAILED\n'))

    def test_receipt_cannot_modify_source_or_destination_tree(self):
        for receipt in (self.source / 'receipt.json', self.destination / 'receipt.json'):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = copy.main(['--source-root', str(self.source), '--destination-root', str(self.destination),
                                  '--receipt', str(receipt)])
            self.assertEqual((code, out.getvalue(), err.getvalue()), (2, '', 'INSTALL_FULL_COPY_FAILED\n'))
        self.assertFalse(self.destination.exists()); self.assert_originals()

    def test_total_entry_bound_includes_file_added_by_last_directory(self):
        source = self.root / 'entry-bound'; source.mkdir(mode=0o700)
        deepest = source / 'a/b/c'; deepest.mkdir(parents=True, mode=0o700)
        (deepest / 'last').write_bytes(b'one file')
        with patch.object(copy, 'MAX_FILES', 2), self.assertRaisesRegex(copy.CopyRejected, 'INSTALL_COPY_BOUND'):
            copy.copy_site(source, self.destination, disk_usage=self.free)
        self.assertFalse(self.destination.exists())

    def test_source_mutation_during_later_destination_hash_is_rejected(self):
        original = copy.hash_fd
        calls = 0
        def hashing(fd, maximum):
            nonlocal calls
            calls += 1
            if calls == 6:  # Three staging hashes, then three final destination hashes.
                (self.source / 'binary').write_bytes(b'late synthetic source change')
            return original(fd, maximum)
        with patch.object(copy, 'hash_fd', side_effect=hashing), \
                self.assertRaisesRegex(copy.CopyRejected, 'INSTALL_COPY_SOURCE_CHANGED'):
            copy.copy_site(self.source, self.destination, disk_usage=self.free)
        self.assertEqual(calls, 6)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.marker.read_bytes(), b'old evidence unchanged')

    def test_already_hashed_destination_mutation_during_later_hash_is_rejected(self):
        original = copy.hash_fd
        calls = 0
        def hashing(fd, maximum):
            nonlocal calls
            calls += 1
            if calls == 6:
                (self.destination / 'binary').write_bytes(b'late synthetic output change')
            return original(fd, maximum)
        with patch.object(copy, 'hash_fd', side_effect=hashing), \
                self.assertRaisesRegex(copy.CopyRejected, 'INSTALL_COPY_CONTENT_CHANGED'):
            copy.copy_site(self.source, self.destination, disk_usage=self.free)
        self.assertEqual(calls, 6)
        self.assertFalse(self.destination.exists()); self.assert_originals()

    def test_free_space_budget_counts_only_new_destination_plus_headroom(self):
        total = sum(p.stat().st_size for p in self.source.rglob('*') if p.is_file())
        required = total + copy.HEADROOM
        with self.assertRaisesRegex(copy.CopyRejected, 'INSTALL_COPY_INSUFFICIENT_SPACE'):
            copy.copy_site(self.source, self.destination, disk_usage=lambda _: SimpleNamespace(free=required - 1))
        self.assertFalse(self.destination.exists())
        result = copy.copy_site(self.source, self.destination, disk_usage=lambda _: SimpleNamespace(free=required))
        self.assertEqual(result['bytes'], total); self.assert_originals()
