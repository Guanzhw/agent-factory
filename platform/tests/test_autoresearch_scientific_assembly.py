"""Synthetic original-pin verifier tests; no filesystem staging, process or GPU."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import autoresearch_scientific_assembly as module
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.resources import PersistentResourceService
from test_research_manifest import example_manifest
from test_research_training_adapter import synthetic_files
from agent_factory import research_training_adapter as adapter


class ScientificAssemblyTests(unittest.TestCase):
    def fixture(self):
        # Exact provider/driver instances with synthetic inert pins, no ctor effects.
        value = object.__new__(module.ScientificPhaseAssembler)
        value.owner, value.files, value.microbatch = 'alice', {'train.py': b'baseline'}, 1
        value.manifest = example_manifest()
        value.limits, value.gpu = object(), object()
        spec = object(); value.stages = {'training': SimpleNamespace(spec=spec)}
        token = {'artifactId': 'original-token-bytes'}
        value._token = Mock(return_value=token)
        value._candidate = Mock(return_value=({'train.py': b'candidate'}, 'b'*64))
        driver = object.__new__(module._LocalDriver)
        driver._manifest, driver._variant, driver._entrypoint = value.manifest, 'b'*64, 'train_candidate.py'
        driver._generated, driver._fingerprint = {'train_candidate.py': b'fixed'}, 'c'*64
        driver._operator_json = module.json.dumps({'tokenBytes': token}).encode()
        driver.validate_spec = Mock()
        provider = object.__new__(module.ResearchLocalProvider)
        provider.spec, provider.limits, provider._program_verifier, provider._source = spec, value.limits, driver, 'c'*64
        target = SimpleNamespace(owners=frozenset({'alice'}), synthetic_fixture=False, provider=provider, gpu_binding=value.gpu)
        pin = {'targetRef': 'original-target', 'comparisonManifest': value.manifest,
               'comparisonManifestSha256': manifest_fingerprint(value.manifest), 'variantSha256': 'b'*64}
        return value, driver, target, pin

    def test_actual_driver_class_byte_variant_spec_and_prepared_pin_are_checked(self):
        with patch.object(module, 'build_training_bundle', return_value={'generatedFiles': {'train_candidate.py': b'fixed'}}):
            value, driver, target, pin = self.fixture()
            value.verify_phase('training', {'trainPy': 'candidate'}, {}, pin, target)
            driver.validate_spec.assert_called_once_with(target.provider.spec)
            for change in ('generated', 'variant', 'token', 'provider-spec', 'provider-class'):
                value, driver, target, pin = self.fixture()
                if change == 'generated': driver._generated = {'train_candidate.py': b'wrong candidate'}
                if change == 'variant': driver._variant = 'f'*64
                if change == 'token': value._token.return_value = {'artifactId': 'different-token'}
                if change == 'provider-spec': target.provider.spec = object()
                if change == 'provider-class': target.provider = SimpleNamespace(**target.provider.__dict__)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    value.verify_phase('training', {'trainPy': 'candidate'}, {}, pin, target)

    def test_actual_candidate_derivation_rejects_architecture_or_manifest_substitution(self):
        files = synthetic_files()
        text = files['train.py'].decode().replace('EMBEDDING_LR = 0.5', 'EMBEDDING_LR = 0.25')
        with patch.object(adapter, 'verify_upstream_source', return_value={'commit': 'synthetic-only', 'sourceSha256': {}}):
            derived = module.derive_local_identities(files, {**files, 'train.py': text.encode()}, microbatch=1)['identities']
            value = object.__new__(module.ScientificPhaseAssembler)
            value.files, value.microbatch, value.manifest = files, 1, example_manifest()
            value.manifest['baselineSourceManifestSha256'] = derived['baseline']['sha256']
            for field, key in (('code', 'evaluatorCode'), ('configuration', 'evaluatorConfiguration')):
                value.manifest['evaluator'][field] = {k: derived[key][k] for k in ('sha256', 'sizeBytes')}
            _, variant = value._candidate({'trainPy': text})
            self.assertEqual(variant, derived['candidate']['sha256'])
            with self.assertRaises(ValueError): value._candidate({'trainPy': text.replace('DEPTH = 8', 'DEPTH = 9')})
            value.manifest['evaluator']['code']['sha256'] = 'f'*64
            with self.assertRaises(ValueError): value._candidate({'trainPy': text})

    def test_registration_requires_exact_committed_original_phase_before_any_write(self):
        value = object.__new__(module.ScientificPhaseAssembler)
        candidate, pin = {'trainPy': 'candidate'}, {'targetRef': 'new-original-target'}
        target = module.RemoteTarget('Synthetic fixed target', 'compute', frozenset({'alice'}))
        row = {'owner_id': 'alice', 'parent_task_id': 'parent', 'body': {'candidate': candidate,
            'phases': {'training': {'config': pin}}}}
        value.owner, value.pending = 'alice', {pin['targetRef']: target}
        value.verify_phase = Mock()
        store = SimpleNamespace(sql=Mock(return_value=[deepcopy(row)]))
        resources = PersistentResourceService(store, Mock(), {})
        store.process_runtime = SimpleNamespace(resources=resources)
        store.research_runtime = SimpleNamespace(resources=resources)
        value.store = store; value.state = {'store': store, 'auth': Mock(), 'settings': SimpleNamespace(remote_targets={})}
        ctx = SimpleNamespace(run_context=SimpleNamespace(run_id='original-run', user_id='alice', session_id='parent'))
        for change in ('missing', 'owner', 'candidate', 'pin'):
            bad = deepcopy(row)
            if change == 'owner': bad['owner_id'] = 'bob'
            if change == 'candidate': bad['body']['candidate'] = {'trainPy': 'wrong'}
            if change == 'pin': bad['body']['phases']['training']['config'] = {'targetRef': 'wrong'}
            store.sql.return_value = [] if change == 'missing' else [bad]
            with self.subTest(change=change), self.assertRaises(ValueError):
                value.register_phase(ctx, 'training', candidate, {}, pin)
            self.assertEqual(resources.targets, {}); self.assertEqual(value.state['settings'].remote_targets, {})
        store.sql.return_value = [row]
        self.assertIs(value.register_phase(ctx, 'training', candidate, {}, pin), target)
        self.assertIs(resources.targets[pin['targetRef']], target)
        self.assertIs(value.state['settings'].remote_targets[pin['targetRef']], target)
        resources.targets[pin['targetRef']] = module.RemoteTarget('Other', 'compute', frozenset({'alice'}))
        with self.assertRaises(ValueError): value.register_phase(ctx, 'training', candidate, {}, pin)
