"""Bounded optimizer/compile diagnostic; not training, evaluation or Factory admission.

Linux supervisor owns one original process group. Compiler descendants are reaped
before scratch removal; unknown/escaped custody retains scratch and denies success.
No retries, downloads, installation, checkpoint, task IDs or synthetic scientific score.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
from types import ModuleType
from typing import cast

BASE_REVISION = '4e0d3aceddc4e7a2fdbd88cbe1f1569ce865755f'
WALL_SECONDS = 300
CPU_SECONDS = 300
FILE_BYTES = 256 * 1024**2
CACHE_BYTES = 1024**3
OUTPUT_BYTES = 32768
CLEANUP_SECONDS = 5
MAX_ENTRIES = 8192
SOURCE_LIMIT = 4 * 1024**2
ALLOCATOR_BYTES = 8 * 1024**3
MODEL = {'sequence_len': 2048, 'vocab_size': 8192, 'n_layer': 8, 'n_head': 4,
         'n_kv_head': 4, 'n_embd': 512, 'window_pattern': 'SSSL'}
OPTIMIZER = {'unembedding_lr': .004, 'embedding_lr': .6, 'matrix_lr': .04,
             'scalar_lr': .5, 'adam_betas': (.8, .95), 'weight_decay': .2}
PHASES = ('dependencies', 'architecture', 'model_setup', 'compile_registration',
          'round1_forward', 'round1_backward', 'round1_optimizer',
          'round2_forward', 'round2_backward', 'round2_optimizer', 'eager_eval1', 'eager_eval2')
ERRORS = frozenset({'SOURCE_INVALID', 'VERSION_MISMATCH', 'CUDA_UNAVAILABLE', 'CUDA_OUT_OF_MEMORY',
    'NONFINITE', 'ALLOCATOR_LIMIT', 'TIMEOUT', 'CACHE_LIMIT', 'CPU_LIMIT', 'OUTPUT_INVALID',
    'SUPERVISOR_UNAVAILABLE', 'STOP_UNCONFIRMED', 'PROBE_FAILED'})


class ProbeError(ValueError):
    pass


def require(ok, code='SOURCE_INVALID'):
    if not ok:
        raise ProbeError(code)


LOCAL_SHA256 = {'__init__': '34a3ecc32ec01bb74feee444a052919b9407ef081460c8a4546bae3f438c163a', 'research_candidate': '61814f7dc86bef20dc38e375c831d5bf822ffb4555bc13e832adb3adc6a26197', 'research_profile': 'b410187bfc2530264363dfcf32c5cf8236848c071f8fb0f2a992de4a9d5bcb45', 'research_manifest': '1bc6331885191fe08b8f683c547ba30fa0160b5521f3b5f0bc0c441973cd97f9', 'research_assessment': 'd65fceff622b6ea1f5513b2081d0dc7a15ab04a66fdb13a850bfa3884458aee3', 'research_evaluation': 'abaaeea583c5316aa0be04814f593ae27c6b7943532aaa8138e530708a427080', 'research_checkpoint': 'a9c3a12bc5a94065a6cc6fc254632c22f14ac8daf815b5009ca29725bcdf585f', 'research_torch_runtime': 'cd3c9e3edc1800f495fd0c3e4ed9bdef03b077d918883262e19f1fd192774dde', 'research_training_adapter': 'c63ce79249796d4afdc5be7347f36a293d1657a3139c7a640986feb88d01a3da'}


def _directory(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts and os.name == 'posix')
    nofollow, directory = getattr(os, 'O_NOFOLLOW', None), getattr(os, 'O_DIRECTORY', None)
    require(type(nofollow) is int and nofollow > 0 and type(directory) is int and directory > 0)
    nofollow, directory = cast(int, nofollow), cast(int, directory)
    fd = os.open(path.anchor, os.O_RDONLY | directory | nofollow)
    try:
        for name in path.parts[1:]:
            child = os.open(name, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def read_files(root, names):
    """Read only fixed basenames, regular single-link files, bounded same-FD bytes."""
    fd = _directory(root)
    result = {}
    try:
        for name in names:
            require(type(name) is str and Path(name).name == name and name not in {'.', '..'})
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW') | getattr(os, 'O_NONBLOCK')
            child = os.open(name, flags, dir_fd=fd)
            try:
                before = os.fstat(child)
                require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= SOURCE_LIMIT)
                pieces, left = [], before.st_size
                while left:
                    piece = os.read(child, min(left, 1024**2))
                    require(bool(piece))
                    pieces.append(piece)
                    left -= len(piece)
                require(os.read(child, 1) == b'' and _stamp(os.fstat(child)) == _stamp(before)
                        and _stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) == _stamp(before))
                result[name] = b''.join(pieces)
            finally:
                os.close(child)
        return result
    finally:
        os.close(fd)


def local_sources():
    root = Path(__file__).absolute().parent.parent / 'platform' / 'agent_factory'
    sources = read_files(root, [name + '.py' for name in LOCAL_SHA256])
    require(all(hashlib.sha256(sources[name + '.py']).hexdigest() == expected for name, expected in LOCAL_SHA256.items()))
    return sources


def load_local_modules(sources):
    """Fresh worker only. Execute exact pinned Factory source, without filesystem imports."""
    require(not any(name == 'agent_factory' or name.startswith('agent_factory.') for name in sys.modules))
    modules = {}
    for basename in LOCAL_SHA256:
        name = 'agent_factory' if basename == '__init__' else 'agent_factory.' + basename
        module = ModuleType(name)
        module.__package__ = 'agent_factory'
        module.__file__ = '<reviewed-' + basename + '>'
        if basename == '__init__':
            module.__path__ = []
        sys.modules[name] = module
        exec(compile(sources[basename + '.py'], module.__file__, 'exec'), module.__dict__)
        modules[basename] = module
    return modules


def generate_architecture(source_root, modules):
    profile = modules['research_profile']
    files = read_files(source_root, profile.SOURCE_SHA256)
    profile.verify_upstream_source(files)
    bundle = modules['research_training_adapter'].build_training_bundle(files, files, microbatch=1)
    source = bundle['generatedFiles']['trusted_architecture.py']
    expected = bundle['receipt']['generatedSha256']['trusted_architecture.py']
    require(hashlib.sha256(source).hexdigest() == expected)
    return source, expected


def load_architecture(source):
    # Only generated architecture/optimizer definitions, never the training tail.
    module = ModuleType('trusted_architecture')
    module.__file__ = '<verified-generated-trusted-architecture>'
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module



def allocator(torch):
    values = {name: getattr(torch.cuda, name)(0) for name in
              ('memory_allocated', 'memory_reserved', 'max_memory_allocated', 'max_memory_reserved')}
    require(all(type(v) is int and 0 <= v <= 2**63 - 1 for v in values.values()), 'ALLOCATOR_LIMIT')
    return values


def worker_resources():
    import resource
    usage = getattr(resource, 'getrusage')(getattr(resource, 'RUSAGE_SELF'))
    return {'userCpuSeconds': usage.ru_utime, 'systemCpuSeconds': usage.ru_stime,
            'peakRssKiB': int(usage.ru_maxrss)}


def run_model(torch, architecture, emit):
    """Exactly two small optimizer steps, NOT two full accumulated training steps."""
    torch.cuda.set_device(0); torch.manual_seed(42); torch.cuda.manual_seed(42)
    torch.set_float32_matmul_precision('high'); torch.cuda.reset_peak_memory_stats(0)
    def phase(name, fn):
        torch.cuda.synchronize()
        started = time.monotonic()
        metrics = allocator(torch)
        emit({'phase': name, 'state': 'started', 'allocator': metrics})
        require(max(metrics.values()) <= ALLOCATOR_BYTES, 'ALLOCATOR_LIMIT')
        value = fn()
        torch.cuda.synchronize()
        metrics = allocator(torch)
        emit({'phase': name, 'state': 'completed', 'elapsedSeconds': time.monotonic() - started,
              'allocator': metrics, 'resources': worker_resources()})
        require(max(metrics.values()) <= ALLOCATOR_BYTES, 'ALLOCATOR_LIMIT')
        return value
    def setup():
        with torch.device('meta'):
            model = architecture.GPT(architecture.GPTConfig(**MODEL))
        model.to_empty(device='cuda:0'); model.init_weights(); model.train()
        return model, model.setup_optimizer(**OPTIMIZER)
    model, optimizer = phase('model_setup', setup)
    compiled = phase('compile_registration', lambda: torch.compile(model, dynamic=False))
    x = torch.arange(2048, device='cuda:0').remainder(8192).unsqueeze(0)
    y = (x + 1).remainder(8192)
    parameters = list(model.parameters())
    count = sum(p.numel() for p in parameters)
    require(type(count) is int and 0 < count <= 200_000_000, 'NONFINITE')
    def finite(value):
        require(bool(torch.isfinite(value).all().item()), 'NONFINITE')
    def forward(target):
        with torch.amp.autocast(device_type='cuda', dtype=torch.bfloat16):
            loss = target(x, y)
        require(loss.ndim == 0, 'NONFINITE'); finite(loss)
        return loss
    for step in range(2):
        loss = phase(f'round{step + 1}_forward', lambda: forward(compiled))
        def backward():
            (loss / 256).backward()  # 2048/524288, only ONE of the usual 256 microbatches.
            for p in parameters:
                require(p.grad is not None, 'NONFINITE'); finite(p.grad)
        phase(f'round{step + 1}_backward', backward)
        def optimize():
            for group in optimizer.param_groups:
                group['lr'] = group['initial_lr']  # Fixed progress=0, original warmup multiplier 1.
                if group['kind'] == 'muon':
                    group['momentum'] = (1 - step / 300) * .85 + (step / 300) * .95
                    group['weight_decay'] = .2
            optimizer.step()
            for p in parameters:
                finite(p)
            for state in optimizer.state.values():
                for value in state.values():
                    if torch.is_tensor(value):
                        finite(value)
                    elif type(value) in (int, float):
                        require(math.isfinite(value), 'NONFINITE')
                    else:
                        require(False, 'NONFINITE')
            model.zero_grad(set_to_none=True)
        phase(f'round{step + 1}_optimizer', optimize)
    model.eval()
    with torch.no_grad():
        for index in range(2):
            phase(f'eager_eval{index + 1}', lambda: forward(model))
    return {'parameterCount': count, 'optimizerSteps': 2, 'forwardBackwardMicrobatches': 2,
            'eagerEvaluationForwards': 2, 'parametersAndOptimizerStateFinite': True}


def run_probe(source_root, emit):
    torch = None
    try:
        started = time.monotonic(); emit({'phase': 'dependencies', 'state': 'started'})
        modules = load_local_modules(local_sources())
        source, sha = generate_architecture(source_root, modules)
        import torch as selected_torch  # pyright: ignore[reportMissingImports] -- operator target only
        torch = selected_torch
        version = torch.__version__
        require(issubclass(type(version), str) and re.fullmatch(r'2\.9\.1(?:\+[A-Za-z0-9._-]{1,40})?',
                str.__str__(version)) and torch.version.cuda == '12.8', 'VERSION_MISMATCH')
        require(torch.cuda.is_available(), 'CUDA_UNAVAILABLE')
        emit({'phase': 'dependencies', 'state': 'completed', 'elapsedSeconds': time.monotonic() - started})
        started = time.monotonic(); emit({'phase': 'architecture', 'state': 'started'})
        architecture = load_architecture(source)
        emit({'phase': 'architecture', 'state': 'completed', 'elapsedSeconds': time.monotonic() - started,
              'generatedArchitectureSha256': sha})
        metrics = run_model(torch, architecture, emit)
        emit({'result': 'passed', 'generatedArchitectureSha256': sha, **metrics})
    except BaseException as error:
        code = error.args[0] if type(error) is ProbeError and error.args and error.args[0] in ERRORS else 'PROBE_FAILED'
        oom = getattr(getattr(torch, 'cuda', None), 'OutOfMemoryError', None)
        if isinstance(oom, type) and isinstance(error, oom):
            code = 'CUDA_OUT_OF_MEMORY'
        failure = {'result': 'failed', 'errorCode': code}
        if torch is not None:
            try:
                failure['allocator'] = allocator(torch)
            except BaseException:
                pass
        emit(failure)


def report():
    return {'schema': 1, 'evidenceKind': 'bounded_optimizer_compile_diagnostic', 'passed': False,
        'baseRevision': BASE_REVISION, 'localSourceSha256': LOCAL_SHA256, 'model': MODEL, 'seed': 42, 'batchSize': 1,
        'microbatchesPerOptimizerStep': 1, 'fullTrainingAccumulationMicrobatches': 256,
        'factoryExecutionVerified': False, 'scientificConclusionVerified': False,
        'fullWarmupVerified': False, 'fullEvaluationVerified': False, 'baselineVerified': False,
        'valBpbProduced': False, 'checkpointProduced': False, 'totalGpuMemoryBounded': False,
        'limits': {'wallSeconds': WALL_SECONDS, 'perProcessCpuSeconds': CPU_SECONDS,
            'singleFileBytes': FILE_BYTES, 'observedAggregateCacheBytes': CACHE_BYTES,
            'outputBytes': OUTPUT_BYTES, 'compilerThreads': 1,
            'aggregateCpuHardQuota': False, 'aggregateDiskHardQuota': False},
        'compileTimingNote': 'lazy code generation included in first forward/backward/optimizer phases',
        'evaluationTimingScope': 'two eager forwards only; not the full evaluation or a duration promise',
        'cacheMeasurement': 'sampled logical bytes; threshold may be exceeded between observations',
        'events': [], 'cachePeakBytes': 0, 'observedCpuSeconds': 0.0,
        'originalGroupStopped': False, 'scratchRemoved': False}


def validate_allocator(value):
    require(type(value) is dict and set(value) ==
        {'memory_allocated', 'memory_reserved', 'max_memory_allocated', 'max_memory_reserved'}
        and all(type(v) is int and 0 <= v <= 2**63 - 1 for v in value.values()), 'OUTPUT_INVALID')


def validate_event(value):
    require(type(value) is dict, 'OUTPUT_INVALID')
    if 'result' in value:
        if value.get('result') == 'failed':
            require({'result', 'errorCode'} <= set(value) <= {'result', 'errorCode', 'allocator'}
                    and value['errorCode'] in ERRORS, 'OUTPUT_INVALID')
            if 'allocator' in value:
                validate_allocator(value['allocator'])
        else:
            require(set(value) == {'result', 'generatedArchitectureSha256', 'parameterCount', 'optimizerSteps',
                'forwardBackwardMicrobatches', 'eagerEvaluationForwards', 'parametersAndOptimizerStateFinite'}
                and value['result'] == 'passed' and type(value['parameterCount']) is int
                and 0 < value['parameterCount'] <= 200_000_000
                and type(value['generatedArchitectureSha256']) is str
                and re.fullmatch('[a-f0-9]{64}', value['generatedArchitectureSha256'])
                and all(type(value[k]) is int and value[k] == 2 for k in
                    ('optimizerSteps', 'forwardBackwardMicrobatches', 'eagerEvaluationForwards'))
                and value['parametersAndOptimizerStateFinite'] is True, 'OUTPUT_INVALID')
        return value
    require(value.get('phase') in PHASES and value.get('state') in {'started', 'completed'}
            and set(value) <= {'phase', 'state', 'elapsedSeconds', 'allocator', 'resources', 'generatedArchitectureSha256'}, 'OUTPUT_INVALID')
    if 'generatedArchitectureSha256' in value:
        require(value['phase'] == 'architecture' and value['state'] == 'completed'
                and type(value['generatedArchitectureSha256']) is str
                and re.fullmatch('[a-f0-9]{64}', value['generatedArchitectureSha256']), 'OUTPUT_INVALID')
    require(('elapsedSeconds' in value) == (value['state'] == 'completed'), 'OUTPUT_INVALID')
    if 'elapsedSeconds' in value:
        v = value['elapsedSeconds']
        require(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= WALL_SECONDS, 'OUTPUT_INVALID')
    if 'allocator' in value:
        validate_allocator(value['allocator'])
    if 'resources' in value:
        r = value['resources']
        require(type(r) is dict and set(r) == {'userCpuSeconds', 'systemCpuSeconds', 'peakRssKiB'}
            and all(type(v) in (int, float) and math.isfinite(cast(float, v)) and 0 <= cast(float, v) <= 2**40 for v in r.values()), 'OUTPUT_INVALID')
    return value


def proc_identity(pid):
    require(type(pid) is int and pid >= 1, 'SUPERVISOR_UNAVAILABLE')
    raw = Path(f'/proc/{pid}/stat').read_bytes()
    require(len(raw) <= 8192, 'SUPERVISOR_UNAVAILABLE')
    fields = raw[raw.rfind(b')') + 2:].split()
    require(len(fields) >= 20, 'SUPERVISOR_UNAVAILABLE')
    return {'pid': pid, 'state': fields[0].decode('ascii'), 'parent': int(fields[1]),
            'group': int(fields[2]), 'start': int(fields[19]), 'cpuTicks': int(fields[11]) + int(fields[12])}


def group_members(group):
    members = []
    entries = list(Path('/proc').iterdir())
    require(len(entries) <= 32768, 'SUPERVISOR_UNAVAILABLE')
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            value = proc_identity(int(entry.name))
        except FileNotFoundError:
            continue
        if value['group'] == group:
            members.append(value)
    return members


def adopted_children():
    entries = list(Path('/proc').iterdir())
    require(len(entries) <= 32768, 'SUPERVISOR_UNAVAILABLE')
    children = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            identity = proc_identity(int(entry.name))
        except FileNotFoundError:
            continue
        if identity['parent'] == os.getpid():
            children.append(identity['pid'])
    return children


def stop_adopted(pid, identity):
    # The dedicated subreaper began childless. Verify current adopted ownership
    # around pidfd acquisition; signal only this held process identity. An escape
    # still invalidates whole-tree proof, even if this process is stopped.
    require(identity['parent'] == os.getpid(), 'STOP_UNCONFIRMED')
    fd = getattr(os, 'pidfd_open')(pid, 0)
    try:
        current = proc_identity(pid)
        require(current['parent'] == os.getpid() and current['start'] == identity['start'], 'STOP_UNCONFIRMED')
        getattr(signal, 'pidfd_send_signal')(fd, getattr(signal, 'SIGKILL'))
        os.waitpid(pid, getattr(os, 'WNOHANG'))
    finally:
        os.close(fd)


def stop_group(process, pin, *, grace=CLEANUP_SECONDS):
    """Do not poll/reap the leader until SIGKILL targets its pinned live/zombie group.

    Holding the original unreaped leader prevents PID reuse while signalling its
    compiler descendants. Absence is confirmed by /proc plus reaping adopted group
    children; escaped or unreadable descendants make custody UNKNOWN.
    """
    proof = {'leaderReaped': False, 'groupEmpty': False, 'adoptedChildrenEmpty': False}
    escaped_seen = False
    try:
        current = proc_identity(process.pid)
        require(current['start'] == pin['start'] and current['group'] == process.pid == pin['group'], 'STOP_UNCONFIRMED')
        try:
            getattr(os, 'killpg')(process.pid, getattr(signal, 'SIGKILL'))
        except ProcessLookupError:
            pass
        process.wait(timeout=grace)
        proof['leaderReaped'] = True
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            while True:
                try:
                    child, _ = os.waitpid(-pin['group'], getattr(os, 'WNOHANG'))
                except ChildProcessError:
                    break
                if not child:
                    break
            children = adopted_children()
            for child in children[:128]:
                try:
                    identity = proc_identity(child)
                    if identity['group'] != pin['group']:
                        escaped_seen = True
                        stop_adopted(child, identity)
                except FileNotFoundError:
                    continue
            proof['groupEmpty'] = not group_members(pin['group'])
            proof['adoptedChildrenEmpty'] = not adopted_children() and not escaped_seen
            if all(proof.values()):
                return proof
            time.sleep(.02)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return proof


def scan_cache(path):
    count, total = 0, 0
    def visit(fd, depth):
        nonlocal count, total
        require(depth <= 20, 'CACHE_LIMIT')
        for entry in os.scandir(fd):
            count += 1
            require(count <= MAX_ENTRIES, 'CACHE_LIMIT')
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                require(info.st_nlink == 1, 'CACHE_LIMIT')
                total += info.st_size
                if info.st_size > FILE_BYTES or total > CACHE_BYTES:
                    raise ProbeError('CACHE_LIMIT', total)
            elif stat.S_ISDIR(info.st_mode):
                try:
                    child = os.open(entry.name, os.O_RDONLY | getattr(os, 'O_DIRECTORY') | getattr(os, 'O_NOFOLLOW'), dir_fd=fd)
                except FileNotFoundError:
                    continue
                try:
                    visit(child, depth + 1)
                finally:
                    os.close(child)
            else:
                require(False, 'CACHE_LIMIT')
    fd = _directory(path)
    try:
        visit(fd, 0)
    finally:
        os.close(fd)
    return total


def clean_environment(scratch, device):
    require(type(device) is str and re.fullmatch(r'GPU-[a-fA-F0-9-]{8,80}', device), 'SUPERVISOR_UNAVAILABLE')
    value = {key: str(scratch) for key in ('HOME', 'TMPDIR', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR',
        'CUDA_CACHE_PATH', 'PYTHONPYCACHEPREFIX', 'HF_HOME')}
    value.update(PATH=os.defpath, LANG='C.UTF-8', LC_ALL='C.UTF-8', CUDA_VISIBLE_DEVICES=device,
        HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONNOUSERSITE='1',
        PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
        TORCHINDUCTOR_COMPILE_THREADS='1', MAX_JOBS='1', SETUPTOOLS_USE_DISTUTILS='local')
    return value


def exclusive_json(path, value):
    raw = json.dumps(value, allow_nan=False, separators=(',', ':')).encode()
    require(len(raw) <= OUTPUT_BYTES, 'OUTPUT_INVALID')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW'), 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw); stream.flush(); os.fsync(fd)
    finally:
        os.close(fd)


_WORKER = '''import os,resource,runpy,sys,signal,json
resource.setrlimit(resource.RLIMIT_CPU,(300,300))
resource.setrlimit(resource.RLIMIT_FSIZE,(268435456,268435456))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
module=runpy.run_path(sys.argv[1],run_name='optimizer_probe_worker')
output=os.dup(1)
def emit(value):
 raw=json.dumps(value,allow_nan=False,separators=(',',':')).encode()+b'\\n'
 if len(raw)>8192: raise ValueError('OUTPUT_INVALID')
 os.write(output,raw)
with open(os.devnull,'wb') as sink:
 os.dup2(sink.fileno(),1); os.dup2(sink.fileno(),2)
module['run_probe'](sys.argv[2],emit)
# Group anchor remains alive until supervisor signals the original group.
while True: signal.pause()
'''


_START_GATE = "import os,sys; gate=os.read(0,1); gate==b'G' or sys.exit(2); os.execv(sys.argv[1],sys.argv[1:])"


def _supervise_command(command, scratch, environment, *, wall=WALL_SECONDS):
    """Private stdlib seam for tests. CLI exposes only the fixed worker command."""
    value = report(); process = None; pin = None
    old_subreaper = ctypes.c_int()
    libc = ctypes.CDLL(None, use_errno=True)
    require(libc.prctl(37, ctypes.byref(old_subreaper), 0, 0, 0) == 0
            and not adopted_children(), 'SUPERVISOR_UNAVAILABLE')
    require(libc.prctl(36, 1, 0, 0, 0) == 0, 'SUPERVISOR_UNAVAILABLE')
    started = time.monotonic(); pending = bytearray(); count = 0; result = None; cpu_seen = {}
    try:
        require(signal.getsignal(getattr(signal, 'SIGCHLD')) == signal.SIG_DFL, 'SUPERVISOR_UNAVAILABLE')
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', _START_GATE, *command],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True, env=environment, cwd=scratch)
        pin = proc_identity(process.pid)
        require(pin['group'] == process.pid, 'SUPERVISOR_UNAVAILABLE')
        assert process.stdin is not None
        process.stdin.write(b'G'); process.stdin.close()
        assert process.stdout is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while result is None:
                require(time.monotonic() - started < wall, 'TIMEOUT')
                value['cachePeakBytes'] = max(value['cachePeakBytes'], scan_cache(scratch))
                for member in group_members(pin['group']):
                    key = (member['pid'], member['start'])
                    cpu_seen[key] = max(cpu_seen.get(key, 0), member['cpuTicks'])
                value['observedCpuSeconds'] = sum(cpu_seen.values()) / getattr(os, 'sysconf')('SC_CLK_TCK')
                require(value['observedCpuSeconds'] <= CPU_SECONDS, 'CPU_LIMIT')
                if not selector.select(.05):
                    continue
                block = os.read(process.stdout.fileno(), 4096)
                require(bool(block), 'OUTPUT_INVALID')
                count += len(block); require(count <= OUTPUT_BYTES, 'OUTPUT_INVALID')
                pending.extend(block)
                while b'\n' in pending:
                    line, _, rest = pending.partition(b'\n'); pending = bytearray(rest)
                    event = validate_event(json.loads(line, parse_constant=lambda _: require(False, 'OUTPUT_INVALID')))
                    require(len(value['events']) < 40 and result is None, 'OUTPUT_INVALID')
                    if 'result' in event:
                        result = event
                    else:
                        expected = PHASES[len(value['events']) // 2]
                        require(event['phase'] == expected and event['state'] ==
                                ('started' if len(value['events']) % 2 == 0 else 'completed'), 'OUTPUT_INVALID')
                        value['events'].append(event)
                        if 'allocator' in event:
                            require(max(event['allocator'].values()) <= ALLOCATOR_BYTES, 'ALLOCATOR_LIMIT')
            require(not pending, 'OUTPUT_INVALID')
        if result['result'] == 'passed':
            require(len(value['events']) == len(PHASES) * 2, 'OUTPUT_INVALID')
            value['metrics'] = result
            value['passed'] = True
        else:
            value['errorCode'] = result['errorCode']
            value['failure'] = result
    except ProbeError as error:
        if len(error.args) == 2 and error.args[0] == 'CACHE_LIMIT' and type(error.args[1]) is int:
            value['cachePeakBytes'] = max(value['cachePeakBytes'], error.args[1])
        value['errorCode'] = error.args[0] if error.args and error.args[0] in ERRORS else 'PROBE_FAILED'
    except BaseException:
        value['errorCode'] = 'PROBE_FAILED'
    finally:
        value['workElapsedSeconds'] = time.monotonic() - started
        if process is not None and pin is not None:
            proof = stop_group(process, pin)
            value['stopProof'] = proof
            value['originalGroupStopped'] = all(proof.values())
        elif process is not None:
            # This Popen child has never been polled/reaped and SIGCHLD is default;
            # its PID cannot be recycled. Best-effort stop is not a custody proof.
            try:
                if getattr(os, 'getpgid')(process.pid) == process.pid:
                    getattr(os, 'killpg')(process.pid, getattr(signal, 'SIGKILL'))
                else:
                    os.kill(process.pid, getattr(signal, 'SIGKILL'))
                process.wait(timeout=CLEANUP_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass
        value['elapsedSeconds'] = time.monotonic() - started
        if process is not None and process.stdout is not None:
            process.stdout.close()
        if process is not None and process.stdin is not None:
            process.stdin.close()
        if not value['originalGroupStopped']:
            value['passed'] = False
            value['stopErrorCode'] = 'STOP_UNCONFIRMED'
        libc.prctl(36, old_subreaper.value, 0, 0, 0)
    return value


def supervise(source_root, scratch_root, device):
    value = report()
    try:
        require(sys.platform == 'linux', 'SUPERVISOR_UNAVAILABLE')
        local_sources()  # Parent checks exact current closure before any child launch.
        root_fd = _directory(scratch_root)
        try:
            info = os.fstat(root_fd)
            require(info.st_uid == getattr(os, 'getuid')() and stat.S_IMODE(info.st_mode) == 0o700,
                    'SUPERVISOR_UNAVAILABLE')
        finally:
            os.close(root_fd)
        scratch_root = Path(scratch_root)
        exclusive_json(scratch_root / 'attempt.json', {'schema': 1, 'limits': value['limits']})
        scratch = scratch_root / 'owned-cache'
        scratch.mkdir(mode=0o700)
        scratch_pin = scratch.stat()
        command = [sys.executable, '-I', '-B', '-c', _WORKER, str(Path(__file__).absolute()), str(source_root)]
        value = _supervise_command(command, scratch, clean_environment(scratch, device))
        if value['originalGroupStopped']:
            current = scratch.lstat()
            require(stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) ==
                    (scratch_pin.st_dev, scratch_pin.st_ino), 'STOP_UNCONFIRMED')
            shutil.rmtree(scratch)
            value['scratchRemoved'] = True
        exclusive_json(scratch_root / 'result.json', value)
    except (OSError, ValueError, TypeError):
        value['passed'] = False
        value.setdefault('errorCode', 'SUPERVISOR_UNAVAILABLE')
    return value


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        print('{"schema":1,"passed":false,"errorCode":"ARGUMENTS_INVALID"}', file=sys.stderr)
        raise SystemExit(2)


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--scratch-root', type=Path, required=True)
    parser.add_argument('--device', required=True)
    args = parser.parse_args(argv)
    value = supervise(args.source_root, args.scratch_root, args.device)
    print(json.dumps(value, allow_nan=False, separators=(',', ':')))
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
