"""Synthetic original-pin verifier tests; no filesystem staging, process or GPU."""
from copy import deepcopy
from pathlib import Path
from dataclasses import asdict
import os
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import autoresearch_scientific_assembly as module
from agent_factory.research_manifest import manifest_fingerprint
from test_research_manifest import example_manifest
from test_research_training_adapter import synthetic_files
from agent_factory import research_training_adapter as adapter
from agent_factory import research_local_driver as local_driver
from agent_factory.research_staging import FilePin


class ScientificAssemblyTests(unittest.TestCase):
    def fixture(self):
        # Exact provider/driver instances with synthetic inert pins, no ctor effects.
        value = object.__new__(module.ScientificPhaseAssembler)
        value.owner, value.files, value.microbatch = 'alice', {'train.py': b'baseline'}, 1
        value.manifest = example_manifest()
        value.limits, value.gpu = object(), object()
        spec = object(); value.phase_stages = {'original-target': SimpleNamespace(spec=spec)}
        token = {'artifactId': 'original-token-bytes'}
        value._token = Mock(return_value=token)
        value.inputs = {'operatorInputs': {'tokenBytes': deepcopy(token)}}
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

    def test_authority_metadata_path_never_reads_retained_artifacts_but_full_path_does(self):
        with patch.object(module, 'build_training_bundle', return_value={'generatedFiles': {'train_candidate.py': b'fixed'}}):
            value, _, target, pin = self.fixture()
            value._token.side_effect = PermissionError('retained source revoked')
            value.preparation_receipt = Mock(side_effect=AssertionError('no retention in authority'))
            value._training = Mock(side_effect=AssertionError('no checkpoint in authority'))
            value.verify_authority('training', {'trainPy': 'candidate'}, {}, pin, target)
            value._token.assert_not_called(); value.preparation_receipt.assert_not_called(); value._training.assert_not_called()
            with self.assertRaises(PermissionError): value.verify_phase('training', {'trainPy': 'candidate'}, {}, pin, target)
            value._token.assert_called_once_with({})

    def test_evaluation_authority_checks_original_receipt_and_checkpoint_pin_without_reading(self):
        with patch.object(module, 'build_training_bundle', return_value={'generatedFiles': {'train_candidate.py': b'fixed'}}):
            value, driver, target, pin = self.fixture()
            driver._entrypoint = 'evaluate.py'
            receipt = {'execution': {'ownerId': 'alice', 'taskId': 'original-training'}, 'artifact': {'id': 'checkpoint'}}
            prior = {'training': {'state': 'COMPLETED', 'config': {'variantSha256': 'b'*64}, 'receipt': receipt}}
            training = {**receipt['execution'], 'variantSha256': 'b'*64,
                'checkpoint': {'artifactId': 'checkpoint', 'sha256': 'd'*64, 'sizeBytes': 1}}
            driver._evaluation = module._Evaluation({}, Mock(), training, value.manifest,
                value.manifest['artifactLimits']['checkpointBytes'])
            driver._evaluation_policy = driver._evaluation.configuration_fingerprint
            value._training = Mock(side_effect=AssertionError('no retention in authority'))
            value.verify_authority('evaluation', {'trainPy': 'candidate'}, prior, pin, target)
            value._training.assert_not_called(); value._token.assert_not_called()
            driver._evaluation.training['checkpoint']['sha256'] = 'e'*64
            with self.assertRaises(ValueError): value.verify_authority('evaluation', {'trainPy': 'candidate'}, prior, pin, target)

    def test_actual_candidate_derivation_rejects_architecture_or_manifest_substitution(self):
        files = synthetic_files()
        text = files['train.py'].decode().replace('EMBEDDING_LR = 0.5', 'EMBEDDING_LR = 0.25')
        # This pure derivation fixture supplies fixed synthetic runtime bytes;
        # descriptor-safe installed package scanning is a separate POSIX contract.
        with patch.object(adapter, 'verify_upstream_source', return_value={'commit': 'synthetic-only', 'sourceSha256': {}}), \
             patch.object(local_driver, '_runtime_pins', return_value=(FilePin('synthetic_runtime.py', 'a' * 64, 1),)):
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



