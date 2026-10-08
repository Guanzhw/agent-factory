"""Bounded, original tools; all research evidence is explicitly synthetic."""
import asyncio
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from .application_schema import time_budget

from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agno.tools import tool

SYNTHETIC_DATASET = [9, 5, 8, 1, 3, 7, 2, 6, 4, 0]
DATASET_HASH = hashlib.sha256(json.dumps(SYNTHETIC_DATASET, separators=(',', ':')).encode()).hexdigest()
EXPERIMENT_PROGRAM = '''import json,sys,time,os
if os.name != 'nt':
 import resource
 resource.setrlimit(resource.RLIMIT_AS,(int(sys.argv[2]),int(sys.argv[2])))
 resource.setrlimit(resource.RLIMIT_CPU,(int(sys.argv[3]),int(sys.argv[3])))
 resource.setrlimit(resource.RLIMIT_NPROC,(int(sys.argv[4]),int(sys.argv[4])))
data=[9,5,8,1,3,7,2,6,4,0]
time.sleep(float(sys.argv[1]))
baseline=sum(data[i]>data[j] for i in range(len(data)) for j in range(i+1,len(data)))
candidate=sorted(data)
score=sum(candidate[i]>candidate[j] for i in range(len(candidate)) for j in range(i+1,len(candidate)))
print(json.dumps({'baseline':baseline,'candidate':score,'delta':baseline-score,'metric':'inversion_count','direction':'lower'}))
'''


