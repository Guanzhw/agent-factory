import asyncio
from contextlib import nullcontext
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_factory.gpu_custody import GpuBinding
from agent_factory.research_local_provider import ResearchLocalProvider
from agent_factory.store import digest
from agent_factory.research_interpreter import capture_interpreter_contract
from agent_factory.process_enforcement import ResearchProcessSpec, ResearchProcessLimits, UvResearchProcessSpec


class Observer:
    configuration_fingerprint = 'c'*64
    def __init__(self, status='AVAILABLE'):
        self.status, self.calls = status, []
    def __call__(self, request):
        self.calls.append(request)
        return {'schema': 1, 'requestFingerprint': digest(request), 'status': self.status, 'observationSha256': 'd'*64}


class Verifier:
    def validate_spec(self, spec):
        return None

    configuration_fingerprint = 'e'*64
    def __call__(self, record):
        return {'schema': 1, 'checkpoint': None, 'evaluationContractSha256': None, 'descriptorSha256': '8'*64, 'sourceSha256': self.configuration_fingerprint,
            'manifestSha256': 'f'*64, 'variantSha256': '7'*64}


def fixture():
    observer = Observer()
    with patch('agent_factory.research_local_provider.ProcessResourceProvider.__init__'):
        provider = ResearchLocalProvider(None, None, ResearchProcessSpec.__new__(ResearchProcessSpec),
            ResearchProcessLimits.__new__(ResearchProcessLimits), gpu_binding=GpuBinding('a'*64, 'b'*64),
            source_fingerprint='e'*64, manifest_fingerprint='f'*64, observer=observer, program_verifier=Verifier())
    binding = {'id': 'lease', 'ownerId': 'alice', 'localTaskId': 'task', 'nativeRunId': 'run', 'planId': 'plan',
        'fingerprint': 'a'*64, 'gpuBinding': provider.gpu_binding.to_dict(), 'executionGuard': {'manifestSha256': 'f'*64, 'variantSha256': '7'*64}}
    record = {'binding': binding, 'bindingHash': digest(binding), 'processPin': {'id': 'original', 'identitySha256': '9'*64},
        'allStopped': True, 'stopKind': 'original-root-reaped-and-no-live-process-group-members'}
    snapshot = {'stoppedProof': True, 'stopReceipt': {'kind': 'original-group-stopped'}}
    return provider, observer, record, snapshot