class PreparationReceiptTests(unittest.TestCase):
    def fixture(self):
        value = object.__new__(module.ScientificPhaseAssembler)
        value.owner, value.prep_ref = 'alice', 'original-prep-target'
        value.preparation_reference = {'taskId': 'original-producer', 'artifactId': 'original-artifact'}
        binding = {'ownerId': 'alice', 'taskId': 'original-producer', 'nativeRunId': 'original-run',
            'planId': 'original-plan', 'planFingerprint': 'a'*64, 'leaseId': 'original-lease',
            'providerJobId': 'original-job', 'variantSha256': 'b'*64, 'manifestSha256': 'c'*64}
        token = {'root': '/synthetic/retained', 'basename': 'token-bytes.safetensors',
            'rootIdentity': {'device': 1, 'inode': 2}, 'binding': binding, 'sha256': 'd'*64, 'sizeBytes': 128}
        value.inputs = {'operatorInputs': {'tokenBytes': deepcopy(token)}}
        value.manifest = {'tokenizer': {'tokenBytes': {'sha256': 'd'*64, 'sizeBytes': 128}}}
        value.preparation = SimpleNamespace(input_pin=Mock(return_value=deepcopy(token)))
        value.prep_target = SimpleNamespace(provider=Mock())
        lease = {'connectionRef': value.prep_ref, 'ownerId': 'alice', 'localTaskId': binding['taskId'],
            'nativeRunId': binding['nativeRunId'], 'planId': binding['planId'], 'providerJobId': binding['providerJobId'],
            'state': 'RECLAIMED', 'capacityHeld': False, 'executionStatus': 'COMPLETED', 'exitCode': 0,
            'stopEvidence': {'allStopped': True}}
        task = {'id': binding['taskId'], 'cancel_requested': False}
        runtime = SimpleNamespace(_original=Mock(return_value={'lease_id': binding['leaseId'],
            'native_run_id': binding['nativeRunId'], 'owner_id': 'alice'}),
            _custody=Mock(return_value=(lease, value.prep_target, task, {'id': binding['nativeRunId']})), run=Mock())
        artifact = {'id': 'original-artifact', 'jobId': binding['taskId'], 'provenance': deepcopy(binding)}
        value.store = SimpleNamespace(process_runtime=runtime, plan=Mock(return_value={'fingerprint': 'a'*64}),
            artifact=Mock(return_value=(artifact, b'original reference bytes')))
        return value, lease, token, artifact

    def test_retained_whole_file_and_original_execution_are_reused_without_export(self):
        value, _, token, artifact = self.fixture()
        receipt = value.preparation_receipt()
        self.assertEqual(value.preparation.input_pin.call_count, 1)
        self.assertEqual(receipt['artifact'], artifact)
        self.assertEqual(receipt['execution']['taskId'], 'original-producer')
        self.assertEqual(set(receipt['execution']), {'ownerId', 'taskId', 'nativeRunId', 'planId',
            'planFingerprint', 'leaseId', 'providerJobId'})
        prior = {'preparation': {'state': 'COMPLETED', 'receipt': {**receipt,
            'verification': {'taskId': 'verification-child', 'nativeRunId': 'verification-run', 'planId': 'child-plan'}}}}
        self.assertEqual(value._token(prior), token)
        self.assertEqual(value.preparation.input_pin.call_count, 2)
        value.store.process_runtime.run.assert_not_called()
        value.prep_target.provider.assert_not_called()
        value.preparation.input_pin.assert_called_with('alice', 'original-producer', 'original-artifact')

    def test_hash_binding_target_terminal_proof_or_receipt_substitution_denied(self):
        for change in ('hash', 'size', 'binding', 'target', 'held', 'failed', 'stop', 'cancel', 'artifact', 'midread'):
            value, lease, token, artifact = self.fixture()
            if change == 'hash': value.inputs['operatorInputs']['tokenBytes']['sha256'] = 'e'*64
            if change == 'size': value.manifest['tokenizer']['tokenBytes']['sizeBytes'] = 129
            if change == 'binding': value.store.process_runtime._original.return_value['native_run_id'] = 'other'
            if change == 'target': lease['connectionRef'] = 'other'
            if change == 'held': lease['capacityHeld'] = True
            if change == 'failed': lease['executionStatus'] = 'FAILED'
            if change == 'stop': lease['stopEvidence']['allStopped'] = False
            if change == 'cancel': value.store.process_runtime._custody.return_value[2]['cancel_requested'] = True
            if change == 'artifact': artifact['provenance']['leaseId'] = 'other'
            if change == 'midread': value.store.artifact.side_effect = lambda *args: (
                setattr(value.preparation.input_pin, 'return_value', {**token, 'sha256': 'e'*64}) or artifact, b'reference')
            with self.subTest(change=change), self.assertRaises(ValueError): value.preparation_receipt()
        value, _, _, _ = self.fixture()
        receipt = value.preparation_receipt(); receipt['execution']['taskId'] = 'new-export'
        with self.assertRaises(ValueError): value._token({'preparation': {'state': 'COMPLETED', 'receipt': receipt}})

    def test_final_fresh_reader_rejects_revocation_after_metadata_and_never_caches(self):
        value, _, _, artifact = self.fixture()
        value.preparation_receipt()
        def metadata(*args):
            value.preparation.input_pin.side_effect = PermissionError('original authority revoked')
            return artifact, b'reference'
        value.store.artifact.side_effect = metadata
        with self.assertRaises(PermissionError): value.preparation_receipt()
        self.assertEqual(value.preparation.input_pin.call_count, 2)
        value.store.process_runtime.run.assert_not_called()

    def test_preparation_phase_rechecks_receipt_without_driver_or_provider_call(self):
        value, _, _, _ = self.fixture()
        provider = object.__new__(module.PreparationProvider)
        value.prep_target = SimpleNamespace(provider=provider, owners=frozenset({'alice'}), synthetic_fixture=False)
        value._candidate = Mock(return_value=({}, 'b'*64))
        value.manifest = example_manifest()
        value.preparation_receipt = Mock(return_value={'execution': {}, 'artifact': {}})
        pin = {'targetRef': value.prep_ref, 'variantSha256': 'b'*64, 'comparisonManifest': value.manifest,
            'comparisonManifestSha256': manifest_fingerprint(value.manifest)}
        value.verify_phase('preparation', {'trainPy': 'synthetic'}, {}, pin, value.prep_target)
        value.preparation_receipt.assert_called_once_with()
        value.preparation_receipt.side_effect = PermissionError('original producer revoked')
        with self.assertRaises(PermissionError):
            value.verify_phase('preparation', {'trainPy': 'synthetic'}, {}, pin, value.prep_target)


