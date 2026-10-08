# pyright: reportMissingImports=false
"""Concrete descriptor/settings/publication assembly without private inputs or DB."""
from copy import deepcopy
from dataclasses import asdict
import importlib
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_autoresearch_operator as cli_fixture
from test_research_manifest import example_manifest
from agent_factory.research_local_driver import _RUNTIME_FILES
from agent_factory.research_staging import FilePin

bindings = importlib.import_module('autoresearch_operator_bindings')


def config(role='controller'):
    root = str(Path.cwd())
    pinfiles = [asdict(FilePin(name, 'a'*64, 100)) for name in _RUNTIME_FILES]
    project = {'id': 'science-project', 'name': 'Scientific project', 'ownerId': 'alice',
        'defaultGoal': 'Improve verified result', 'manifest': example_manifest(), 'microbatch': 1,
        'limits': {'totalSeconds': 900, 'experimentSeconds': 600, 'maxExperiments': 1,
            'toolCalls': 32, 'outputBytes': 65536, 'modelRequests': 3, 'modelOutputTokens': 512},
        'upstreamRoot': root, 'applicationRef': None}
    if role == 'controller':
        project.update(receiver={'targetRef': 'receiver', 'originRef': 'origin', 'baseUrl': 'https://receiver.example',
            'ownerId': 'receiver-alice', 'revision': 'reviewed-v1', 'projectPin': 'b'*64},
            modelCredentialRef='EXISTING_MODEL', billingAuthorized=False, runtimeFilePins=pinfiles,
            orx={'sessionRoot': root, 'image': 'sha256:'+'c'*64,
                'orx': {'path': str(Path(root)/'orx'), 'sha256': 'd'*64},
                'opencode': {'path': str(Path(root)/'opencode'), 'sha256': 'e'*64},
                'projectId': '00000000-0000-4000-8000-000000000001'})
    else:
        project.update(baseline={'databaseRef': 'ORIGINAL_DB', 'configFile': root,
            'evaluationReceiptFile': root, 'trainingRunConfigFile': root,
            'scientificRuntime': {'schema': 1, 'kind': 'sealed-scientific-runtime-v1',
                'packageRoot': str(Path(root)/'site-packages'/'agent_factory'),
                'rootIdentity': {'device': 1, 'inode': 2}, 'files': pinfiles}},
            assembly={'projectPin': 'b'*64, 'preparationSnapshotFile': root,
                'preparationReference': {'taskId': 'original-prep', 'artifactId': 'original-artifact'},
                'stageRoots': {phase: {name: str(Path(root)/(phase+'-'+name)) for name in ('program','cache','custody')}
                    for phase in ('training','evaluation')}},
            origin={'baseUrl': 'https://origin.example', 'originRef': 'origin', 'targetRef': 'receiver',
                'originOwnerId': 'alice', 'revision': 'reviewed-v1', 'targetFingerprint': 'f'*64})
    return {**cli_fixture.config(), 'role': role, 'project': project}


