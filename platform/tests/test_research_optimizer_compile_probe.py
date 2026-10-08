"""Mock operator semantics and real stdlib-only process custody; never import Torch."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import importlib.util
import hashlib
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).parents[2] / 'scripts/probe_research_optimizer_compile.py'
spec = importlib.util.spec_from_file_location('optimizer_probe', SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)


class Tensor:
    ndim = 0
    grad: object = None
    def __init__(self, history): self.history = history
    def remainder(self, value): return self
    def unsqueeze(self, value): return self
    def __add__(self, value): return self
    def __truediv__(self, value):
        self.history.append(('loss_divisor', value)); return self
    def backward(self): self.history.append(('backward',))
    def all(self): return self
    def item(self): return True
    def numel(self): return 10


class FakeTorch:
    bfloat16 = 'bf16'
    def __init__(self):
        self.history = []
        self.cuda = SimpleNamespace(set_device=Mock(), manual_seed=Mock(), reset_peak_memory_stats=Mock(),
            synchronize=Mock(), **{key: Mock(return_value=1024) for key in ('memory_allocated', 'memory_reserved',
                'max_memory_allocated', 'max_memory_reserved')})
        self.amp = SimpleNamespace(autocast=lambda **kw: nullcontext())
        self.manual_seed = Mock(); self.set_float32_matmul_precision = Mock()
    def device(self, value): return nullcontext()
    def no_grad(self): return nullcontext()
    def arange(self, *args, **kwargs): return Tensor(self.history)
    def isfinite(self, value): return Tensor(self.history)
    def is_tensor(self, value): return isinstance(value, Tensor)
    def compile(self, model, **kwargs):
        self.history.append(('compile', kwargs)); return model


class FakeModel:
    def __init__(self, torch):
        self.torch = torch
        self.parameter = Tensor(torch.history); self.parameter.grad = Tensor(torch.history)
        self.optimizer = SimpleNamespace(param_groups=[{'kind': 'muon', 'initial_lr': .04}],
            state={0: {'step': 1, 'momentum': Tensor(torch.history)}}, step=self.step)
    def to_empty(self, **kw): pass
    def init_weights(self): pass
    def train(self): pass
    def eval(self): self.torch.history.append(('eval_mode',))
    def setup_optimizer(self, **kwargs):
        self.torch.history.append(('optimizer_setup', kwargs)); return self.optimizer
    def parameters(self): return [self.parameter]
    def __call__(self, x, y):
        self.torch.history.append(('forward',)); return Tensor(self.torch.history)
    def step(self):
        self.torch.history.append(('step', dict(self.optimizer.param_groups[0])))
    def zero_grad(self, **kw): self.torch.history.append(('zero_grad', kw))


class ModelContractTests(unittest.TestCase):
    def test_two_microbatches_original_optimizer_flags_and_two_eager_forwards(self):
        torch = FakeTorch(); model = FakeModel(torch)
        architecture = SimpleNamespace(GPT=lambda config: model, GPTConfig=lambda **kw: kw)
        events = []
        with patch.object(probe, 'worker_resources', return_value={'userCpuSeconds': 0, 'systemCpuSeconds': 0, 'peakRssKiB': 1}):
            result = probe.run_model(torch, architecture, events.append)
        self.assertEqual(result['optimizerSteps'], 2)
        self.assertEqual(result['forwardBackwardMicrobatches'], 2)
        self.assertEqual(result['eagerEvaluationForwards'], 2)
        self.assertEqual([x for x in torch.history if x[0] == 'compile'], [('compile', {'dynamic': False})])
        setup = next(x[1] for x in torch.history if x[0] == 'optimizer_setup')
        self.assertEqual(setup, {'unembedding_lr': .004, 'embedding_lr': .6, 'matrix_lr': .04,
            'scalar_lr': .5, 'adam_betas': (.8, .95), 'weight_decay': .2})
        steps = [x[1] for x in torch.history if x[0] == 'step']
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]['momentum'], .85)
        self.assertAlmostEqual(steps[1]['momentum'], .8503333333333333)
        self.assertTrue(all(x['lr'] == .04 and x['weight_decay'] == .2 for x in steps))
        self.assertEqual(sum(x[0] == 'forward' for x in torch.history), 4)
        self.assertEqual([x for x in torch.history if x[0] == 'loss_divisor'], [('loss_divisor', 256)] * 2)
        self.assertEqual(sum(x[0] == 'zero_grad' for x in torch.history), 2)
        for event in events: probe.validate_event(event)
        self.assertFalse(probe.report()['fullWarmupVerified'])
        self.assertFalse(probe.report()['fullEvaluationVerified'])

    @unittest.skipUnless(sys.platform == 'linux', 'Exact Linux source byte pins exclude Windows checkout line endings')
    def test_exact_current_source_hashes(self):
        root = SCRIPT.parents[1] / 'platform/agent_factory'
        for name, expected in probe.LOCAL_SHA256.items():
            self.assertEqual(hashlib.sha256((root / (name + '.py')).read_bytes()).hexdigest(), expected)

    @unittest.skipUnless(sys.platform == 'linux', 'Source-only loader requires nofollow directory FDs')
    def test_no_pyc_loader(self):
        sources = probe.local_sources()
        self.assertEqual(set(sources), {name + '.py' for name in probe.LOCAL_SHA256})
        code = ("import importlib.util,sys; s=importlib.util.spec_from_file_location('p',sys.argv[1]);"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "m.load_local_modules(m.local_sources());assert 'torch' not in sys.modules")
        result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(SCRIPT)],
                                capture_output=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_clean_environment_never_reads_ambient_credentials_or_device(self):
        with patch.object(probe.os, 'environ', {'SECRET': 'sentinel', 'CUDA_VISIBLE_DEVICES': 'ambient'}):
            value = probe.clean_environment(Path('/private/task'), 'GPU-12345678')
        self.assertNotIn('SECRET', value)
        self.assertEqual(value['CUDA_VISIBLE_DEVICES'], 'GPU-12345678')
        self.assertEqual(value['TORCHINDUCTOR_COMPILE_THREADS'], '1')
        self.assertEqual(value['SETUPTOOLS_USE_DISTUTILS'], 'local')

    def test_cli_invalid_private_argument_is_not_echoed_or_launched(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(probe, 'supervise') as launch, redirect_stderr(stderr), redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as error:
                probe.main(['--source-root', '/private/source', '--scratch-root', '/private/scratch',
                            '--device', 'GPU-12345678', '--unknown-private=/private/credential'])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(json.loads(stderr.getvalue()), {'schema': 1, 'passed': False, 'errorCode': 'ARGUMENTS_INVALID'})
        self.assertNotIn('/private', stderr.getvalue())
        launch.assert_not_called()

    def test_strict_metrics_reject_unknown_fields_nonfinite_and_false_success(self):
        for event in ({'phase': 'round1_forward', 'state': 'completed', 'elapsedSeconds': float('nan')},
                      {'phase': 'dependencies', 'state': 'started', 'rawError': 'private'},
                      {'result': 'passed'}, {'result': 'failed', 'errorCode': 'private-path'}):
            with self.assertRaises(probe.ProbeError): probe.validate_event(event)


@unittest.skipUnless(sys.platform == 'linux', 'Actual stdlib group/reaping tests require Linux')
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.scratch = Path(self.temp.name)

    def supervise(self, code, wall: float = 2, *, timeout_after_event=False):
        # A separate stdlib supervisor isolates PR_SET_CHILD_SUBREAPER from the
        # unittest process and any unrelated children. The child never loads ML.
        parent = """import importlib.util,json,pathlib,sys
