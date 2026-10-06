"""Probe control/reference tests without importing torch or invoking a GPU."""
import importlib.util
from pathlib import Path
import sys
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, mock_open, patch

_SPEC = importlib.util.spec_from_file_location('research_sdpa_probe', Path(__file__).resolve().parents[2] / 'scripts' / 'probe_research_sdpa.py')
assert _SPEC is not None and _SPEC.loader is not None
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


class SdpaProbeTests(unittest.TestCase):
    def torch(self):
        cuda = Mock()
        cuda.is_available.return_value = True
        cuda.get_device_capability.return_value = (12, 0)
        return SimpleNamespace(__version__='2.9.1+cu128', version=SimpleNamespace(cuda='12.8'), cuda=cuda)

    def test_reference_causal_self_and_inclusive_left_boundary(self):
        self.assertEqual(probe.reference(5, 1, 1, 0)[0][0][0], 1)
        self.assertEqual(probe.reference(5, 1, 1, 0)[1][0][0], 0)
        self.assertEqual(probe.reference(5, 1, 1, 2)[2][0][0], 1/3)
        self.assertEqual(probe.reference(5, 1, 1, 2)[3][0][0], 0)
        short = probe.reference(1026, 1, 1, 1024)
        full = probe.reference(1026, 1, 1, 1025)
        self.assertEqual(short[1024][0][0], 1/1025)
        self.assertEqual(short[1025][0][0], 0)
        self.assertEqual(full[1025][0][0], 1/1026)
        self.assertGreater(1/1026, probe.TOLERANCE)

    def test_gqa_reference_repeats_corresponding_kv_heads(self):
        values = probe.reference(5, 4, 2, 2)
        self.assertEqual(values[4][0][2], 0)
        self.assertEqual(values[4][1][2], 0)
        self.assertEqual(values[4][2][2], 1)
        self.assertEqual(values[4][3][2], 1)

    def test_fixed_cases_and_mocked_success_keep_acceptance_false(self):
        torch = self.torch()
        with patch.dict(sys.modules, {'torch': torch}), \
             patch.object(probe, 'run_case', side_effect=lambda _t, _a, case: {'case': case[0], 'passed': True}) as run, \
             patch.object(probe, 'run_nonzero_case', return_value={'case': 'nonzero', 'passed': True}):
            result = probe.run_probe()
        self.assertEqual(run.call_count, 6)
        self.assertEqual(len(result['cases']), 7)
        self.assertTrue(result['passed'])
        self.assertFalse(result['factoryExecutionVerified'])
        self.assertFalse(result['scientificConclusionVerified'])
        self.assertFalse(result['totalGpuMemoryBounded'])
        self.assertEqual(result['cudaCapability'], [12, 0])
        self.assertEqual(result['externalTimeoutSeconds'], 60)

    def test_failure_stops_without_exception_text(self):
        with patch.dict(sys.modules, {'torch': self.torch()}), \
             patch.object(probe, 'run_case', side_effect=RuntimeError('private/path never report')) as run:
            result = probe.run_probe()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result['errorCode'], 'PROBE_FAILED')
        self.assertNotIn('private', str(result))

    def test_no_cuda_or_invalid_capability_never_runs_cases(self):
        for capability in ((True, 0), (12,), 'sm120'):
            torch = self.torch(); torch.cuda.get_device_capability.return_value = capability
            with patch.dict(sys.modules, {'torch': torch}), patch.object(probe, 'run_case') as run:
                self.assertEqual(probe.run_probe()['errorCode'], 'CAPABILITY_INVALID')
                run.assert_not_called()
        torch = self.torch(); torch.cuda.is_available.return_value = False
        with patch.dict(sys.modules, {'torch': torch}):
            self.assertEqual(probe.run_probe()['errorCode'], 'CUDA_UNAVAILABLE')

    def test_bad_metric_case_stops_before_next_case(self):
        with patch.dict(sys.modules, {'torch': self.torch()}), \
             patch.object(probe, 'run_case', return_value={'passed': False}) as run:
            self.assertEqual(probe.run_probe()['errorCode'], 'CASE_FAILED')
            self.assertEqual(run.call_count, 1)

    def test_bf16_reference_rounding_preserves_boundary_discrimination(self):
        def bf16(value):
            bits = struct.unpack('>I', struct.pack('>f', value))[0]
            rounded = (bits + 0x7fff + ((bits >> 16) & 1)) & 0xffff0000
            return struct.unpack('>f', struct.pack('>I', rounded))[0]
        # Normal BF16 1/3 must not be compared directly against raw FP32 1/3.
        self.assertGreater(abs(bf16(1/3) - 1/3), probe.TOLERANCE)
        self.assertEqual(bf16(1/3), 0.333984375)
        self.assertGreater(bf16(1/1026), probe.TOLERANCE)
        self.assertEqual(bf16(0), 0)

    def test_software_mismatch_stops_before_cuda_access(self):
        for version, cuda in (('2.8.0', '12.8'), ('2.9.1', '13.0')):
            torch = self.torch(); torch.__version__ = version; torch.version.cuda = cuda
            with patch.dict(sys.modules, {'torch': torch}):
                result = probe.run_probe()
            self.assertEqual(result['errorCode'], 'VERSION_MISMATCH')
            torch.cuda.is_available.assert_not_called()

    def test_wrong_adapter_source_stops_before_cuda_access(self):
        torch = self.torch()
        with patch.dict(sys.modules, {'torch': torch}), patch('builtins.open', mock_open(read_data=b'wrong implementation')):
            result = probe.run_probe()
        self.assertEqual(result['errorCode'], 'ADAPTER_SOURCE_MISMATCH')
        self.assertNotIn('adapterSourceSha256', result)
        torch.cuda.is_available.assert_not_called()
