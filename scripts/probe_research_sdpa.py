"""Fixed tiny SDPA compatibility probe; no training, compilation or downloads.

Run with the operator-selected CUDA_VISIBLE_DEVICES; logical device is cuda:0.
The probe has no tuning arguments. External supervision must bound wall time:
a stuck CUDA call cannot be safely timed out inside this Python process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time

CASES = (
    ('causal-full', 5, 1, 1, 5),
    ('window-zero', 5, 1, 1, 0),
    ('window-two', 5, 1, 1, 2),
    ('gqa-window-two', 5, 4, 2, 2),
    ('inclusive-1024', 1026, 1, 1, 1024),
    ('inclusive-1025', 1026, 1, 1, 1025),
)
DIMENSION = 8
TOLERANCE = 0.00003
ADAPTER_SHA256 = 'cd3c9e3edc1800f495fd0c3e4ed9bdef03b077d918883262e19f1fd192774dde'
MAX_ALLOCATED_BYTES = 128 * 1024**2  # Observed tensor-allocation guard, not total GPU memory/quota.


def value_at(position, head, channel):
    if channel == 0:
        return float(position == 0)
    if channel == 1:
        return float(position == 1)
    return float(head == 1 and channel == 2)


def reference(length, query_heads, kv_heads, left):
    """Independent uniform means for zero Q/K, including both window endpoints."""
    return [[[
        sum(value_at(key, head // (query_heads // kv_heads), channel)
            for key in range(max(0, position-left), position+1)) / (min(position, left)+1)
        for channel in range(DIMENSION)] for head in range(query_heads)] for position in range(length)]


def safe_version(value):
    # torch.__version__ is a TorchVersion (str subclass). Read its underlying
    # string directly; never coerce other objects or invoke subclass hooks.
    if not issubclass(type(value), str) or not 1 <= str.__len__(value) <= 80:
        return 'UNKNOWN'
    plain = str.__str__(value)
    return plain if re.fullmatch(r'[A-Za-z0-9.+_-]{1,80}', plain) else 'UNKNOWN'


def run_case(torch, adapter, case):
    name, length, heads, kv_heads, left = case
    device = 'cuda:0'
    q = torch.zeros((1, length, heads, DIMENSION), device=device, dtype=torch.bfloat16, requires_grad=True)
    k = torch.zeros((1, length, kv_heads, DIMENSION), device=device, dtype=torch.bfloat16, requires_grad=True)
    values = [[[value_at(pos, head, channel) for channel in range(DIMENSION)]
               for head in range(kv_heads)] for pos in range(length)]
    v = torch.tensor([values], device=device, dtype=torch.bfloat16, requires_grad=True)
    torch.cuda.synchronize()
    started = time.monotonic()
    output = adapter.flash_attn_func(q, k, v, causal=True, window_size=(left, 0))
    shape_ok = tuple(output.shape) == (1, length, heads, DIMENSION)
    finite = bool(torch.isfinite(output).all().item())
    expected = torch.tensor([reference(length, heads, kv_heads, left)], dtype=torch.float32).to(torch.bfloat16).float()
    error = float((output.detach().float().cpu() - expected).abs().max().item())
    output.float().square().sum().backward()
    gradients = all(item.grad is not None and bool(torch.isfinite(item.grad).all().item()) for item in (q, k, v))
    torch.cuda.synchronize()
    duration = time.monotonic() - started
    peak = int(torch.cuda.max_memory_allocated())
    passed = shape_ok and finite and gradients and error <= TOLERANCE and peak < MAX_ALLOCATED_BYTES
    return {'case': name, 'sequenceLength': length, 'headDimension': DIMENSION, 'queryHeads': heads, 'kvHeads': kv_heads, 'passed': passed, 'shapeMatches': shape_ok, 'forwardFinite': finite,
            'backwardFinite': gradients, 'maxAbsError': error if math.isfinite(error) else None,
            'elapsedSeconds': round(duration, 6), 'peakAllocatedBytes': peak}


def run_nonzero_case(torch, adapter, dimension=128):
    """Independent CPU FP32 matmul/softmax and explicit repeated KV head graph."""
    inputs = []
    for heads, offset in ((2, 1), (1, 2), (1, 3)):
        data = [[[[((position*3 + head*2 + channel + offset) % 7 - 3) / 8
                   for channel in range(dimension)] for head in range(heads)] for position in range(4)]]
        inputs.append(torch.tensor(data, device='cuda:0', dtype=torch.bfloat16, requires_grad=True))
    q, k, v = inputs
    cq, ck, cv = [item.detach().float().cpu().requires_grad_(True) for item in inputs]
    outputs = []
    for head in range(2):
        rows = []
        for position in range(4):
            first = max(0, position-2)
            scores = (ck[0, first:position+1, 0] * cq[0, position, head]).sum(dim=-1) / math.sqrt(dimension)
            rows.append((scores.softmax(dim=0)[:, None] * cv[0, first:position+1, 0]).sum(dim=0))
        outputs.append(torch.stack(rows))
    expected = torch.stack(outputs, dim=1).unsqueeze(0)
    torch.cuda.synchronize()
    started = time.monotonic()
    actual = adapter.flash_attn_func(q, k, v, causal=True, window_size=(2, 0))
    expected.square().sum().backward()
    actual.float().square().sum().backward()
    torch.cuda.synchronize()
    finite = bool(torch.isfinite(actual).all().item())
    gradients = all(item.grad is not None and bool(torch.isfinite(item.grad).all().item()) for item in inputs)
    forward_error = float((actual.detach().float().cpu()-expected.detach()).abs().max().item())
    gradient_error = max(float((item.grad.float().cpu()-ref.grad).abs().max().item())
                         for item, ref in zip(inputs, (cq, ck, cv))) if gradients else None
    peak = int(torch.cuda.max_memory_allocated())
    passed = (finite and gradients and forward_error <= .005 and gradient_error is not None
              and gradient_error <= .02 and peak < MAX_ALLOCATED_BYTES)
    return {'case': 'nonzero-gqa-reference', 'sequenceLength': 4, 'headDimension': dimension, 'queryHeads': 2, 'kvHeads': 1, 'passed': passed, 'forwardFinite': finite, 'backwardFinite': gradients,
        'maxAbsError': forward_error if math.isfinite(forward_error) else None,
        'maxGradientError': gradient_error if gradient_error is not None and math.isfinite(gradient_error) else None,
        'elapsedSeconds': round(time.monotonic()-started, 6), 'peakAllocatedBytes': peak}


def run_probe():
    report = {'schema': 1, 'evidenceKind': 'bounded_sdpa_compatibility_probe', 'passed': False,
              'factoryExecutionVerified': False, 'scientificConclusionVerified': False, 'totalGpuMemoryBounded': False, 'externalTimeoutSeconds': 60, 'cases': []}
    try:
        import torch  # pyright: ignore[reportMissingImports] -- optional target-only dependency
        from agent_factory import research_torch_runtime as adapter_module
        report['torchVersion'] = safe_version(torch.__version__)
        report['torchCudaVersion'] = safe_version(torch.version.cuda)
        if report['torchVersion'].split('+')[0] != '2.9.1' or report['torchCudaVersion'] != '12.8':
            report['errorCode'] = 'VERSION_MISMATCH'
            return report
        with open(adapter_module.__file__, 'rb') as source:
            raw = source.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != ADAPTER_SHA256:
            report['errorCode'] = 'ADAPTER_SOURCE_MISMATCH'
            return report
        report['adapterSourceSha256'] = ADAPTER_SHA256
        if not torch.cuda.is_available():
            report['errorCode'] = 'CUDA_UNAVAILABLE'
            return report
        capability = torch.cuda.get_device_capability(0)
        if (type(capability) is not tuple or len(capability) != 2
                or any(type(value) is not int or not 0 <= value <= 99 for value in capability)):
            report['errorCode'] = 'CAPABILITY_INVALID'
            return report
        report['cudaCapability'] = list(capability)
        torch.cuda.set_device(0)
        torch.cuda.reset_peak_memory_stats()
        adapter = adapter_module.SDPAAdapter(torch)
        for case in CASES:
            result = run_case(torch, adapter, case)
            report['cases'].append(result)
            if not result['passed']:
                report['errorCode'] = 'CASE_FAILED'
                return report
        result = run_nonzero_case(torch, adapter)
        report['cases'].append(result)
        if not result['passed']:
            report['errorCode'] = 'CASE_FAILED'
            return report
        report['passed'] = True
    except ImportError:
        report['errorCode'] = 'DEPENDENCY_UNAVAILABLE'
    except Exception as error:
        # Never emit exception text: CUDA errors may contain paths or details.
        report['errorCode'] = 'CUDA_OUT_OF_MEMORY' if type(error).__name__ == 'OutOfMemoryError' else 'PROBE_FAILED'
    return report


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    result = run_probe()
    print(json.dumps(result, allow_nan=False, separators=(',', ':')))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