class _WindowsJob:
    """Documented Windows job-object containment, including descendant cleanup."""
    kernel: Any  # Platform-specific ctypes DLL/handle types.
    handle: Any = None

    def __init__(self, pid, memory_bytes=256 * 1024 * 1024, process_limit=4, cpu_percent=10):
        if os.name != 'nt':
            raise RuntimeError('Windows job containment requires Windows')
        from ctypes import wintypes
        # These ctypes exports exist only on Windows; resolve after the OS guard.
        win_dll = getattr(ctypes, 'WinDLL')
        win_error = getattr(ctypes, 'WinError')
        last_error = getattr(ctypes, 'get_last_error')
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64), ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active_limit', wintypes.DWORD), ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ['read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes']]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', Io), ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]
        kernel = win_dll('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel, self.handle = kernel, kernel.CreateJobObjectW(None, None)
        limits = Extended(); limits.basic.flags = 0x2000 | 0x8 | 0x200  # kill-on-close, active-process and job-memory limits
        limits.basic.active_limit = process_limit
        limits.job_memory = memory_bytes
        process = None
        try:
            if not self.handle or not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise win_error(last_error())
            class CpuRate(ctypes.Structure):
                _fields_ = [('flags', wintypes.DWORD), ('rate', wintypes.DWORD)]
            cpu = CpuRate(0x1 | 0x4, cpu_percent * 100)  # enabled hard CPU-rate cap
            if not kernel.SetInformationJobObject(self.handle, 15, ctypes.byref(cpu), ctypes.sizeof(cpu)):
                raise win_error(last_error())
            process = kernel.OpenProcess(0x100 | 0x1, False, pid)
            if not process or not kernel.AssignProcessToJobObject(self.handle, process):
                raise win_error(last_error())
        except BaseException:
            self.close()
            raise
        finally:
            if process: kernel.CloseHandle(process)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _experiment(settings, store, ctx, plan, stop_signal, authority_check=None):
    proc = job = None
    failure = None
    dispatch_attempted = False
    try:
        runtime_root = Path(getattr(settings, 'runtime_directory', '.local/runtime')).resolve()
        if getattr(store, 'storage', None) is not None:
            runtime_root = store.storage.directory(ctx.run_id, "synthetic-runtime")
        runtime_root.mkdir(parents=True, exist_ok=True)
        timeout = min(30.0, max(.1, float(getattr(settings, 'experiment_timeout_seconds', 5))))
        output_cap = min(1024 * 1024, max(1024, int(getattr(settings, 'experiment_output_bytes', 65536))))
        duration = min(5.0, max(.01, float(plan.get('config', {}).get('experimentDurationSeconds', .05))))
        memory_cap = min(1024 * 1024 * 1024, max(64 * 1024 * 1024, int(getattr(settings, 'experiment_memory_bytes', 256 * 1024 * 1024))))
        process_cap = min(8, max(1, int(getattr(settings, 'experiment_process_limit', 4))))
        cpu_percent = min(100, max(1, int(getattr(settings, 'experiment_cpu_percent', 10))))
        timeout = min(timeout, time_budget(plan, timeout))
        output_cap = min(output_cap, plan.get('budget', {}).get('outputBytes', output_cap))
        bindings = getattr(store, 'execution_bindings', None)
        selected_runtime = 'local-python-bounded-v1'
        if bindings is not None:
            limits = bindings.environment_limits(plan, ctx)
            selected_runtime = limits.runtime_id
            timeout = min(timeout, limits.timeout_seconds)
            output_cap = min(output_cap, limits.output_bytes)
            memory_cap = min(memory_cap, limits.memory_bytes)
            process_cap = min(process_cap, limits.process_limit)
            cpu_percent = min(cpu_percent, limits.cpu_percent)
        started = time.monotonic()
        next_authority_check = started
        with tempfile.TemporaryFile(dir=runtime_root) as output:
            dispatch_attempted = True
            proc = subprocess.Popen([sys.executable, '-I', '-c', EXPERIMENT_PROGRAM, str(duration), str(memory_cap), str(int(timeout)+1), str(process_cap)], stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                    cwd=runtime_root, creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0,
                                    start_new_session=os.name != 'nt', env={k: v for k, v in os.environ.items() if k in ['SystemRoot','WINDIR','TEMP','TMP','PATH','LANG','LC_ALL']})
            if os.name == 'nt': job = _WindowsJob(proc.pid, memory_cap, process_cap, cpu_percent)
            store.event(ctx.run_id, 'compute_started', 'Bounded synthetic subprocess started', {'pid': proc.pid, 'runtimeId': selected_runtime, 'descendantIsolation': 'windows-job-kill-on-close' if job else 'posix-process-group', 'evaluatorId': 'synthetic-sort-inversions', 'evaluatorVersion': '1', 'datasetHash': DATASET_HASH, 'memoryLimitBytes':memory_cap,'processLimit':process_cap,'cpuLimit':{'percent':cpu_percent} if job else {'seconds':int(timeout)+1},'wallClockLimitSeconds':timeout,'outputLimitBytes':output_cap})
            while proc.poll() is None:
                if stop_signal.is_set() or store.cancellation_requested(ctx.run_id):
                    raise RunCancelledException('Factory cancellation requested during local compute')
                if authority_check is not None and time.monotonic() >= next_authority_check:
                    try:
                        authority_check()
                    except RunCancelledException:
                        # An exact trusted origin cancellation is already a
                        # native stop signal, not a new authority failure.
                        raise
                    except Exception as error:
                        store.event(ctx.run_id, 'protected_denied', 'Current authority ended during owned compute; stopping this process', {'tool': 'run_experiment'})
                        raise RunCancelledException('Current task authority ended during owned compute') from error
                    next_authority_check = time.monotonic() + .25
                if time.monotonic() - started > timeout:
                    raise TimeoutError('Bounded experiment exceeded wall-clock limit')
                if output.seek(0, os.SEEK_END) > output_cap:
                    raise RuntimeError('Bounded experiment exceeded output limit')
                time.sleep(.03)
            output.seek(0)
            raw = output.read(output_cap + 1)
            if len(raw) > output_cap or proc.returncode != 0:
                raise RuntimeError('Bounded experiment failed or exceeded output limit')
            metric = json.loads(raw)
            return {**metric, 'evidenceKind': 'synthetic', 'datasetHash': DATASET_HASH, 'evaluatorId': 'synthetic-sort-inversions', 'evaluatorVersion': '1', 'runtimeId': selected_runtime, 'modelAdapterId': (plan.get('executionBindings') or {}).get('model', {}).get('adapterId', 'local-synthetic-model-v1'), 'pid': proc.pid, 'elapsedSeconds': round(time.monotonic() - started, 4), 'outputHash': hashlib.sha256(raw).hexdigest()}
    except BaseException as error:
        failure = error
        # These markers describe this invocation, never a reused exception.
        setattr(error, 'compute_cleanup_complete', False)
        setattr(error, 'compute_never_dispatched', False)
        raise
    finally:
        if job: job.close()
        if proc:
            if os.name != 'nt':
                try: os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError: pass
            elif proc.poll() is None:
                proc.terminate()
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if os.name != 'nt':
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                else: proc.kill()
                proc.wait(timeout=2)
            if os.name != 'nt':
                # A descendant may ignore SIGTERM even after its root exits.
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            store.event(ctx.run_id, 'compute_stopped', 'Task-owned compute and descendants cleaned up', {'pid': proc.pid, 'returnCode': proc.returncode, 'cleanupComplete': True})
        if failure is not None:
            # A failed launch call may have dispatched without returning a handle.
            # Only our local pre-dispatch boundary or confirmed cleanup proves stop.
            if proc is not None or not dispatch_attempted:
                setattr(failure, 'compute_cleanup_complete', True)
            if not dispatch_attempted:
                setattr(failure, 'compute_never_dispatched', True)


def _experiment_outcome(settings, store, ctx, plan, stop_signal, authority_check=None):
    try:
        return {'ok': True, 'result': _experiment(settings, store, ctx, plan, stop_signal, authority_check), 'cleanupComplete': True}
    except BaseException as error:
        return {'ok': False, 'error': error, 'cleanupComplete': bool(getattr(error, 'compute_cleanup_complete', False)),
                'neverDispatched': bool(getattr(error, 'compute_never_dispatched', False))}


def build_tools(settings, store):
    def checked(ctx, name):
        if store.cancellation_requested(ctx.run_id):
            raise RunCancelledException('Factory cancellation requested')
        store.authorize_tool(ctx, name)
        return store.resolve_run(ctx)

    def artifact(ctx, name, result):
        encoded = json.dumps(result, sort_keys=True)
        plan = store.resolve_run(ctx)
        manifest = plan.get('executionBindings') or {}
        environment = manifest.get('environment', {})
        metadata = {'evidenceKind': result.get('evidenceKind', 'synthetic'),
                    'modelAdapterId': manifest.get('model', {}).get('adapterId', 'local-synthetic-model-v1'),
                    'environmentAdapterId': environment.get('adapterId', 'local-bounded-environment-v1'),
                    'executionBindingsSha256': manifest.get('sha256'),
                    'runtimeId': result.get('runtimeId', environment.get('config', {}).get('runtimeId', 'local-bounded-v1')),
                    'sha256': hashlib.sha256(encoded.encode()).hexdigest()}
        store.artifact_write(ctx.run_id, name, encoded, 'application/json', metadata)

    @tool(requires_user_input=True, user_input_fields=['scope'])
    def ask_scope(question: str, scope: str, run_context: RunContext) -> str:
        """Ask the user to provide a bounded research scope before continuing."""
        checked(run_context, 'ask_scope')
        if not scope.strip() or len(scope) > 4000:
            raise ValueError('Scope must contain between 1 and 4000 characters')
        result = {'question': question, 'scope': scope.strip(), 'evidenceKind': 'synthetic'}
        store.event(run_context.run_id, 'scope_answered', 'User-provided scope accepted', {'scope': scope.strip()})
        return json.dumps(result)

    def literature_search(query: str, run_context: RunContext) -> str:
        """Return clearly synthetic local literature fixtures, never real research claims."""
        checked(run_context, 'literature_search')
        if not query.strip() or len(query) > 4000: raise ValueError('Query must contain between 1 and 4000 characters')
        result = {'query': query.strip(), 'evidenceKind': 'synthetic', 'sources': [{'id': 'synthetic-method-fixture-v1', 'title': 'Synthetic method fixture (not a publication)', 'url': 'https://synthetic-research.invalid/method-v1', 'claim': 'Deterministic integration fixture only', 'sha256': hashlib.sha256(b'synthetic-method-fixture-v1').hexdigest()}], 'notice': 'No internet literature search was performed.'}
        artifact(run_context, 'synthetic-literature.json', result)
        store.event(run_context.run_id, 'literature_fixture', 'Synthetic literature fixture recorded', {'evidenceKind':'synthetic','sourceCount':1})
        return json.dumps(result)

    def checksum(text: str, run_context: RunContext) -> str:
        """Compute SHA-256 over the actual supplied UTF-8 text."""
        checked(run_context, 'checksum')
        encoded = text.encode()
        if len(encoded) > 65536: raise ValueError('Checksum input exceeds 64 KiB')
        result = {'algorithm': 'sha256', 'sha256': hashlib.sha256(encoded).hexdigest(), 'inputBytes': len(encoded), 'evidenceKind': 'synthetic-input-real-computation'}
        artifact(run_context, 'checksum.json', result)
        store.event(run_context.run_id, 'checksum_completed', 'Input checksum computed', result)
        return json.dumps(result)

    @tool(requires_confirmation=True)
    async def run_experiment(experiment: str, run_context: RunContext) -> str:
        """Run the one allowlisted synthetic sort evaluator after user confirmation."""
        plan = checked(run_context, 'run_experiment')
        if experiment != 'bounded-sort-v1': raise ValueError('Unknown experiment: only bounded-sort-v1 is approved')
        key = 'experiment:bounded-sort-v1'
        request = {'experiment': experiment, 'datasetHash': DATASET_HASH, 'evaluatorVersion': '1'}
        reservation = store.effect_reserve(run_context.run_id, key, request)
        if reservation['status'] == 'unknown':
            store.event(run_context.run_id, 'effect_unknown', 'UNKNOWN compute acknowledgement requires reconciliation', {'effectKey':key})
            raise RuntimeError('UNKNOWN effect requires reconciliation; automatic replay refused')
        if reservation['status'] == 'done': return json.dumps(reservation['result'])
        outcome = None
        recorded = False
        try:
            stop_signal = threading.Event()
            worker = asyncio.create_task(asyncio.to_thread(_experiment_outcome, settings, store, run_context, plan, stop_signal, lambda: store.authorize_tool(run_context, "run_experiment")))
            try:
                outcome = await asyncio.shield(worker)
            except BaseException:
                stop_signal.set()
                outcome = await asyncio.shield(worker)
                raise
            if not outcome['ok']: raise outcome['error']
            result = outcome['result']
            # Persist known compute outcome before a subsequent authority
            # check: revocation must not turn a completed effect into UNKNOWN.
            store.effect_complete(run_context.run_id, key, result)
            recorded = True
            checked(run_context, 'run_experiment')
            artifact(run_context, 'synthetic-experiment.json', result)
            store.event(run_context.run_id, 'experiment_completed', 'Synthetic evaluator completed; no real research success established', result)
            return json.dumps(result)
        except BaseException as error:
            if outcome and outcome.get('cleanupComplete') and isinstance(error, (RunCancelledException, asyncio.CancelledError)):
                known = outcome['result'] if outcome['ok'] else {'cancelled': True, 'cleanupComplete': True, 'runtimeId': 'local-python-bounded-v1'}
                if not outcome['ok'] and outcome.get('neverDispatched'):
                    known['dispatchState'] = 'never-dispatched'
                if not recorded: store.effect_complete(run_context.run_id, key, known)
                store.event(run_context.run_id, 'compute_cancelled', 'Cancellation settled after confirmed task-owned compute cleanup', {'effectKey':key,'cleanupComplete':True})
            elif not recorded:
                store.event(run_context.run_id, 'effect_unknown', 'Compute outcome requires reconciliation', {'effectKey':key,'error':str(error),'cancellationRequested':store.cancellation_requested(run_context.run_id)})
            raise

    return {'ask_scope': ask_scope, 'literature_search': literature_search, 'checksum': checksum, 'run_experiment': run_experiment}
