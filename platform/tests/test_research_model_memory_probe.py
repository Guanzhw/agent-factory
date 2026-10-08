"""Pure/mock preflight tests: never import Torch or execute generated architecture."""
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).parents[2] / 'scripts' / 'probe_research_model_memory.py'
spec = importlib.util.spec_from_file_location('model_memory_probe', SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ModelMemoryProbeTests(unittest.TestCase):
    def test_report_cannot_claim_factory_or_compiled_training_success(self):
        value = probe.report('untrusted/path/token')
        self.assertEqual(value['errorCode'], 'PROBE_FAILED')
        self.assertFalse(value['factoryExecutionVerified'])
        self.assertFalse(value['scientificConclusionVerified'])
        self.assertFalse(value['compiledTrainingFitVerified'])
        self.assertFalse(value['trainingExecuted'])
        self.assertEqual(value['model']['vocab_size'], 8192)

    @unittest.skipUnless(os.name == 'posix', 'POSIX bounded source reader')
    def test_pinned_local_closure_has_not_drifted_without_loading_it(self):
        before = 'torch' in sys.modules
        sources = probe.local_sources()
        self.assertEqual(set(sources), {name + '.py' for name in probe.LOCAL_SHA256})
        self.assertEqual('torch' in sys.modules, before)

    @unittest.skipUnless(os.name == 'posix', 'POSIX bounded source reader')
    def test_source_reader_rejects_alias_directory_hardlink_and_large_file(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'source.py').write_bytes(b'# inert')
            self.assertEqual(probe.read_files(root, ['source.py']), {'source.py': b'# inert'})
            (root / 'alias.py').symlink_to('source.py')
            with self.assertRaises(OSError):
                probe.read_files(root, ['alias.py'])
            (root / 'directory.py').mkdir()
            with self.assertRaises(probe.ProbeError):
                probe.read_files(root, ['directory.py'])
            os.link(root / 'source.py', root / 'hardlink.py')
            with self.assertRaises(probe.ProbeError):
                probe.read_files(root, ['hardlink.py'])
            (root / 'large.py').write_bytes(b'12345')
            with patch.object(probe, 'SOURCE_LIMIT', 4), self.assertRaises(probe.ProbeError):
                probe.read_files(root, ['large.py'])

    def test_generation_calls_exact_existing_adapter_only(self):
        source = b'# fixed architecture, never executed'
        identity = probe.hashlib.sha256(source).hexdigest()
        profile, generator = MagicMock(), MagicMock()
        profile.SOURCE_SHA256 = {'train.py': 'pin'}
        generator.build_training_bundle.return_value = {'generatedFiles': {'trusted_architecture.py': source},
            'receipt': {'generatedSha256': {'trusted_architecture.py': identity}}}
        files = {'train.py': b'not executed'}
        with patch.object(probe, 'read_files', return_value=files):
            self.assertEqual(probe.generate_architecture('/synthetic', {
                'research_profile': profile, 'research_training_adapter': generator}), (source, identity))
        profile.verify_upstream_source.assert_called_once_with(files)
        generator.build_training_bundle.assert_called_once_with(files, files, microbatch=1)

    def tensors(self):
        torch, architecture, model, parameter = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        architecture.GPT.return_value = model
        parameter.numel.return_value = 1024
        parameter.grad = object()
        model.parameters.return_value = [parameter]
        loss = model.return_value
        loss.ndim = 0
        loss.detach.return_value.item.return_value = 2.5
        torch.isfinite.return_value.all.return_value.item.return_value = True
        for name in ('memory_allocated', 'memory_reserved', 'max_memory_allocated', 'max_memory_reserved'):
            getattr(torch.cuda, name).return_value = 4096
        return torch, architecture, model

    def test_one_eager_forward_backward_no_optimizer_or_compile_model(self):
        torch, architecture, model = self.tensors()
        result = probe.run_model(torch, architecture)
        self.assertEqual(result['syntheticLoss'], 2.5)
        architecture.GPTConfig.assert_called_once_with(**probe.MODEL)
        model.to_empty.assert_called_once_with(device='cuda:0')
        model.init_weights.assert_called_once_with()
        model.assert_called_once()
        model.return_value.backward.assert_called_once_with()
        model.setup_optimizer.assert_not_called()
        torch.compile.assert_not_called()
        torch.cuda.synchronize.assert_called()

    def test_nonfinite_loss_or_gradient_and_allocator_overflow_fail_closed(self):
        for failure in ('loss', 'gradient', 'memory'):
            with self.subTest(failure=failure):
                torch, architecture, model = self.tensors()
                if failure == 'loss':
                    model.return_value.detach.return_value.item.return_value = float('nan')
                elif failure == 'gradient':
                    model.parameters.return_value[0].grad = None
                else:
                    torch.cuda.max_memory_reserved.return_value = probe.MAX_OBSERVED_ALLOCATOR_BYTES + 1
                with self.assertRaises(probe.ProbeError):
                    probe.run_model(torch, architecture)

    def fake_run(self, torch, *, failure=None):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {'torch': torch}))
            stack.enter_context(patch.object(probe, 'local_sources', return_value={}))
            stack.enter_context(patch.object(probe, 'load_local_modules', return_value={}))
            stack.enter_context(patch.object(probe, 'generate_architecture', return_value=(b'inert', '0' * 64)))
            loader = stack.enter_context(patch.object(probe, 'load_architecture'))
            stack.enter_context(patch.object(probe, 'run_model', side_effect=failure, return_value={}))
            result = probe.run_probe('/synthetic')
            return result, loader.call_count

    def test_version_gate_precedes_architecture_execution_and_no_exception_text(self):
        torch = SimpleNamespace(__version__='wrong', version=SimpleNamespace(cuda='12.8'))
        result, calls = self.fake_run(torch)
        self.assertEqual(result['errorCode'], 'VERSION_MISMATCH')
        self.assertEqual(calls, 0)
        class OutOfMemoryError(RuntimeError):
            pass
        torch = SimpleNamespace(__version__='2.9.1+cu128', version=SimpleNamespace(cuda='12.8'),
            cuda=SimpleNamespace(is_available=lambda: True, OutOfMemoryError=OutOfMemoryError))
        result, _ = self.fake_run(torch, failure=OutOfMemoryError('untrusted-path-or-token'))
        self.assertEqual(result['errorCode'], 'CUDA_OUT_OF_MEMORY')
        self.assertNotIn('untrusted', json.dumps(result))

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_interrupt_and_system_exit_stop_original_child_before_cache_cleanup(self):
        for error in (KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(kind=type(error).__name__):
                process = MagicMock(pid=12345)
                process.poll.return_value = None
                events = []
                process.wait.side_effect = lambda **kwargs: events.append('wait')
                process.stdout.close.side_effect = lambda: events.append('close')
                selector = MagicMock()
                selector.__enter__.return_value.select.side_effect = error
                with patch.object(probe.subprocess, 'Popen', return_value=process), \
                        patch.object(probe.selectors, 'DefaultSelector', return_value=selector), \
                        patch.object(probe.tempfile, 'mkdtemp', return_value='/synthetic/cache'), \
                        patch.object(probe.shutil, 'rmtree', side_effect=lambda *a, **k: events.append('cleanup')), \
                        patch.object(probe.os, 'killpg', side_effect=lambda *a: events.append('kill')) as kill, \
                        self.assertRaises(type(error)) as caught:
                    probe.supervise('/synthetic')
                self.assertIs(caught.exception, error)
                self.assertEqual(events, ['kill', 'wait', 'close', 'cleanup'])
                kill.assert_called_once_with(12345, probe.signal.SIGKILL)
                process.wait.assert_called_once_with(timeout=5)

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_unconfirmed_kill_retains_private_cache_without_claiming_stop(self):
        process = MagicMock(pid=12345)
        process.poll.return_value = None
        process.wait.side_effect = probe.subprocess.TimeoutExpired('fixed-probe', timeout=5)
        with patch.object(probe.subprocess, 'Popen', return_value=process), \
                patch.object(probe.selectors, 'DefaultSelector'), \
                patch.object(probe.tempfile, 'mkdtemp', return_value='/synthetic/cache'), \
                patch.object(probe.shutil, 'rmtree') as cleanup, \
                patch.object(probe.time, 'monotonic', side_effect=[0, 121]), \
                patch.object(probe.os, 'killpg'):
            result = probe.supervise('/synthetic')
        self.assertEqual(result['errorCode'], 'TIMEOUT')
        self.assertFalse(result['factoryExecutionVerified'])
        cleanup.assert_not_called()
        process.wait.assert_called_once_with(timeout=5)

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_supervisor_deadline_kills_only_original_group(self):
        process = MagicMock(pid=12345)
        process.poll.return_value = None
        with patch.object(probe.subprocess, 'Popen', return_value=process), \
                patch.object(probe.selectors, 'DefaultSelector'), \
                patch.object(probe.time, 'monotonic', side_effect=[0, 121]), \
                patch.object(probe.os, 'killpg') as kill:
            self.assertEqual(probe.supervise('/synthetic')['errorCode'], 'TIMEOUT')
        kill.assert_called_once_with(12345, probe.signal.SIGKILL)
        process.wait.assert_called_once_with(timeout=5)

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_supervisor_rejects_output_overflow_and_extra_fields(self):
        for payload in (b'x' * (probe.MAX_OUTPUT_BYTES + 1), json.dumps(probe.report('CUDA_UNAVAILABLE') | {'path': '/private'}).encode()):
            with self.subTest(size=len(payload)):
                process = MagicMock(pid=12345, returncode=0)
                process.poll.return_value = 0
                with patch.object(probe.subprocess, 'Popen', return_value=process), \
                        patch.object(probe.selectors, 'DefaultSelector'), \
                        patch.object(probe.os, 'read', side_effect=[payload, b'']), \
                        patch.object(probe.os, 'killpg') as kill:
                    self.assertEqual(probe.supervise('/synthetic')['errorCode'], 'OUTPUT_INVALID')
                kill.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_supervisor_validates_success_scalars_and_never_returns_paths(self):
        torch, architecture, _ = self.tensors()
        value = probe.report() | probe.run_model(torch, architecture) | {
            'passed': True, 'generatedArchitectureSha256': '0' * 64,
            'adapterSha256': probe.LOCAL_SHA256['research_torch_runtime'],
            'optimizerCompileDecoratorsRegistered': True, 'torchVersion': '2.9.1', 'torchCudaVersion': '12.8'}
        for payload, expected in ((value, True), (value | {'syntheticLoss': '/untrusted/path'}, False)):
            process = MagicMock(pid=12345, returncode=0)
            process.poll.return_value = 0
            with patch.object(probe.subprocess, 'Popen', return_value=process), \
                    patch.object(probe.selectors, 'DefaultSelector'), \
                    patch.object(probe.os, 'read', side_effect=[json.dumps(payload).encode(), b'']):
                result = probe.supervise('/synthetic')
            self.assertEqual(result['passed'], expected)
            self.assertNotIn('/untrusted/path', json.dumps(result))

    def test_torchversion_str_subclass_accepted_without_arbitrary_stringification(self):
        class TorchVersion(str):
            def __str__(self):
                raise AssertionError('must not call override')
        self.assertTrue(probe.torch_version_matches(TorchVersion('2.9.1+cu128')))
        for value in (object(), 291, True, TorchVersion('2.9.1/path'), TorchVersion('2.9.10'),
                      TorchVersion('2.9.1\n'), TorchVersion('2.9.1+' + 'x' * 41)):
            self.assertFalse(probe.torch_version_matches(value))
        torch = SimpleNamespace(__version__=TorchVersion('2.9.1+cu128'), version=SimpleNamespace(cuda='12.8'),
            cuda=SimpleNamespace(is_available=lambda: True))
        result, calls = self.fake_run(torch)
        self.assertTrue(result['passed'])
        self.assertEqual(calls, 1)

    @unittest.skipUnless(os.name == 'posix', 'POSIX supervisor')
    def test_supervisor_preserves_safe_failure_and_has_fixed_child_command(self):
        process = MagicMock(pid=12345, returncode=0)
        process.poll.return_value = 0
        payload = json.dumps(probe.report('CUDA_UNAVAILABLE')).encode()
        with patch.object(probe.subprocess, 'Popen', return_value=process) as launch, \
                patch.object(probe.selectors, 'DefaultSelector'), \
                patch.object(probe.os, 'read', side_effect=[payload, b'']):
            self.assertEqual(probe.supervise('/synthetic')['errorCode'], 'CUDA_UNAVAILABLE')
        argv = launch.call_args.args[0]
        self.assertEqual(argv[1:4], ['-I', '-B', '-c'])
        self.assertEqual(argv[4], probe._WORKER)
        self.assertTrue(launch.call_args.kwargs['start_new_session'])
        self.assertNotIn('OPENCODE_GO', launch.call_args.kwargs['env'])
        self.assertEqual(launch.call_args.kwargs['env']['OMP_NUM_THREADS'], '2')
        self.assertEqual(launch.call_args.kwargs['env']['MKL_NUM_THREADS'], '2')


if __name__ == '__main__':
    unittest.main()
