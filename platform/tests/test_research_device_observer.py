import unittest
from pathlib import Path
from unittest.mock import patch

from agent_factory.gpu_custody import GpuBinding
from agent_factory.research_device_observer import NvidiaSmiObserver


class DeviceObserverTests(unittest.TestCase):
    def fixture(self):
        binding = GpuBinding('a'*64, 'b'*64)
        observer = NvidiaSmiObserver(Path.cwd() / 'inert-operator-binary', 'c'*64, 'GPU-12345678', binding, 'v1')
        return observer, {'operation': 'launch', 'gpuBinding': binding.to_dict()}

    def test_idle_and_busy(self):
        for apps, expected in ((b'', 'AVAILABLE'), (b'GPU-12345678, 123\n', 'BUSY')):
            observer, request = self.fixture()
            with patch.object(observer, '_query', side_effect=[b'GPU-12345678\n', apps]):
                self.assertEqual(observer(request)['status'], expected)

    def test_release_requires_original_stop_even_when_idle(self):
        observer, request = self.fixture()
        request['operation'] = 'release'
        with patch.object(observer, '_query') as query:
            self.assertEqual(observer(request)['status'], 'UNKNOWN')
            query.assert_not_called()
        request.update(originalStopped=True, stopReceiptSha256='d'*64)
        with patch.object(observer, '_query', side_effect=[b'GPU-12345678\n', b'']):
            self.assertEqual(observer(request)['status'], 'RELEASED')

    def test_ambiguity_and_failure_are_unknown(self):
        for outputs in ([b'GPU-other\n', b''], [b'GPU-12345678\n', b'N/A'],
                        [b'GPU-12345678\n', b'GPU-12345678, 2\nGPU-12345678, 2']):
            observer, request = self.fixture()
            with patch.object(observer, '_query', side_effect=outputs):
                self.assertEqual(observer(request)['status'], 'UNKNOWN')
        with patch.object(observer, '_query', side_effect=TimeoutError):
            self.assertEqual(observer(request)['status'], 'UNKNOWN')

    def test_binary_hash_mismatch_never_spawns(self):
        observer, request = self.fixture()
        with patch('agent_factory.research_device_observer.os.O_NOFOLLOW', 0x20000, create=True), \
             patch('agent_factory.research_device_observer.os.open', return_value=5), \
             patch('agent_factory.research_device_observer.os.close'), \
             patch('agent_factory.research_device_observer.os.fstat') as info, \
             patch('agent_factory.research_device_observer.os.read', side_effect=[b'wrong', b'']), \
             patch('agent_factory.research_device_observer.subprocess.Popen') as spawn:
            info.return_value.st_mode = 0o100700
            info.return_value.st_size = 5
            self.assertEqual(observer(request)['status'], 'UNKNOWN')
            spawn.assert_not_called()

    def test_subprocess_is_pinned_bounded_and_killed_on_overflow(self):
        import hashlib
        observer, _ = self.fixture()
        observer._sha256 = hashlib.sha256(b'binary').hexdigest()
        for overflowing in (False, True):
            with self.subTest(overflowing=overflowing), \
                 patch('agent_factory.research_device_observer.os.O_NOFOLLOW', 0x20000, create=True), \
                 patch('agent_factory.research_device_observer.os.open', return_value=5), \
                 patch('agent_factory.research_device_observer.os.close'), \
                 patch('agent_factory.research_device_observer.os.fstat') as info, \
                 patch('agent_factory.research_device_observer.os.read', side_effect=
                       [b'binary', b''] + ([b'x'*4096]*16 + [b'x'] if overflowing else [b'GPU-12345678\n', b''])), \
                 patch('agent_factory.research_device_observer.selectors.DefaultSelector') as selector, \
                 patch('agent_factory.research_device_observer.subprocess.Popen') as spawn:
                info.return_value.st_mode = 0o100700
                info.return_value.st_size = 6
                process = spawn.return_value.__enter__.return_value
                process.wait.return_value = 0
                process.poll.return_value = None
                selector.return_value.__enter__.return_value.select.return_value = [(1, 1)]
                if overflowing:
                    with self.assertRaises(ValueError):
                        observer._query('--query-gpu=uuid')
                else:
                    self.assertEqual(observer._query('--query-gpu=uuid'), b'GPU-12345678\n')
                process.kill.assert_called_once()
                args, kwargs = spawn.call_args
                self.assertEqual(args[0][0], '/proc/self/fd/5')
                self.assertEqual(kwargs['pass_fds'], (5,))
                self.assertEqual(set(kwargs['env']), {'PATH', 'LANG', 'LC_ALL'})

    def test_subprocess_timeout_is_unknown_and_cleanup_runs(self):
        import hashlib
        observer, request = self.fixture()
        observer._sha256 = hashlib.sha256(b'binary').hexdigest()
        with patch('agent_factory.research_device_observer.os.O_NOFOLLOW', 0x20000, create=True), \
             patch('agent_factory.research_device_observer.os.open', return_value=5), \
             patch('agent_factory.research_device_observer.os.close'), \
             patch('agent_factory.research_device_observer.os.fstat') as info, \
             patch('agent_factory.research_device_observer.os.read', side_effect=[b'binary', b'']), \
             patch('agent_factory.research_device_observer.selectors.DefaultSelector') as selector, \
             patch('agent_factory.research_device_observer.subprocess.Popen') as spawn:
            info.return_value.st_mode = 0o100700
            info.return_value.st_size = 6
            process = spawn.return_value.__enter__.return_value
            process.poll.return_value = None
            selector.return_value.__enter__.return_value.select.return_value = []
            self.assertEqual(observer(request)['status'], 'UNKNOWN')
            process.kill.assert_called_once()

    def test_missing_nofollow_capability_denies_before_open_or_spawn(self):
        observer, request = self.fixture()
        with patch('agent_factory.research_device_observer.os.O_NOFOLLOW', None, create=True), \
             patch('agent_factory.research_device_observer.os.open') as opening, \
             patch('agent_factory.research_device_observer.subprocess.Popen') as spawn:
            self.assertEqual(observer(request)['status'], 'UNKNOWN')
            opening.assert_not_called()
            spawn.assert_not_called()