class EvaluationServiceTests(unittest.TestCase):
    def test_service_only_after_registered_exact_target_and_revalidates_before_cache(self):
        value = object.__new__(module.ScientificPhaseAssembler)
        value.manifest = example_manifest()
        pin = {'targetRef': 'original-evaluation', 'comparisonManifest': value.manifest,
            'comparisonManifestSha256': manifest_fingerprint(value.manifest), 'variantSha256': 'b'*64}
        target = SimpleNamespace(provider=SimpleNamespace(read_completed_output=Mock(), read_launch_proof=Mock()))
        resources = SimpleNamespace(targets={pin['targetRef']: target}, _target_fingerprint=Mock(return_value='a'*64))
        value.store = SimpleNamespace(research_runtime=SimpleNamespace(resources=resources),
            process_runtime=SimpleNamespace(resources=resources))
        value.state = {'auth': Mock(), 'settings': SimpleNamespace(remote_targets={pin['targetRef']: target})}
        value.checkpoints = SimpleNamespace(identity=Mock())
        value.evaluation_registrations, value.evaluation_services = {}, {}
        value.verify_phase = Mock()
        with self.assertRaises(ValueError): value.evaluation_service(pin)
        value.evaluation_registrations[pin['targetRef']] = {'pin': deepcopy(pin), 'candidate': {'trainPy': 'synthetic'},
            'prior': {'original': 'custody'}, 'target': target, 'fingerprint': 'a'*64}
        service = value.evaluation_service(pin)
        self.assertIs(type(service), module.ResearchEvaluationService)
        self.assertIs(value.evaluation_service(pin), service)
        self.assertEqual(value.verify_phase.call_count, 2)
        self.assertEqual(service._targets, {module.digest(value.manifest['evaluator']): (pin['targetRef'], 'a'*64)})
        self.assertIs(service._reader, value.checkpoints.identity)
        bad = deepcopy(pin); bad['variantSha256'] = 'c'*64
        with self.assertRaises(ValueError): value.evaluation_service(bad)
        resources._target_fingerprint.return_value = 'd'*64
        with self.assertRaises(ValueError): value.evaluation_service(pin)
        resources._target_fingerprint.return_value = 'a'*64
        resources.targets[pin['targetRef']] = object()
        with self.assertRaises(ValueError): value.evaluation_service(pin)
        resources.targets[pin['targetRef']] = target
        value.verify_phase.side_effect = PermissionError('checkpoint revoked')
        with self.assertRaises(PermissionError): value.evaluation_service(pin)
        self.assertIs(value.evaluation_services[pin['targetRef']], service)