class ConcreteOperatorTests(unittest.TestCase):
    def test_default_is_fixed_concrete_bindings_not_unavailable(self):
        value = cli_fixture.operator.default_bindings()
        self.assertIs(value.describe_settings, bindings.describe_settings)
        self.assertIs(value.construct_application, bindings.construct_application)

    def test_both_role_descriptors_and_settings_are_inert(self):
        for role in ('controller', 'receiver'):
            value = config(role)
            with patch.object(bindings, '_upstream', side_effect=AssertionError('no file reads')):
                self.assertEqual(bindings.project_descriptor(value), value['project'])
                settings = bindings.describe_settings(value, 'postgresql://unused')
            self.assertEqual(settings.host, '127.0.0.1')
            self.assertEqual(settings.runtime_tool_contract, 'autoresearch-session-v1')
            self.assertEqual(settings.temporary_policy, 'admin-review')
            self.assertEqual(bool(settings.autoresearch_presets), role == 'controller')

    def test_cross_role_extra_credentials_and_candidate_are_rejected(self):
        for key, value in (('candidate', 'prescribed'), ('modelCredential', 'plaintext'), ('baseline', {})):
            item = config(); item['project'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): bindings.project_descriptor(item)
        item = config(); item['project']['receiver']['baseUrl'] = 'http://public.example'
        with self.assertRaises(ValueError): bindings.project_descriptor(item)

    def test_receiver_cannot_alias_baseline_database_reference_or_stage_roots(self):
        item = config('receiver'); item['project']['baseline']['databaseRef'] = item['databaseRef']
        with self.assertRaises(ValueError): bindings.project_descriptor(item)
        item = config('receiver')
        item['project']['assembly']['stageRoots']['training']['cache'] = item['project']['assembly']['stageRoots']['training']['program']
        with self.assertRaises(ValueError): bindings.project_descriptor(item)

    def test_runtime_commitment_order_cannot_change(self):
        item = config(); item['project']['runtimeFilePins'].reverse()
        with self.assertRaises(ValueError): bindings.project_descriptor(item)

    def test_controller_builds_actual_services_with_lazy_existing_credentials(self):
        value = config(); resolver = Mock(return_value='synthetic-existing-jwt')
        settings = bindings.describe_settings(value, 'postgresql://unused')
        configured = bindings._controller(value, settings, resolver)
        resolver.assert_called_once_with('EXISTING_JWT')
        store = Mock(); store.sql.return_value = []
        remote = configured.remote_scientific_factory(store, Mock(), Mock(), Mock(), None, Mock())
        from agent_factory.remote_scientific_origin import RemoteScientificOrigin
        from agent_factory.autoresearch_remote_children import AutoResearchRemoteChildren
        self.assertIs(type(remote), RemoteScientificOrigin)
        self.assertEqual(remote.project_bindings[value['project']['id']]['projectPin'], 'b'*64)
        children = configured.autoresearch_children_factory(store, Mock(), Mock(), Mock())
        self.assertIs(type(children), AutoResearchRemoteChildren)
        self.assertEqual(children.target_ref, 'receiver')
        resolver.assert_called_once_with('EXISTING_JWT')

    def test_receiver_publication_uses_distinct_existing_governance(self):
        value = config('receiver'); governance, applications, auth = Mock(), Mock(), Mock()
        governance.create_draft.side_effect = lambda owner, definition, request: {**definition, 'version': 1, 'sha256': 'a'*64}
        governance.request_publication.return_value = {'id': 'review'}
        applications.create_draft.side_effect = lambda owner, definition, request: {**definition, 'version': 1, 'sha256': 'b'*64}
        applications.request_publication.return_value = {'id': 'app-review'}
        state = {'auth': auth, 'material_governance': governance, 'applications': applications}
        app = SimpleNamespace(operator_config=value, state=SimpleNamespace(factory=state))
        result = bindings.prepare_publication(app, deepcopy(value['publication']))
        self.assertEqual(result['applicationRef']['sha256'], 'b'*64)
        from agent_factory.autoresearch_profile import material_drafts
        self.assertEqual(governance.create_draft.call_count, 15 + len(material_drafts(value['project']['id'], external_session=True)))
        self.assertTrue(all(call.args[0] == 'reviewer' for call in governance.decide_publication.call_args_list))
        definition = applications.create_draft.call_args.args[1]
        self.assertEqual(set(definition['modes']), {'research', *('remote-scientific-'+p for p in ('preparation','training','evaluation'))})


    def test_receiver_parent_descriptors_match_but_every_factory_denies(self):
        from agent_factory.autoresearch_profile import registrations
        from agent_factory.execution_bindings import ExecutionBindings
        receiver = bindings.describe_settings(config('receiver'), 'postgresql://unused')
        expected = registrations(external_session=True)
        parent_ids = {entry.adapter_id for entry in expected}
        actual = [entry for entry in receiver.runtime_adapters if entry.adapter_id in parent_ids]
        self.assertEqual(len(actual), len(expected))
        def descriptions(entries):
            registry = ExecutionBindings(receiver, Mock())
            for entry in entries:
                values = vars(entry).copy()
                registry.register(**values)
            return registry.describe()
        self.assertEqual(descriptions(actual), descriptions(expected))
        self.assertEqual(receiver.autoresearch_presets, {})
        for entry in actual:
            with self.subTest(adapter=entry.adapter_id), self.assertRaisesRegex(ValueError, 'RECEIVER_PARENT_EXECUTION_DENIED'):
                entry.factory(Mock())

    def test_roles_publish_identical_full_application_and_material_definitions(self):
        from agent_factory.store import digest
        from agent_factory.applications import ApplicationDefinition
        definitions, catalogues = [], []
        source_snapshot = None
        for role in ('controller', 'receiver'):
            value = config(role)
            if source_snapshot is not None:
                value['project']['applicationSnapshot'] = deepcopy(source_snapshot)
            settings = bindings.describe_settings(value, 'postgresql://unused')
            governance, applications = Mock(), Mock()
            catalogue = []
            def material(owner, definition, request):
                catalogue.append(deepcopy(definition))
                return {**definition, 'version': 1, 'sha256': digest(definition)}
            governance.create_draft.side_effect = material
            governance.request_publication.return_value = {'id': 'material-review'}
            def create(owner, definition, request):
                body = {**ApplicationDefinition.model_validate(definition).model_dump(exclude_none=True),
                    'version': 1, 'schema': 1, 'origin': 'manager-authored',
                    'createdAt': '2026-10-07T12:00:00+00:00' if role == 'controller' else '2026-10-07T12:01:00+00:00'}
                return {**body, 'sha256': digest(body)}
            applications.create_draft.side_effect = create
            applications.import_snapshot.side_effect = lambda actor, snapshot, request: deepcopy(snapshot)
            applications.request_publication.return_value = {'id': 'application-review'}
            state = {'auth': Mock(), 'material_governance': governance, 'applications': applications,
                     'settings': settings, 'store': SimpleNamespace(autoresearch=SimpleNamespace(presets=settings.autoresearch_presets))}
            app = SimpleNamespace(operator_config=value, state=SimpleNamespace(factory=state))
            result = bindings.prepare_publication(app, value['publication'])
            source_snapshot = result['applicationSnapshot']
            if role == 'receiver':
                applications.create_draft.assert_not_called()
                applications.import_snapshot.assert_called_once()
                self.assertEqual(source_snapshot['createdAt'], '2026-10-07T12:00:00+00:00')
                applications.request_publication.assert_called_once()
                applications.decide_publication.assert_called_once()
                accepted_catalogue = deepcopy(catalogue)
                value['project']['applicationSnapshot']['description'] = 'Different project scope'
                applications.import_snapshot.reset_mock()
                with self.assertRaisesRegex(ValueError, bindings.ERROR):
                    bindings.prepare_publication(app, value['publication'])
                applications.import_snapshot.assert_not_called()
                catalogue = accepted_catalogue
            definitions.append(result)
            catalogues.append(catalogue)
        self.assertEqual(definitions[0], definitions[1])
        self.assertEqual(catalogues[0], catalogues[1])


    def test_snapshot_descriptor_is_optional_but_not_unstructured(self):
        value = config('receiver')
        value['project']['applicationSnapshot'] = None
        self.assertIsNone(bindings.project_descriptor(value)['applicationSnapshot'])
        for bad in (False, [], {}, {'sha256': 'a' * 64}):
            value['project']['applicationSnapshot'] = bad
            with self.subTest(kind=type(bad).__name__), self.assertRaises(ValueError):
                bindings.project_descriptor(value)