s=importlib.util.spec_from_file_location('p',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
if sys.argv[5]=='1':
 real_clock=m.time.monotonic; original_validate=m.validate_event; offset=[0]
 m.time.monotonic=lambda:real_clock()+offset[0]
 def validate(value):
  event=original_validate(value); offset[0]=float(sys.argv[4])+1; return event
 m.validate_event=validate
r=m._supervise_command([sys.executable,'-I','-B','-c',sys.argv[3]],pathlib.Path(sys.argv[2]),m.clean_environment(pathlib.Path(sys.argv[2]),'GPU-12345678'),wall=float(sys.argv[4]))
print(json.dumps(r))
"""
        result = subprocess.run([sys.executable, '-I', '-B', '-c', parent, str(SCRIPT), str(self.scratch), code, str(wall), '1' if timeout_after_event else '0'],
                                capture_output=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return json.loads(result.stdout)

    def test_root_exit_with_live_descendant_requires_real_group_kill_and_reap(self):
        code = """import os,time,json
child=os.fork()
if child==0:
 time.sleep(60)
else:
 print(json.dumps({'result':'failed','errorCode':'PROBE_FAILED'}),flush=True)
 os._exit(0)
"""
        result = self.supervise(code)
        self.assertFalse(result['passed'])
        self.assertTrue(result['originalGroupStopped'], result)
        self.assertEqual(result['stopProof'], {'leaderReaped': True, 'groupEmpty': True, 'adoptedChildrenEmpty': True})

    def test_compile_timeout_keeps_started_phase_and_stops_original(self):
        result = self.supervise("import json,time;print(json.dumps({'phase':'dependencies','state':'started'}),flush=True);time.sleep(60)", timeout_after_event=True)
        self.assertEqual(result['errorCode'], 'TIMEOUT')
        self.assertEqual(result['events'], [{'phase': 'dependencies', 'state': 'started'}])
        self.assertTrue(result['originalGroupStopped'])

    def test_cache_budget_observation_records_over_limit_peak_without_expansion(self):
        code = "import os,time;f=os.open('huge',os.O_CREAT|os.O_WRONLY,0o600);os.ftruncate(f,1073741825);os.close(f);time.sleep(60)"
        result = self.supervise(code)
        self.assertEqual(result['errorCode'], 'CACHE_LIMIT')
        self.assertGreater(result['cachePeakBytes'], probe.CACHE_BYTES)
        self.assertTrue(result['originalGroupStopped'])

    def test_unconfirmed_original_birth_never_signals_or_proves_stop(self):
        process = Mock(pid=123)
        with patch.object(probe, 'proc_identity', return_value={'start': 2, 'group': 123}), \
             patch.object(probe.os, 'killpg') as kill:
            proof = probe.stop_group(process, {'start': 1, 'group': 123})
        self.assertFalse(all(proof.values()))
        kill.assert_not_called(); process.wait.assert_not_called()

    def test_unknown_stop_retains_private_scratch_and_single_attempt(self):
        root = self.scratch / 'private'; root.mkdir(mode=0o700)
        with patch.object(probe, 'local_sources'), patch.object(probe, '_supervise_command', return_value=probe.report()) as run:
            result = probe.supervise(Path('/source'), root, 'GPU-12345678')
            self.assertFalse(result['scratchRemoved'])
            self.assertTrue((root / 'owned-cache').exists())
            again = probe.supervise(Path('/source'), root, 'GPU-12345678')
            self.assertFalse(again['passed'])
            self.assertEqual(run.call_count, 1)

    def test_initial_pin_failure_never_releases_worker_gate_and_attempts_stop(self):
        code = "from pathlib import Path;Path('launched').write_text('bad')"
        process_factory = probe.subprocess.Popen
        original = probe.proc_identity
        child_pid = []
        def create(*args, **kwargs):
            value = process_factory(*args, **kwargs); child_pid.append(value.pid); return value
        def fail_pin(pid):
            if child_pid and pid == child_pid[0]:
                raise PermissionError('synthetic')
            return original(pid)
        with patch.object(probe.subprocess, 'Popen', side_effect=create), \
             patch.object(probe, 'proc_identity', side_effect=fail_pin):
            result = probe._supervise_command([sys.executable, '-I', '-B', '-c', code],
                self.scratch, probe.clean_environment(self.scratch, 'GPU-12345678'), wall=.2)
        self.assertFalse(result['originalGroupStopped'])
        self.assertEqual(result['stopErrorCode'], 'STOP_UNCONFIRMED')
        self.assertFalse((self.scratch / 'launched').exists())
        with self.assertRaises(FileNotFoundError): original(child_pid[0])

    def test_escaped_adopted_child_is_stopped_but_proof_remains_unknown(self):
        code = """import os,time,json
child=os.fork()
if child==0:
 os.setsid(); open('escaped-pid','w').write(str(os.getpid())); time.sleep(60)
else:
 time.sleep(.1); print(json.dumps({'result':'failed','errorCode':'PROBE_FAILED'}),flush=True); os._exit(0)
"""
        result = self.supervise(code)
        self.assertFalse(result['originalGroupStopped'])
        self.assertEqual(result['stopErrorCode'], 'STOP_UNCONFIRMED')
        self.assertFalse(result['stopProof']['adoptedChildrenEmpty'])
        pid = int((self.scratch / 'escaped-pid').read_text())
        self.assertFalse(Path(f'/proc/{pid}').exists())

    def test_allocator_over_limit_event_preserves_actual_value(self):
        code = "import json,time;print(json.dumps({'phase':'dependencies','state':'started','allocator':{k:8589934593 for k in ('memory_allocated','memory_reserved','max_memory_allocated','max_memory_reserved')}}),flush=True);time.sleep(60)"
        result = self.supervise(code)
        self.assertEqual(result['errorCode'], 'ALLOCATOR_LIMIT')
        self.assertEqual(result['events'][0]['allocator']['max_memory_reserved'], probe.ALLOCATOR_BYTES + 1)
        self.assertTrue(result['originalGroupStopped'])
