"""Only tiny synthetic trees and mocked FICLONE; never clone an installation."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_spec = importlib.util.spec_from_file_location('environment_clone', Path(__file__).resolve().parents[2] / 'scripts/clone_research_environment.py')
assert _spec and _spec.loader
clone = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clone)


@unittest.skipUnless(sys.platform == 'linux', 'Descriptor clone is Linux only')
class CloneTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / 'source'; self.source.mkdir()
        self.parent = self.root / 'private'; self.parent.mkdir(mode=0o700)
        (self.source / 'module.py').write_bytes(b'fixed source\n')
        (self.source / 'package').mkdir()
        (self.source / 'package/data').write_bytes(b'data')

    @staticmethod
    def fake_clone(dst, src):
        # Mock kernel action, never a production fallback implementation.
        os.lseek(src, 0, os.SEEK_SET)
        os.write(dst, os.read(src, 1024))

    def run_clone(self, action=None):
        with patch.object(clone, 'reflink', side_effect=action or self.fake_clone):
            return clone.clone(self.source, self.parent)

    def test_original_hardlinks_become_separate_private_files_and_receipt(self):
        os.link(self.source / 'module.py', self.source / 'alias.py')
        source_stat = (self.source / 'module.py').stat()
        value = self.run_clone()
        self.assertEqual(value['status'], 'SEALED')
        self.assertFalse(value['environmentAdmitted'])
        self.assertNotIn(str(self.root), json.dumps(value))
        [target] = list(self.parent.iterdir())
        receipt = json.loads((target / clone.RECEIPT).read_bytes())
        self.assertEqual(receipt['sourceRoot'], str(self.source))
        self.assertEqual(receipt['destinationRoot'], str(target))
        self.assertEqual(value['fileCount'], 3)
        self.assertEqual((self.source / 'module.py').stat().st_ino, source_stat.st_ino)
        self.assertEqual((self.source / 'module.py').stat().st_nlink, 2)
        inodes = []
        for path in (target / 'alias.py', target / 'module.py', target / 'package/data'):
            info = path.stat(); inodes.append(info.st_ino)
            self.assertEqual(info.st_nlink, 1)
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            self.assertNotEqual(info.st_ino, source_stat.st_ino)
        self.assertEqual(len(set(inodes)), 3)
        self.assertEqual(stat.S_IMODE((target / clone.RECEIPT).stat().st_mode), 0o600)
        self.assertFalse((target / clone.PENDING).exists())

    def test_ioctl_only_failure_retains_unsealed_partial_without_fallback(self):
        with patch('fcntl.ioctl', side_effect=OSError('untrusted path')) as ioctl:
            value = clone.worker(str(self.source), str(self.parent))
        self.assertEqual(value['errorCode'], 'REFLINK_UNAVAILABLE')
        self.assertNotIn('untrusted', json.dumps(value))
        self.assertEqual(ioctl.call_args.args[1], clone.FICLONE)
        [target] = list(self.parent.iterdir())
        self.assertFalse((target / clone.RECEIPT).exists())
        self.assertEqual(sum(p.stat().st_size for p in target.rglob('*') if p.is_file()), 0)

    def test_symlink_roots_entries_and_special_files_rejected(self):
        (self.source / 'link').symlink_to('module.py')
        with self.assertRaises((clone.CloneError, OSError)):
            self.run_clone()
        self.assertEqual(list(self.parent.iterdir()), [])
        (self.source / 'link').unlink()
        alias = self.root / 'alias'; alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(OSError):
            clone.clone(alias, self.parent)
        getattr(os, 'mkfifo')(self.source / 'fifo')
        with self.assertRaises(clone.CloneError):
            self.run_clone()

    def test_parent_not_private_and_destination_under_source_rejected(self):
        self.parent.chmod(0o755)
        with self.assertRaises(clone.CloneError):
            self.run_clone()
        nested = self.source / 'nested'; nested.mkdir(mode=0o700)
        with self.assertRaises(clone.CloneError):
            clone.clone(self.source, nested)

    def test_changed_source_bytes_namespace_and_root_are_not_sealed(self):
        for mutation in ('bytes', 'namespace', 'root'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                base = Path(temp); source = base / 'source'; source.mkdir()
                parent = base / 'out'; parent.mkdir(mode=0o700)
                (source / 'a').write_bytes(b'abc')
                def action(dst, src):
                    self.fake_clone(dst, src)
                    if mutation == 'bytes':
                        (source / 'a').write_bytes(b'xyz')
                    elif mutation == 'namespace':
                        (source / 'added').write_bytes(b'new')
                    else:
                        source.rename(base / 'old'); source.mkdir()
                with patch.object(clone, 'reflink', side_effect=action), self.assertRaises(clone.CloneError):
                    clone.clone(source, parent)
                self.assertFalse(any(path.name == clone.RECEIPT for path in parent.rglob('*')))

    def test_mutation_during_final_hash_pass_cannot_publish_receipt(self):
        for tree in ('source', 'destination'):
            with self.subTest(tree=tree), tempfile.TemporaryDirectory() as temp:
                base = Path(temp); source = base / 'source'; source.mkdir()
                parent = base / 'out'; parent.mkdir(mode=0o700)
                (source / 'a').write_bytes(b'abc')
                original_scan = clone.scan
                calls = 0
                def scan(fd, *args, **kwargs):
                    nonlocal calls
                    value = original_scan(fd, *args, **kwargs)
                    if os.fstat(fd).st_ino == source.stat().st_ino and kwargs.get('hash_files', True):
                        calls += 1
                        if calls == 2:
                            target = source if tree == 'source' else next(parent.iterdir())
                            (target / 'a').write_bytes(b'xyz')
                    return value
                with patch.object(clone, 'scan', side_effect=scan), patch.object(clone, 'reflink', side_effect=self.fake_clone):
                    with self.assertRaises(clone.CloneError):
                        clone.clone(source, parent)
                self.assertFalse(any(path.name == clone.RECEIPT for path in parent.rglob('*')))

    def test_bad_destination_bytes_or_hardlink_never_sealed(self):
        def wrong(dst, src):
            os.write(dst, b'wrong')
        with self.assertRaises(clone.CloneError):
            self.run_clone(wrong)
        self.assertFalse(any(path.name == clone.RECEIPT for path in self.parent.rglob('*')))

    def test_fixed_limits_and_deadline_deny_before_publication(self):
        for name, limit in [('MAX_FILES', 1), ('MAX_ENTRIES', 1), ('MAX_BYTES', 1), ('MAX_FILE_BYTES', 1), ('MAX_DEPTH', 0)]:
            with self.subTest(name=name), patch.object(clone, name, limit), self.assertRaises(clone.CloneError):
                self.run_clone()
        with patch.object(clone.time, 'monotonic', side_effect=[0, 121]), self.assertRaises(clone.CloneError):
            self.run_clone()
        self.assertFalse(any(path.name == clone.RECEIPT for path in self.parent.rglob('*')))

    def test_existing_clone_never_adopted_and_readonly_executable_mode_preserved(self):
        (self.source / 'module.py').chmod(0o755)
        fixed = '11111111-1111-4111-8111-111111111111'
        with patch.object(clone, 'uuid4', return_value=fixed):
            self.run_clone()
            target = self.parent / ('clone-' + fixed)
            original = (target / clone.RECEIPT).read_bytes()
            with self.assertRaises(FileExistsError):
                self.run_clone()
            self.assertEqual((target / clone.RECEIPT).read_bytes(), original)
            self.assertEqual(stat.S_IMODE((target / 'module.py').stat().st_mode), 0o700)
            self.assertEqual((self.source / 'module.py').stat().st_mode & 0o777, 0o755)

    def test_source_execute_and_special_bits_have_explicit_private_receipt_mapping(self):
        modes = [0o644, 0o744, 0o654, 0o645, 0o4755, 0o2644]
        for index, mode in enumerate(modes):
            path = self.source / ('mode-' + str(index))
            path.write_bytes(b'synthetic executable bytes; not executed')
            path.chmod(mode)
        self.run_clone()
        [target] = list(self.parent.iterdir())
        receipt = json.loads((target / clone.RECEIPT).read_bytes())
        self.assertEqual(receipt['permissionMapping'], 'owner-private-any-execute-v1')
        entries = {entry['path']: entry for entry in receipt['files']}
        for index, mode in enumerate(modes):
            name = 'mode-' + str(index)
            expected = 0o700 if mode & 0o111 else 0o600
            self.assertEqual(stat.S_IMODE((target / name).stat().st_mode), expected)
            self.assertEqual(stat.S_IMODE((self.source / name).stat().st_mode), mode)
            self.assertEqual(entries[name]['sourceMode'], format(mode, '04o'))
            self.assertEqual(entries[name]['destinationMode'], format(expected, '04o'))
        self.assertEqual(entries['package']['destinationMode'], '0700')

    def test_destination_execute_drift_is_rejected_even_if_content_hash_matches(self):
        (self.source / 'module.py').chmod(0o755)
        original_chmod = getattr(os, 'fchmod')
        def strip_execute(fd, mode):
            original_chmod(fd, 0o600)
        with patch.object(clone.os, 'fchmod', side_effect=strip_execute), self.assertRaises(clone.CloneError):
            self.run_clone()
        self.assertFalse(any(path.name == clone.RECEIPT for path in self.parent.rglob('*')))

    def test_empty_files_and_directories_are_preserved_and_reserved_names_refused(self):
        (self.source / 'empty-file').write_bytes(b'')
        (self.source / 'empty-directory').mkdir()
        self.run_clone()
        [target] = list(self.parent.iterdir())
        self.assertEqual((target / 'empty-file').read_bytes(), b'')
        self.assertTrue((target / 'empty-directory').is_dir())
        (self.source / clone.RECEIPT).write_bytes(b'not a receipt')
        with self.assertRaises(clone.CloneError):
            self.run_clone()
        self.assertEqual(len(list(self.parent.iterdir())), 1)

    def test_partial_receipt_not_a_seal(self):
        original = clone.os.write
        def write(fd, data):
            if b'private-reflink-clone-v1' in data:
                raise OSError('simulated storage loss')
            return original(fd, data)
        with patch.object(clone.os, 'write', side_effect=write), self.assertRaises(OSError):
            self.run_clone()
        [target] = list(self.parent.iterdir())
        self.assertTrue((target / clone.PENDING).exists())
        self.assertFalse((target / clone.RECEIPT).exists())

    def test_raw_argument_and_exception_text_not_output(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = clone.main(['--secret-unrecognized=/private/value'])
        self.assertEqual(status, 1)
        self.assertNotIn('/private', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['errorCode'], 'INPUT_INVALID')

    def test_supervisor_rejects_arbitrary_path_in_child_report(self):
        payload = clone.result(files=1, size=1, fingerprint='a' * 64)
        for change in ({'sourceTreeSha256': '/private/value'}, {'fileCount': True},
                       {'errorCode': '/private/value'}, {'interpreterVerified': 0}, {'schema': True}):
            process = MagicMock(returncode=0)
            process.poll.return_value = 0
            process.communicate.return_value = (json.dumps(payload | change).encode(), None)
            with patch.object(clone.subprocess, 'Popen', return_value=process):
                value = clone.supervise('/source', '/private')
            self.assertEqual(value, clone.result('CLONE_FAILED'))
            self.assertNotIn('/private', json.dumps(value))

    def test_supervisor_timeout_and_interruption_stop_original_group(self):
        for error in (subprocess.TimeoutExpired('fixed', 120), KeyboardInterrupt()):
            process = MagicMock(pid=111)
            process.poll.return_value = None
            process.communicate.side_effect = error
            with patch.object(clone.subprocess, 'Popen', return_value=process) as launch, patch.object(clone.os, 'killpg') as kill:
                if isinstance(error, KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        clone.supervise('/source', '/private')
                else:
                    self.assertEqual(clone.supervise('/source', '/private')['errorCode'], 'TIMEOUT')
            kill.assert_called_once_with(111, clone.signal.SIGKILL)
            process.wait.assert_called_once_with(timeout=5)
            self.assertEqual(launch.call_args.kwargs['env'], {'PATH': os.defpath, 'LANG': 'C.UTF-8'})
            self.assertEqual(launch.call_args.args[0][1:3], ['-I', '-B'])


class PlatformTests(unittest.TestCase):
    def test_unsupported_platform_never_starts_worker(self):
        output = io.StringIO()
        with patch.object(clone.sys, 'platform', 'win32'), patch.object(clone.subprocess, 'Popen') as launch, redirect_stdout(output):
            self.assertEqual(clone.main(['--source-root', '/source', '--destination-parent', '/private']), 1)
        self.assertEqual(json.loads(output.getvalue()), clone.result('PLATFORM_UNSUPPORTED'))
        launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