class ReceiverBootstrapTests(unittest.TestCase):
    """Real receiver/assembler constructors, mocked PG/archive/device boundaries.

    Synthetic private interpreter/package bytes are never imported or executed.
    This proves assembly wiring, not baseline custody, GPU or PG acceptance.
    """
    def test_real_receiver_constructor_keeps_original_preparation_and_science(self):
        import hashlib
        import json
        import os
        from contextlib import ExitStack, contextmanager
        from test_research_interpreter import InterpreterTests
        from agent_factory.gpu_custody import GpuBinding
        from agent_factory.process_enforcement import UvResearchProcessSpec, ResearchProcessLimits
        from agent_factory.research_local_driver import ScientificRuntimePin, _runtime_pins
        from agent_factory.research_staging import RootIdentity, pin_bytes
        from agent_factory.research_preparation_provider import PreparationProvider
        from agent_factory.research_manifest import manifest_fingerprint
        from agent_factory.remote_scientific_receiver import RemoteScientificReceiver
        from autoresearch_scientific_assembly import ScientificPhaseAssembler
        if os.name != 'posix':
            self.skipTest('Private POSIX roots and original interpreter pin')
        fixture = InterpreterTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        root = fixture.root
        retained = root / 'retained'; retained.mkdir(mode=0o700)
        workspace = root / 'receiver'; workspace.mkdir(mode=0o700)
        package = fixture.venv / 'lib' / 'python3.12' / 'site-packages' / 'agent_factory'
        package.mkdir(parents=True, mode=0o700)
        pins = []
        for name in _RUNTIME_FILES:
            raw = b'# Original synthetic science; NEVER IMPORTED\n' + name.encode()
            item = package / name; item.write_bytes(raw); item.chmod(0o600)
            pins.append(pin_bytes(name, raw))
        info = package.stat()
        scientific = ScientificRuntimePin(str(package), RootIdentity(info.st_dev, info.st_ino), tuple(pins))
        self.assertEqual(_runtime_pins(scientific), tuple(pins))
        def write(name, value):
            item = retained / name; item.write_text(json.dumps(value)); item.chmod(0o600)
            return str(item)
        original = {'workspace': str(retained), 'venvRoot': str(fixture.venv), 'microbatch': 1,
            'limits': asdict(ResearchProcessLimits()), 'receiverNamespaceSha256': 'a'*64,
            'deviceUuid': 'synthetic-device', 'nvidiaSmi': {'executable': str(root/'not-executed'), 'sha256': 'b'*64}}
        gpu = GpuBinding(original['receiverNamespaceSha256'], hashlib.sha256(original['deviceUuid'].encode()).hexdigest())
        value = config('receiver'); value['workspace'] = str(workspace)
        project = value['project']; project['manifest']['device']['identitySha256'] = gpu.identity_key
        project['manifest']['protocol']['totalWallSeconds'] = 900
        project['baseline'].update(configFile=write('original.json', original),
            evaluationReceiptFile=write('evaluation.json', {'retained': True}),
            trainingRunConfigFile=write('run.json', {'retained': True}), scientificRuntime=scientific.to_dict())
        prep_snapshot = {'preparationManifestSha256': 'c'*64}
        project['assembly']['preparationSnapshotFile'] = write('preparation.json', prep_snapshot)
        for phase in ('training', 'evaluation'):
            for kind in ('program', 'cache', 'custody'):
                item = workspace / (phase+'-'+kind); item.mkdir(mode=0o700)
                project['assembly']['stageRoots'][phase][kind] = str(item)
        source_program = retained / 'program'; source_program.mkdir(mode=0o700)
        info = source_program.stat()
        environment = tuple(sorted({key: '1' for key in
            ('HF_HUB_OFFLINE','HF_DATASETS_OFFLINE','TRANSFORMERS_OFFLINE','PYTHONNOUSERSITE')}.items()))
        environment += (('PYTHONPYCACHEPREFIX', str(source_program)),)
        spec = UvResearchProcessSpec(str(fixture.link), fixture.sha,
            ('-B', str(source_program/'train_baseline.py')), working_directory=str(source_program),
            working_directory_identity=(info.st_dev, info.st_ino), environment=environment,
            interpreter_contract=fixture.capture())
        captured = {'originalConfig': original, 'contract': {'comparisonManifest': project['manifest']},
            'snapshots': {phase: {'launchSpec': asdict(spec), 'environmentPins': [], 'boundsProfile': None,
                'capturedInputs': {'comparisonManifest': project['manifest'],
                    'manifestSha256': manifest_fingerprint(project['manifest']), 'operatorInputs': {}}}
                for phase in ('training','evaluation')}}
        target = SimpleNamespace(provider=object.__new__(PreparationProvider), owners=frozenset({'alice'}))
        resources = SimpleNamespace(targets={'preparation': target}, _target_fingerprint=lambda _: 'd'*64)
        baseline_store = SimpleNamespace(storage=object(), process_runtime=SimpleNamespace(resources=resources))
        baseline_state = {'store': baseline_store, 'auth': Mock(), 'resources': resources}
        opened_settings = []
        @contextmanager
        def opened(settings, *, full_verification=False):
            opened_settings.append((settings, full_verification))
            yield baseline_state
        baseline_url = 'postgresql://synthetic@localhost/retained'
        active_url = 'postgresql://synthetic@localhost/receiver'
        resolver = Mock(side_effect=lambda ref: baseline_url if ref == 'ORIGINAL_DB' else 'synthetic-value')
        settings = bindings.describe_settings(value, active_url)
        reader = Mock(); reader._load.return_value = captured
        archive = {item: item.read_bytes() for item in retained.iterdir() if item.is_file()}
        sealed = {item: item.read_bytes() for item in package.iterdir()}
        with ExitStack() as stack, \
             patch('sqlalchemy.create_engine') as engine, \
             patch('agent_factory.research_bootstrap_database_preflight.database_preflight', return_value={'status':'PASS'}) as policy, \
             patch('autoresearch_retained_baseline.RetainedBaselineReader', return_value=reader), \
             patch('run_research_baseline.config_from_bytes', return_value=original), \
             patch('research_candidate_state.open_state', side_effect=opened), \
             patch('research_candidate_reopen.reconstruct_preparation_target', return_value={
                 'reference':'preparation','target':target,'driver':SimpleNamespace(configuration_fingerprint='e'*64)}), \
             patch('agent_factory.research_device_observer.NvidiaSmiObserver', return_value=Mock(configuration_fingerprint='f'*64)) as device, \
             patch.object(bindings, '_upstream', return_value={'train.py':b'never executed'}), \
             patch('subprocess.Popen', side_effect=AssertionError('NO PROCESS')):
            configured = bindings._receiver(value, settings, resolver, stack)
            active_store = SimpleNamespace(storage=object(), sql=Mock(return_value=[]))
            receiver = configured.remote_scientific_factory(active_store, Mock(), Mock(), Mock(), None, Mock())
            self.assertIs(type(receiver), RemoteScientificReceiver)
            selected = receiver.projects[project['id']]
            self.assertIs(type(selected.assembler), ScientificPhaseAssembler)
            self.assertIs(selected.assembler.store, active_store)
            self.assertIs(selected.assembler.preparation_store, baseline_store)
            self.assertIs(selected.preparation.resources, resources)
            self.assertEqual(selected.assembler.scientific_runtime, scientific)
            self.assertIs(selected.baseline_reader, reader)
            self.assertEqual(configured.db_url, active_url)
            self.assertEqual(configured.autoresearch_presets, {})
            self.assertEqual(len(opened_settings), 2)
            self.assertTrue(all(row.db_url == baseline_url for row, _ in opened_settings))
            self.assertEqual([full for _, full in opened_settings], [False, True])
            self.assertEqual(opened_settings[0][0].policy_revision, 'task-research-bootstrap-v1')
            for phase, stage in selected.assembler.stages.items():
                self.assertEqual(stage.spec.interpreter_contract, spec.interpreter_contract)
                self.assertEqual(stage.spec.working_directory, project['assembly']['stageRoots'][phase]['program'])
                self.assertEqual(stage.spec.argv[1], str(Path(stage.spec.working_directory)/
                    ('evaluate.py' if phase == 'evaluation' else 'train_candidate.py')))
            # Neither origin bearer nor scientific device is accessed at construction.
            self.assertNotIn(value['handoffBearerRef'], [call.args[0] for call in resolver.call_args_list])
            device.return_value.assert_not_called()
            engine.return_value.dispose.assert_called_once()
            # An active stage cannot reuse the retained namespace.
            project['assembly']['stageRoots']['training']['program'] = str(source_program)
            with self.assertRaises(ValueError):
                blocked = bindings._receiver(value, settings, resolver, stack)
                receiver_again = blocked.remote_scientific_factory(active_store, Mock(), Mock(), Mock(), None, Mock())
                self.fail(type(receiver_again).__name__)
            opened_settings.clear()
            policy.return_value = {'status': 'BLOCKED'}
            with self.assertRaises(ValueError):
                bindings._receiver(value, settings, resolver, stack)
            self.assertEqual(opened_settings, [])
        self.assertEqual(archive, {item:item.read_bytes() for item in archive})
        self.assertEqual(sealed, {item:item.read_bytes() for item in sealed})
        self.assertEqual(_runtime_pins(scientific), tuple(pins))