@unittest.skipUnless(os.name == 'posix', 'Descriptor-pinned operator namespaces require POSIX')
class PhaseNamespaceTests(unittest.TestCase):
    def fixture(self, root):
        value = object.__new__(module.ScientificPhaseAssembler)
        value.owner, value.microbatch, value.bounds = 'alice', 1, None
        value.files, value.manifest = {'train.py': b'baseline'}, example_manifest()
        value.inputs = {'comparisonManifest': value.manifest, 'manifestSha256': manifest_fingerprint(value.manifest),
            'operatorInputs': {'tokenBytes': {'id': 'retained-original'}}}
        value.environment = ()
        value.limits = module.ResearchProcessLimits()
        value.gpu = SimpleNamespace(to_dict=lambda: {'syntheticDevice': 'fixed'})
        value.observer = SimpleNamespace(configuration_fingerprint='a'*64)
        value.pending, value.phase_stages, value.phase_intents = {}, {}, {}
        value.evaluation_registrations, value.evaluation_services = {}, {}
        value.stages, value.base_custody = {}, {}
        for phase in ('training', 'evaluation'):
            paths = [root / (phase+'-'+kind) for kind in ('program', 'cache', 'custody')]
            for path in paths: path.mkdir(mode=0o700)
            program, cache, custody = paths
            pp, cp, up = [value._directory_identity(path) for path in paths]
            env = tuple((key, '1') for key in ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE'))
            env += (('PYTHONPYCACHEPREFIX', str(program)),)
            spec = module.UvResearchProcessSpec('/synthetic/python', 'a'*64,
                ('-B', str(program/'train_candidate.py'), '--config', str(program/'run-config.json')),
                str(program), env, (pp.device, pp.inode), '{}')
            value.stages[phase] = module.ScientificStage(spec, pp, cache, cp, custody)
            value.base_custody[phase] = up
        value._candidate = Mock(return_value=({'train.py': b'candidate'}, 'b'*64))
        value._token = Mock(return_value={'id': 'retained-original'})
        value._training = Mock()
        value.verify_phase = Mock()
        value.checkpoints = SimpleNamespace(identity=Mock())
        resources = SimpleNamespace(targets={}, _target_fingerprint=lambda target: target.fingerprint)
        store = SimpleNamespace(sql=Mock(return_value=[]), process_runtime=SimpleNamespace(resources=resources),
            research_runtime=SimpleNamespace(resources=resources))
        value.store = store
        value.state = {'store': store, 'auth': Mock(), 'settings': SimpleNamespace(remote_targets={})}
        def build(phase, candidate, prior, pin, stage, inputs, training, *, stop_only=False):
            value.phase_stages[pin['targetRef']] = stage
            target_fp = module.digest({'spec': asdict(stage.spec), 'custody': str(stage.custody_root)})
            return SimpleNamespace(provider=SimpleNamespace(configuration_fingerprint=target_fp),
                capacity_pool=SimpleNamespace(fingerprint='c'*64), fingerprint=target_fp, stopped_only=stop_only)
        value._build = Mock(side_effect=build)
        return value

    @staticmethod
    def context(run='original-run'):
        return SimpleNamespace(run_context=SimpleNamespace(user_id='alice', session_id='parent-'+run, run_id=run))

    def commit(self, value, ctx, candidate, pin):
        entry = {'config': deepcopy(pin)}
        value.store.sql.return_value = [{'owner_id': 'alice', 'parent_task_id': ctx.run_context.session_id,
            'body': {'candidate': deepcopy(candidate), 'phases': {'training': entry}}}]
        def persist(snapshot):
            self.assertEqual(value.store.process_runtime.resources.targets, {})
            self.assertEqual(value.state['settings'].remote_targets, {})
            entry['runtimeSnapshot'] = {'sha256': module.digest(snapshot), 'body': deepcopy(snapshot)}
            return deepcopy(snapshot)
        return entry, persist

    def test_distinct_parent_namespaces_commit_before_effect_and_snapshot_before_registration(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('agent_factory.process_enforcement.interpreter_module', return_value=SimpleNamespace(validate_interpreter_contract=Mock())), \
             patch.object(module, 'PersistentResourceService'):
            value = self.fixture(Path(directory)); candidate = {'trainPy': 'candidate'}
            ctx, other = self.context(), self.context('another-run')
            pin = value('training', candidate, {}, context=ctx)
            otherpin = value('training', candidate, {}, context=other)
            self.assertNotEqual(pin['targetRef'], otherpin['targetRef'])
            self.assertTrue(all(not list(Path(stage.spec.working_directory).iterdir()) for stage in value.stages.values()))
            with self.assertRaises(ValueError): value.register_phase(ctx, 'training', candidate, {}, pin, persist_snapshot=Mock())
            value._build.assert_not_called()
            entry, persist = self.commit(value, ctx, candidate, pin)
            target = value.register_phase(ctx, 'training', candidate, {}, pin, persist_snapshot=persist)
            snapshot = entry['runtimeSnapshot']['body']
            self.assertEqual(snapshot['targetFingerprint'], target.fingerprint)
            self.assertEqual(len(snapshot['rootIdentities']), 3)
            second_stage, second_identities = value._namespace('training', value._intent(other, 'training', candidate))
            self.assertNotEqual(second_stage.spec.working_directory, snapshot['launch']['launchSpec']['working_directory'])
            self.assertNotEqual(second_identities[0], snapshot['rootIdentities'][0])
            self.assertFalse(target.stopped_only)
            self.assertEqual(target.capacity_pool.fingerprint, 'c'*64)
            value.store.process_runtime.resources.targets.clear(); value.state['settings'].remote_targets.clear()
            value._token.side_effect = PermissionError('original authority revoked')
            value.verify_phase.side_effect = PermissionError('no new effects')
            restored = value.restore_phase(ctx, 'training', candidate, {}, pin, snapshot)
            self.assertTrue(restored.stopped_only)
            self.assertEqual(restored.fingerprint, target.fingerprint)
            self.assertEqual(value._build.call_args.kwargs, {'stop_only': True})
            # Recovery opens only the exact original namespace; no allocation API.
            self.assertEqual(value._token.call_count, 1)
            value.store.process_runtime.resources.targets.clear(); value.state['settings'].remote_targets.clear()
            for change in ('digest', 'root', 'provider', 'observer'):
                bad = deepcopy(snapshot)
                if change == 'digest': bad['intent']['parentRunId'] = 'other'
                if change == 'root': bad['rootIdentities'][0]['inode'] += 1
                if change == 'provider': bad['providerFingerprint'] = 'd'*64
                if change == 'observer': bad['observerFingerprint'] = 'e'*64
                entry['runtimeSnapshot'] = {'sha256': module.digest(bad), 'body': bad}
                with self.subTest(change=change), self.assertRaises(ValueError):
                    value.restore_phase(ctx, 'training', candidate, {}, pin, bad)

    def test_uncommitted_snapshot_failure_retains_namespace_and_never_registers_or_reuses(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('agent_factory.process_enforcement.interpreter_module', return_value=SimpleNamespace(validate_interpreter_contract=Mock())), \
             patch.object(module, 'PersistentResourceService'):
            value = self.fixture(Path(directory)); ctx = self.context(); candidate = {'trainPy': 'candidate'}
            pin = value('training', candidate, {}, context=ctx)
            self.commit(value, ctx, candidate, pin)
            with self.assertRaises(OSError):
                value.register_phase(ctx, 'training', candidate, {}, pin, persist_snapshot=Mock(side_effect=OSError('lost ack')))
            self.assertEqual(value.store.process_runtime.resources.targets, {})
            self.assertTrue(list(Path(value.stages['training'].spec.working_directory).iterdir()))
            with self.assertRaises(FileExistsError):
                value.register_phase(ctx, 'training', candidate, {}, pin, persist_snapshot=Mock())
            self.assertEqual(value._build.call_count, 1)

    def test_parent_replacement_after_mkdir_never_repins_impostor_child(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('agent_factory.process_enforcement.interpreter_module', return_value=SimpleNamespace(validate_interpreter_contract=Mock())):
            value = self.fixture(Path(directory)); candidate = {'trainPy': 'candidate'}; ctx = self.context()
            intent = value._intent(ctx, 'training', candidate)
            parent = Path(value.stages['training'].spec.working_directory)
            original_mkdir = os.mkdir
            swapped = False
            def swapping_mkdir(name, *args, **kwargs):
                nonlocal swapped
                result = original_mkdir(name, *args, **kwargs)
                if kwargs.get('dir_fd') is not None and not swapped:
                    swapped = True
                    parent.rename(parent.with_name('retained-original-parent'))
                    original_mkdir(parent, 0o700)
                    original_mkdir(parent / name, 0o700)
                return result
            with patch.object(module.os, 'mkdir', side_effect=swapping_mkdir), self.assertRaises(ValueError):
                value._namespace('training', intent)
            self.assertTrue(swapped)
            value._build.assert_not_called()


class RestoredProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_restored_provider_denies_before_any_journal_or_callback(self):
        # Real method, no initialized store/root: any journal/base access would
        # fail this test rather than becoming an unnoticed synthetic allocation.
        provider = object.__new__(module.ResearchLocalProvider)
        provider._stop_only = True
        callback = Mock(side_effect=AssertionError('must not call authority/effect'))
        with self.assertRaisesRegex(ValueError, 'RESEARCH_RESTORED_DISPATCH_FORBIDDEN'):
            await provider.allocate_bound({}, before_effect=callback)
        callback.assert_not_called()