class LocalProviderTests(unittest.TestCase):
    def test_reopened_provider_denies_allocation_before_journal_or_authority(self):
        provider, observer, _, _ = fixture()
        provider._stop_only = True
        with patch('agent_factory.research_local_provider.ProcessResourceProvider.allocate_bound') as allocate:
            with self.assertRaisesRegex(ValueError, 'RESTORED_DISPATCH_FORBIDDEN'):
                asyncio.run(provider.allocate_bound({}, before_effect=lambda: self.fail('no new authority')))
            allocate.assert_not_called()
        self.assertEqual(observer.calls, [])

    def test_busy_and_unknown_block_launch(self):
        for state in ('BUSY', 'UNKNOWN', 'RELEASED'):
            provider, observer, record, snapshot = fixture()
            observer.status = state
            with patch.object(ResearchLocalProvider, 'configuration_fingerprint', 'a'*64), self.assertRaises(ValueError):
                provider._before_launch(record, snapshot)
            self.assertNotIn('gpuLaunchObservationSha256', record)

    def test_available_binds_original_identity(self):
        provider, observer, record, snapshot = fixture()
        with patch.object(ResearchLocalProvider, 'configuration_fingerprint', 'a'*64):
            provider._before_launch(record, snapshot)
        self.assertEqual(record['gpuLaunchObservationSha256'], 'd'*64)
        self.assertEqual(observer.calls[0]['processPin'], record['processPin'])

    def test_release_needs_observation_and_stop(self):
        provider, observer, record, snapshot = fixture()
        with patch.object(ResearchLocalProvider, 'configuration_fingerprint', 'a'*64):
            with self.assertRaises(ValueError):
                provider._before_release(record, snapshot)
            observer.status = 'RELEASED'
            provider._before_release(record, snapshot)
            self.assertEqual(record['gpuReleaseObservationSha256'], 'd'*64)
            snapshot['stoppedProof'] = False
            with self.assertRaises(ValueError):
                provider._before_release(record, snapshot)

    def test_never_dispatched_uses_journal_without_device_query(self):
        provider, observer, record, snapshot = fixture()
        record['stopKind'] = 'never-dispatched'
        snapshot['stopReceipt']['kind'] = 'never-dispatched'
        provider._before_release(record, snapshot)
        self.assertEqual(observer.calls, [])
        self.assertEqual(len(record['gpuReleaseObservationSha256']), 64)

    def test_observer_and_manifest_drift_deny(self):
        provider, observer, record, snapshot = fixture()
        observer.configuration_fingerprint = '0'*64
        with self.assertRaises(ValueError):
            provider._before_launch(record, snapshot)
        observer.configuration_fingerprint = 'c'*64
        record['binding']['executionGuard']['manifestSha256'] = '0'*64
        with self.assertRaises(ValueError):
            provider._before_launch(record, snapshot)

    def test_program_verifier_mandatory_and_bound_before_device_query(self):
        provider, observer, record, snapshot = fixture()
        provider._program_verifier.configuration_fingerprint = '0'*64
        with self.assertRaises(ValueError):
            provider._before_launch(record, snapshot)
        self.assertEqual(observer.calls, [])
        self.assertNotIn('programVerification', record)
        provider._program_verifier = Verifier()
        with patch.object(ResearchLocalProvider, 'configuration_fingerprint', 'a'*64):
            provider._before_launch(record, snapshot)
        self.assertEqual(record['programVerification']['descriptorSha256'], '8'*64)
        self.assertEqual(record['programVerification']['leaseBindingSha256'], record['bindingHash'])

    def test_dynamic_proof_rejects_variant_checkpoint_and_static_string(self):
        provider, _, record, _ = fixture()
        valid = Verifier()(record)
        for changed in ('e'*64, valid | {'variantSha256': '0'*64}, valid | {'checkpoint': {}},
                        valid | {'checkpoint': {'artifactId': 'checkpoint', 'sha256': '3'*64, 'sizeBytes': True},
                                 'evaluationContractSha256': '4'*64}):
            with self.assertRaises(ValueError):
                provider._program_proof(record, changed)
        result = provider._program_proof(record, valid | {'checkpoint': {'artifactId': 'checkpoint',
            'sha256': '3'*64, 'sizeBytes': 10}, 'evaluationContractSha256': '4'*64})
        self.assertEqual(result['checkpoint']['sizeBytes'], 10)

    def test_launch_proof_revalidates_current_original_journal(self):
        provider, _, record, _ = fixture()
        record.update(released=True, executionStatus='COMPLETED', exitCode=0)
        record['programVerification'] = provider._program_proof(record, Verifier()(record))
        setattr(provider, '_root_guard', SimpleNamespace(_operation_lock=lambda: nullcontext()))
        current = {'state': 'COMPLETED', 'exitCode': 0, 'stoppedProof': True,
                   'stopReceipt': {'kind': 'original-group-stopped'}}
        with patch.object(provider, '_transaction', side_effect=lambda: nullcontext(None)), \
             patch.object(provider, '_load', return_value=record), \
             patch.object(provider, '_adapter', side_effect=lambda _record: nullcontext((None, current))):
            self.assertEqual(provider.read_launch_proof('lease', 'alice'), record['programVerification'])
            for changed in ({'state': 'UNKNOWN'}, {'state': 'RUNNING'}, {'stoppedProof': False},
                            {'stopReceipt': None}):
                original = dict(current)
                current.update(changed)
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    provider.read_launch_proof('lease', 'alice')
                current.clear()
                current.update(original)

    def test_constructor_rejects_spec_mismatch_before_base_effects(self):
        class WrongSpec(Verifier):
            def validate_spec(self, spec):
                raise ValueError('SPEC_MISMATCH')
        with patch('agent_factory.research_local_provider.ProcessResourceProvider.__init__') as base:
            with self.assertRaisesRegex(ValueError, 'SPEC_MISMATCH'):
                ResearchLocalProvider(None, None, ResearchProcessSpec.__new__(ResearchProcessSpec),
                    ResearchProcessLimits.__new__(ResearchProcessLimits), gpu_binding=GpuBinding('a'*64, 'b'*64),
                    source_fingerprint='e'*64, manifest_fingerprint='f'*64, observer=Observer(), program_verifier=WrongSpec())
            base.assert_not_called()


class ExplicitSpecAdmissionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'POSIX contract capture required')
    def test_valid_uv_spec_is_verified_before_base_provider_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); venv = root / 'venv'; venv.mkdir(); (venv / 'bin').mkdir()
            approved = root / 'approved'; approved.mkdir()
            binary = approved / 'python'; binary.write_bytes(b'inert never-executed interpreter'); binary.chmod(0o700)
            link = venv / 'bin' / 'python'; link.symlink_to(binary)
            cfg = venv / 'pyvenv.cfg'; cfg.write_text('uv = 0.11.7\n')
            project = root / 'pyproject.toml'; project.write_text('[project]\nname="fixture"\n')
            lock = root / 'uv.lock'; lock.write_text('version = 1\n')
            inventory = root / 'inventory.json'; inventory.write_text('{"fixture":true}')
            sha = hashlib.sha256(binary.read_bytes()).hexdigest()
            raw = capture_interpreter_contract(executable=str(link), sha256=sha, project_root=root,
                venv_root=venv, approved_interpreter_roots=[approved], pyvenv_cfg=cfg,
                pyproject_toml=project, uv_lock=lock, package_inventory=inventory, package_files=[])
            info = root.stat()
            spec = UvResearchProcessSpec(str(link), sha, ('-B', str(root / 'owned-entry.py')),
                working_directory=str(root), working_directory_identity=(info.st_dev, info.st_ino),
                environment=tuple((key, '1') for key in
                    ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE')) +
                    (('PYTHONPYCACHEPREFIX', str(root)),),
                interpreter_contract=raw)
            events = []; verifier = Verifier()
            with patch.object(verifier, 'validate_spec', side_effect=lambda actual: events.append(('verified', actual))), \
                    patch('agent_factory.research_local_provider.ProcessResourceProvider.__init__',
                          side_effect=lambda *args, **kwargs: events.append(('base', args[2]))):
                ResearchLocalProvider(None, None, spec, ResearchProcessLimits(), gpu_binding=GpuBinding('a'*64, 'b'*64),
                    source_fingerprint=verifier.configuration_fingerprint, manifest_fingerprint='f'*64,
                    observer=Observer(), program_verifier=verifier)
            self.assertEqual(events, [('verified', spec), ('base', spec)])
            with patch.object(verifier, 'validate_spec', side_effect=ValueError('DENIED')), \
                    patch('agent_factory.research_local_provider.ProcessResourceProvider.__init__') as base:
                with self.assertRaises(ValueError):
                    ResearchLocalProvider(None, None, spec, ResearchProcessLimits(), gpu_binding=GpuBinding('a'*64, 'b'*64),
                        source_fingerprint=verifier.configuration_fingerprint, manifest_fingerprint='f'*64,
                        observer=Observer(), program_verifier=verifier)
                base.assert_not_called()

    def test_arbitrary_subclasses_of_both_approved_specs_still_denied_before_verifier(self):
        class OtherResearchSpec(ResearchProcessSpec):
            pass
        class OtherUvSpec(UvResearchProcessSpec):
            pass
        for cls in (OtherResearchSpec, OtherUvSpec):
            with self.subTest(kind=cls.__name__):
                verifier = Verifier()
                with patch.object(verifier, 'validate_spec') as verify, \
                        patch('agent_factory.research_local_provider.ProcessResourceProvider.__init__') as base:
                    with self.assertRaises(ValueError):
                        ResearchLocalProvider(None, None, object.__new__(cls), ResearchProcessLimits(),
                            gpu_binding=GpuBinding('a'*64, 'b'*64), source_fingerprint='e'*64,
                            manifest_fingerprint='f'*64, observer=Observer(), program_verifier=verifier)
                    verify.assert_not_called(); base.assert_not_called()
