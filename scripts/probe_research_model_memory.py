"""One supervised, fixed eager-model diagnostic; never a Factory training run."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import cast

BASE_REVISION = '87f7227fae1d4a39ba85db6f68d96061f9f4de3a'
WALL_SECONDS = 120
KILL_GRACE_SECONDS = 5
MAX_OUTPUT_BYTES = 16384
MAX_OBSERVED_ALLOCATOR_BYTES = 8 * 1024**3
SOURCE_LIMIT = 4 * 1024**2
# Exact reviewed local closure: load captured source bytes, never a stale .pyc.
LOCAL_SHA256 = {
    '__init__': '34a3ecc32ec01bb74feee444a052919b9407ef081460c8a4546bae3f438c163a',
    'research_candidate': '61814f7dc86bef20dc38e375c831d5bf822ffb4555bc13e832adb3adc6a26197',
    'research_profile': 'b410187bfc2530264363dfcf32c5cf8236848c071f8fb0f2a992de4a9d5bcb45',
    'research_manifest': '1bc6331885191fe08b8f683c547ba30fa0160b5521f3b5f0bc0c441973cd97f9',
    'research_assessment': 'd65fceff622b6ea1f5513b2081d0dc7a15ab04a66fdb13a850bfa3884458aee3',
    'research_evaluation': 'abaaeea583c5316aa0be04814f593ae27c6b7943532aaa8138e530708a427080',
    'research_checkpoint': 'a9c3a12bc5a94065a6cc6fc254632c22f14ac8daf815b5009ca29725bcdf585f',
    'research_torch_runtime': 'cd3c9e3edc1800f495fd0c3e4ed9bdef03b077d918883262e19f1fd192774dde',
    'research_training_adapter': 'c63ce79249796d4afdc5be7347f36a293d1657a3139c7a640986feb88d01a3da',
}
MODEL = {'sequence_len': 2048, 'vocab_size': 8192, 'n_layer': 8, 'n_head': 4,
         'n_kv_head': 4, 'n_embd': 512, 'window_pattern': 'SSSL'}
ERRORS = frozenset({'SOURCE_INVALID', 'DEPENDENCY_UNAVAILABLE', 'VERSION_MISMATCH',
    'CUDA_UNAVAILABLE', 'CUDA_OUT_OF_MEMORY', 'MODEL_NONFINITE', 'ALLOCATOR_LIMIT',
    'PROBE_FAILED', 'TIMEOUT', 'OUTPUT_INVALID', 'SUPERVISOR_UNAVAILABLE'})


class ProbeError(ValueError):
    pass


def require(value, code='SOURCE_INVALID'):
    if not value:
        raise ProbeError(code)


def report(code=None):
    value = {'schema': 1, 'evidenceKind': 'bounded_eager_model_memory_diagnostic', 'passed': False,
        'baseRevision': BASE_REVISION,
        'factoryExecutionVerified': False, 'scientificConclusionVerified': False,
        'compiledTrainingFitVerified': False, 'trainingExecuted': False,
        'optimizerStepExecuted': False, 'modelCompileExecuted': False,
        'checkpointProduced': False, 'totalGpuMemoryBounded': False,
        'wallTimeoutSeconds': WALL_SECONDS, 'killGraceSeconds': KILL_GRACE_SECONDS,
        'batchSize': 1, 'model': dict(MODEL), 'seed': 42}
    if code is not None:
        value['errorCode'] = code if code in ERRORS else 'PROBE_FAILED'
    return value


def _directory(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts and os.name == 'posix')
    nofollow, directory = getattr(os, 'O_NOFOLLOW', None), getattr(os, 'O_DIRECTORY', None)
    require(type(nofollow) is int and type(directory) is int)
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
    # This file includes compiled optimizer function decorators; no optimizer
    # function, optimizer.step(), torch.compile(model), or training tail is called.
    module = ModuleType('trusted_architecture')
    module.__file__ = '<verified-generated-trusted-architecture>'
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, 'exec'), module.__dict__)
    return module


def _memory(torch):
    names = ('memory_allocated', 'memory_reserved', 'max_memory_allocated', 'max_memory_reserved')
    values = {name: getattr(torch.cuda, name)(0) for name in names}
    require(all(type(value) is int and 0 <= value <= 2**40 for value in values.values()), 'ALLOCATOR_LIMIT')
    return values


def run_model(torch, architecture):
    torch.cuda.set_device(0)
    torch.manual_seed(42)
    torch.cuda.manual_seed(42)
    torch.set_float32_matmul_precision('high')
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats(0)
    before = _memory(torch)
    started = time.monotonic()
    with torch.device('meta'):
        model = architecture.GPT(architecture.GPTConfig(**MODEL))
    model.to_empty(device='cuda:0')
    model.init_weights()
    model.train()
    x = torch.arange(2048, device='cuda:0').remainder(8192).unsqueeze(0)
    y = (x + 1).remainder(8192)
    with torch.amp.autocast(device_type='cuda', dtype=torch.bfloat16):
        loss = model(x, y)
    require(loss.ndim == 0 and bool(torch.isfinite(loss).all().item()), 'MODEL_NONFINITE')
    loss.backward()
    parameters = list(model.parameters())
    parameter_count = sum(parameter.numel() for parameter in parameters)
    require(type(parameter_count) is int and 0 < parameter_count <= 200_000_000, 'MODEL_NONFINITE')
    require(all(parameter.grad is not None and bool(torch.isfinite(parameter.grad).all().item())
                for parameter in parameters), 'MODEL_NONFINITE')
    torch.cuda.synchronize()
    scalar = float(loss.detach().item())
    elapsed = time.monotonic() - started
    require(math.isfinite(scalar) and 0 <= scalar <= 100 and math.isfinite(elapsed) and 0 <= elapsed <= WALL_SECONDS,
            'MODEL_NONFINITE')
    after = _memory(torch)
    require(after['max_memory_allocated'] <= MAX_OBSERVED_ALLOCATOR_BYTES
            and after['max_memory_reserved'] <= MAX_OBSERVED_ALLOCATOR_BYTES, 'ALLOCATOR_LIMIT')
    return {'syntheticLoss': scalar, 'gradientsFinite': True, 'parameterCount': parameter_count,
            'elapsedSeconds': round(elapsed, 6), 'allocatorBefore': before, 'allocatorAfter': after}


def torch_version_matches(value):
    # TorchVersion is a legitimate str subclass. Invoke the base descriptor,
    # never an arbitrary object's or subclass's overridden __str__ method.
    if not isinstance(value, str):
        return False
    plain = str.__str__(value)
    return type(plain) is str and re.fullmatch(r'2\.9\.1(?:\+[A-Za-z0-9._-]{1,40})?', plain) is not None


def run_probe(source_root):
    result = report()
    torch = None
    try:
        sources = local_sources()
        modules = load_local_modules(sources)
        source, identity = generate_architecture(source_root, modules)
        import torch as selected_torch  # pyright: ignore[reportMissingImports] -- target-only optional dependency
        torch = selected_torch
        require(torch_version_matches(torch.__version__)
                and torch.version.cuda == '12.8', 'VERSION_MISMATCH')
        require(torch.cuda.is_available(), 'CUDA_UNAVAILABLE')
        architecture = load_architecture(source)
        result.update(run_model(torch, architecture))
        result.update(passed=True, generatedArchitectureSha256=identity,
            adapterSha256=LOCAL_SHA256['research_torch_runtime'],
            optimizerCompileDecoratorsRegistered=True, torchVersion='2.9.1', torchCudaVersion='12.8')
    except ProbeError as error:
        result['errorCode'] = error.args[0] if error.args and error.args[0] in ERRORS else 'PROBE_FAILED'
    except ImportError:
        result['errorCode'] = 'DEPENDENCY_UNAVAILABLE'
    except Exception as error:
        oom = getattr(getattr(torch, 'cuda', None), 'OutOfMemoryError', None)
        result['errorCode'] = 'CUDA_OUT_OF_MEMORY' if isinstance(oom, type) and isinstance(error, oom) else 'PROBE_FAILED'
    return result


_WORKER = '''import os,runpy,sys
module=runpy.run_path(sys.argv[1],run_name='memory_probe_worker')
output=os.dup(1)
with open(os.devnull,'wb') as sink:
 os.dup2(sink.fileno(),1); os.dup2(sink.fileno(),2)
result=module['run_probe'](sys.argv[2])
payload=module['json'].dumps(result,allow_nan=False,separators=(',',':')).encode()
if len(payload)<=module['MAX_OUTPUT_BYTES']: os.write(output,payload)
os.close(output)
'''


def _kill(process):
    # poll reaps a finished original child; never signal a potentially reused ID.
    if process.poll() is not None:
        return True
    try:
        getattr(os, 'killpg')(process.pid, getattr(signal, 'SIGKILL'))
    except ProcessLookupError:
        pass
    except OSError:
        return False
    try:
        process.wait(timeout=KILL_GRACE_SECONDS)
        return True
    except subprocess.TimeoutExpired:
        return False


def supervise(source_root):
    """One owned group; bounded stdout and external CUDA-stall deadline."""
    if os.name != 'posix':
        return report('SUPERVISOR_UNAVAILABLE')
    process, scratch, stopped = None, None, True
    try:
        scratch = tempfile.mkdtemp(prefix='research-model-preflight-')
        environment = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'HOME': scratch,
            'TMPDIR': scratch, 'TORCHINDUCTOR_CACHE_DIR': scratch, 'TRITON_CACHE_DIR': scratch,
            'CUDA_CACHE_PATH': scratch, 'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1',
            'TRANSFORMERS_OFFLINE': '1', 'OMP_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2'}
        # Sole operator-selected visibility value; no ambient credentials copied.
        visible = os.environ.get('CUDA_VISIBLE_DEVICES')
        if visible is not None:
            require(len(visible) <= 256 and '\x00' not in visible)
            environment['CUDA_VISIBLE_DEVICES'] = visible
        try:
            process = subprocess.Popen([sys.executable, '-I', '-B', '-c', _WORKER,
                str(Path(__file__).absolute()), str(source_root)], stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, env=environment, start_new_session=True)
            assert process.stdout is not None
            pieces = bytearray()
            deadline = time.monotonic() + WALL_SECONDS
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return report('TIMEOUT')
                    if not selector.select(min(remaining, 1)):
                        continue
                    block = os.read(process.stdout.fileno(), min(4096, MAX_OUTPUT_BYTES + 1 - len(pieces)))
                    if not block:
                        break
                    pieces.extend(block)
                    if len(pieces) > MAX_OUTPUT_BYTES:
                        return report('OUTPUT_INVALID')
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            require(process.returncode == 0, 'OUTPUT_INVALID')
            value = json.loads(pieces, parse_constant=lambda _: require(False, 'OUTPUT_INVALID'))
            require(type(value) is dict and value.get('schema') == 1 and value.get('evidenceKind') == report()['evidenceKind'], 'OUTPUT_INVALID')
            # Child code is fixed; a successful result still never means training fit.
            require(value.get('factoryExecutionVerified') is False and value.get('scientificConclusionVerified') is False
                    and value.get('compiledTrainingFitVerified') is False and len(pieces) <= MAX_OUTPUT_BYTES, 'OUTPUT_INVALID')
            base = report()
            extras = {'syntheticLoss', 'gradientsFinite', 'parameterCount', 'elapsedSeconds', 'allocatorBefore',
                      'allocatorAfter', 'generatedArchitectureSha256', 'adapterSha256',
                      'optimizerCompileDecoratorsRegistered', 'torchVersion', 'torchCudaVersion'}
            require(type(value.get('passed')) is bool and all(value.get(key) == expected for key, expected in base.items() if key != 'passed'), 'OUTPUT_INVALID')
            require(set(value) == set(base) | (extras if value['passed'] else {'errorCode'}), 'OUTPUT_INVALID')
            if not value['passed']:
                require(value['errorCode'] in ERRORS, 'OUTPUT_INVALID')
            else:
                require(value['gradientsFinite'] is True and value['optimizerCompileDecoratorsRegistered'] is True
                        and value['torchVersion'] == '2.9.1' and value['torchCudaVersion'] == '12.8'
                        and value['adapterSha256'] == LOCAL_SHA256['research_torch_runtime'], 'OUTPUT_INVALID')
                sha = value['generatedArchitectureSha256']
                require(type(sha) is str and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha), 'OUTPUT_INVALID')
                require(type(value['parameterCount']) is int and 0 < value['parameterCount'] <= 200_000_000, 'OUTPUT_INVALID')
                for name, maximum in (('syntheticLoss', 100), ('elapsedSeconds', WALL_SECONDS)):
                    scalar = value[name]
                    require(type(scalar) in {int, float} and math.isfinite(scalar) and 0 <= scalar <= maximum, 'OUTPUT_INVALID')
                for name in ('allocatorBefore', 'allocatorAfter'):
                    memory = value[name]
                    require(type(memory) is dict and set(memory) == {'memory_allocated', 'memory_reserved',
                            'max_memory_allocated', 'max_memory_reserved'}
                            and all(type(n) is int and 0 <= n <= MAX_OBSERVED_ALLOCATOR_BYTES for n in memory.values()), 'OUTPUT_INVALID')
            return value
        finally:
            # Includes KeyboardInterrupt/SystemExit: stop before cache cleanup,
            # then allow the original exception to propagate unchanged.
            if process is not None:
                stopped = False
                try:
                    stopped = _kill(process)
                finally:
                    if process.stdout is not None:
                        process.stdout.close()
    except subprocess.TimeoutExpired:
        return report('TIMEOUT')
    except (OSError, ValueError, TypeError):
        return report('OUTPUT_INVALID')
    finally:
        # A timed-out kill wait is not stopped proof. Retain the private cache
        # rather than remove files a possibly live original child is using.
        if scratch is not None and stopped:
            shutil.rmtree(scratch, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path, help='Absolute directory containing the six pinned public upstream files')
    args = parser.parse_args()
    result = supervise(args.source_root)
    print(json.dumps(result, allow_nan=False, separators=(',', ':')))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
