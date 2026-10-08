"""Concrete, fixed operator assembly for the two scientific handoff roles.

No Python module names or callable references are accepted from configuration.
The original scientific interpreter/package and baseline are receiver-only pins;
controller settings never initialize or upgrade that retained database.
"""
from copy import deepcopy
from pathlib import Path
import re
from urllib.parse import urlsplit

from agent_factory.research_manifest import validate_manifest
from agent_factory.research_local_driver import ScientificRuntimePin

ERROR = 'AUTORESEARCH_OPERATOR_PROJECT_INVALID'
COMMON = {'id', 'name', 'ownerId', 'defaultGoal', 'manifest', 'microbatch', 'limits',
          'upstreamRoot', 'applicationRef'}


def require(value):
    if not value:
        raise ValueError(ERROR)


def fields(value, keys):
    require(type(value) is dict and set(value) == keys)


def identifier(value):
    require(type(value) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', value))


def sha(value):
    require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value))


def path(value):
    require(type(value) is str and Path(value).is_absolute() and '..' not in Path(value).parts and '\x00' not in value)


def owner(value):
    require(type(value) is str and 1 <= len(value) <= 200 and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def endpoint(value):
    require(type(value) is str and len(value) <= 2048)
    parsed = urlsplit(value)
    require(parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username
        and not parsed.password and not parsed.query and not parsed.fragment
        and parsed.path in ('', '/'))
    require(parsed.scheme == 'https' or parsed.hostname in {'localhost', '127.0.0.1', '::1'})


def project_descriptor(config):
    """Pure descriptor validation; no file, environment, DB or provider reads."""
    project = deepcopy(config['project'])
    additions = {'receiver', 'orx', 'modelCredentialRef', 'billingAuthorized', 'runtimeFilePins'} if config['role'] == 'controller' else {'baseline', 'assembly', 'origin'}
    fields(project, COMMON | additions | ({'applicationSnapshot'} if 'applicationSnapshot' in project else set()))
    if project.get('applicationSnapshot') is not None:
        from agent_factory.applications import ApplicationDefinition
        import json
        snapshot = project['applicationSnapshot']
        fields(snapshot, set(ApplicationDefinition.model_fields) | {'version', 'createdAt', 'schema', 'origin', 'sha256'})
        require(len(json.dumps(snapshot, allow_nan=False).encode('utf-8')) <= 131072)
    identifier(project['id']); require(len(project['id']) <= 40); owner(project['ownerId'])
    for key, maximum in (('name', 200), ('defaultGoal', 2000)):
        require(type(project[key]) is str and 1 <= len(project[key]) <= maximum)
    path(project['upstreamRoot']); validate_manifest(project['manifest'])
    require(type(project['microbatch']) is int and project['microbatch'] in {1, 2, 4, 8})
    limits = project['limits']
    ranges = {'totalSeconds': (1, 3600), 'experimentSeconds': (1, 600), 'maxExperiments': (1, 1),
        'toolCalls': (1, 128), 'outputBytes': (1024, 1048576), 'modelRequests': (1, 16), 'modelOutputTokens': (1, 4096)}
    fields(limits, set(ranges))
    for key, (low, high) in ranges.items():
        require(type(limits[key]) is int and low <= limits[key] <= high)
    require(limits['totalSeconds'] >= limits['experimentSeconds'])
    if project['applicationRef'] is not None:
        fields(project['applicationRef'], {'id', 'version', 'sha256'})
        identifier(project['applicationRef']['id']); sha(project['applicationRef']['sha256'])
        require(type(project['applicationRef']['version']) is int and project['applicationRef']['version'] > 0)
    if config['role'] == 'controller':
        from agent_factory.research_staging import FilePin
        from agent_factory.research_local_driver import _RUNTIME_FILES
        require(type(project['runtimeFilePins']) is list and len(project['runtimeFilePins']) == len(_RUNTIME_FILES))
        for row in project['runtimeFilePins']:
            fields(row, {'basename', 'sha256', 'size_bytes'})
            FilePin(**row)
        require(tuple(row['basename'] for row in project['runtimeFilePins']) == _RUNTIME_FILES)
        receiver = project['receiver']
        fields(receiver, {'targetRef', 'originRef', 'baseUrl', 'ownerId', 'revision', 'projectPin'})
        for key in ('targetRef', 'originRef', 'revision'): identifier(receiver[key])
        owner(receiver['ownerId']); endpoint(receiver['baseUrl']); sha(receiver['projectPin'])
        require(type(project['modelCredentialRef']) is str and re.fullmatch('[A-Z_][A-Z0-9_]{0,127}', project['modelCredentialRef']))
        require(type(project['billingAuthorized']) is bool)
        runtime = project['orx']
        fields(runtime, {'sessionRoot', 'image', 'orx', 'opencode', 'projectId'})
        path(runtime['sessionRoot']); identifier(runtime['projectId'])
        require(type(runtime['image']) is str and re.fullmatch('sha256:[a-f0-9]{64}', runtime['image']))
        for key in ('orx', 'opencode'):
            fields(runtime[key], {'path', 'sha256'}); path(runtime[key]['path']); sha(runtime[key]['sha256'])
    else:
        baseline = project['baseline']
        fields(baseline, {'databaseRef', 'configFile', 'evaluationReceiptFile', 'trainingRunConfigFile', 'scientificRuntime'})
        require(type(baseline['databaseRef']) is str and re.fullmatch('[A-Z_][A-Z0-9_]{0,127}', baseline['databaseRef']))
        require(baseline['databaseRef'] != config['databaseRef'])
        for key in ('configFile', 'evaluationReceiptFile', 'trainingRunConfigFile'): path(baseline[key])
        ScientificRuntimePin.from_dict(baseline['scientificRuntime'])
        origin = project['origin']
        fields(origin, {'baseUrl', 'originRef', 'targetRef', 'originOwnerId', 'revision', 'targetFingerprint'})
        endpoint(origin['baseUrl']); owner(origin['originOwnerId']); sha(origin['targetFingerprint'])
        for key in ('originRef', 'targetRef', 'revision'): identifier(origin[key])
        assembly = project['assembly']
        fields(assembly, {'projectPin', 'preparationSnapshotFile', 'preparationReference', 'stageRoots'})
        sha(assembly['projectPin']); path(assembly['preparationSnapshotFile'])
        fields(assembly['preparationReference'], {'taskId', 'artifactId'})
        for value in assembly['preparationReference'].values(): identifier(value)
        fields(assembly['stageRoots'], {'training', 'evaluation'})
        roots = []
        for stage in assembly['stageRoots'].values():
            fields(stage, {'program', 'cache', 'custody'})
            for value in stage.values(): path(value); roots.append(value)
        require(len(set(roots)) == len(roots))
    return project


def _receiver_parent_catalogue_registrations():
    """Declare the shared catalogue contract without installing parent execution.

    Adapter descriptors identify the governed material contract, not code hashes
    or proof that a provider ran. Remote execution maps only to the separately
    registered scientific phase IDs. Every parent factory rejects construction.
    """
    from dataclasses import replace
    from agent_factory.autoresearch_profile import registrations
    def deny_parent(_context):
        raise ValueError('AUTORESEARCH_RECEIVER_PARENT_EXECUTION_DENIED')
    return [replace(entry, factory=deny_parent) for entry in registrations(external_session=True)]


def describe_settings(config, database_url):
    """Settings only: constructors here perform no file/DB/provider operations."""
    from dataclasses import replace
    from agent_factory.autoresearch import ResearchPreset
    from agent_factory import remote_scientific_profile
    from bootstrap_autoresearch import settings as base_settings
    project = project_descriptor(config)
    preset = ResearchPreset(id=project['id'], name=project['name'], owner_id=project['ownerId'],
        default_goal=project['defaultGoal'], instructions='Read original approved research context.',
        manifest=project['manifest'], limits=project['limits'], external_session=True,
        application_ref=project['applicationRef'] or {}, review_owner=config['publication']['reviewer'])
    settings = base_settings(db_url=database_url, workspace=Path(config['workspace']), preset=preset)
    if config['role'] == 'controller':
        from agent_factory.autoresearch_profile import registrations, pricing_registration
        settings = replace(settings,
            runtime_adapters=registrations(external_session=True) + remote_scientific_profile.registrations(project['id']),
            usage_pricing=(pricing_registration(output_tokens=project['limits']['modelOutputTokens']),
                *remote_scientific_profile.pricing_registrations()))
    if config['role'] == 'receiver':
        from agent_factory.autoresearch_profile import pricing_registration
        settings = replace(settings, autoresearch_presets={},
            runtime_adapters=_receiver_parent_catalogue_registrations() + remote_scientific_profile.registrations(project['id']),
            usage_pricing=(pricing_registration(
                output_tokens=project['limits']['modelOutputTokens']), *remote_scientific_profile.pricing_registrations()))
    return replace(settings, port=config['port'])


def _upstream(project):
    from agent_factory.research_profile import SOURCE_SHA256, verify_upstream_source
    from run_research_baseline import read_private
    values = {name: read_private(Path(project['upstreamRoot']) / name, 8 * 1024**2, private=False)
        for name in SOURCE_SHA256}
    verify_upstream_source(values)
    return values


def _variant(project, candidate):
    from agent_factory.research_local_driver import derive_declared_local_identities
    from agent_factory.research_staging import FilePin
    files = _upstream(project)
    derived = derive_declared_local_identities(files, {**files, 'train.py': candidate['trainPy'].encode()},
        runtime_file_pins=tuple(FilePin(**row) for row in project['runtimeFilePins']),
        microbatch=project['microbatch'])['identities']
    manifest = project['manifest']
    require(derived['baseline']['sha256'] == manifest['baselineSourceManifestSha256'])
    for field, name in (('code', 'evaluatorCode'), ('configuration', 'evaluatorConfiguration')):
        require(manifest['evaluator'][field] == {key: derived[name][key] for key in ('sha256', 'sizeBytes')})
    require(derived['candidate']['sha256'] != derived['baseline']['sha256'])
    return derived['candidate']['sha256']


def _controller(config, settings, resolve):
    from dataclasses import replace
    from agent_factory.autoresearch_remote_children import AutoResearchRemoteChildren
    from agent_factory.autoresearch_runtime import AutoResearchRuntime
    from agent_factory.remote_handoff import HandoffTarget
    from agent_factory.remote_scientific_origin import RemoteScientificOrigin
    from agent_factory.store import digest
    from autoresearch_scientific_preset import OperatorScientificConfig, make_preset
    from orx_research_runtime import Runtime, RuntimeConfig, BinaryPin, private_directory
    project = project_descriptor(config); peer = project['receiver']; holder = {}
    target = HandoffTarget(peer['targetRef'], peer['originRef'], peer['baseUrl'],
        {project['ownerId']: peer['ownerId']},
        lambda owner_id: {'Authorization': 'Bearer ' + resolve(config['handoffBearerRef'])}
            if owner_id == project['ownerId'] else {}, configuration_revision=peer['revision'])
    def validate(owner_id, parent, sourceplan, placement):
        require(owner_id == project['ownerId'] and parent['owner_id'] == owner_id
            and placement['targetRef'] == target.reference and placement['projectId'] == project['id']
            and placement['projectPin'] == peer['projectPin'])
        require(placement['scopeBinding']['originParentTaskId'] == parent['id']
            and placement['scopeBinding']['originParentRunId'] == parent['run_id']
            and placement['scopeBinding']['candidateSha256'] == digest(placement['candidate']))
        return _variant(project, placement['candidate'])
    def remote_factory(store, auth, resources, handoff_client, receiver, commands):
        service = RemoteScientificOrigin(store, auth, project_validator=validate, handoff_client=handoff_client,
            project_bindings={project['id']: {'targetRef': peer['targetRef'], 'projectPin': peer['projectPin'],
                'manifest': project['manifest'], 'ownerId': project['ownerId']}})
        holder['remote'] = service
        return service
    def child_factory(store, auth, service, resources):
        children = AutoResearchRemoteChildren(store, auth, service, target_ref=peer['targetRef'],
            project_id=project['id'], project_pin=peer['projectPin'], manifest=project['manifest'])
        holder['children'] = children
        return children
    async def baseline():
        return await holder['remote'].project_baseline(project['ownerId'], peer['targetRef'], project['id'], peer['projectPin'])
    async def experiment(ctx, candidate, call_id, *, parent_guard):
        return await holder['children'].experiment(ctx, candidate, call_id, parent_guard=parent_guard)
    async def verify(ctx, result):
        return await holder['children'].result_verifier(ctx, result)
    def runtime(ctx, service):
        # The native parent's managed effect admits this per-original-run namespace.
        identifier(ctx.run_context.run_id)
        session = private_directory(project['orx']['sessionRoot']) / ctx.run_context.run_id
        session.mkdir(mode=0o700)
        spec = project['orx']
        launcher = Runtime(RuntimeConfig(str(session), spec['image'], BinaryPin(**spec['orx']),
            BinaryPin(**spec['opencode']), wall_seconds=project['limits']['totalSeconds'],
            max_output_tokens=project['limits']['modelOutputTokens'], project_id=spec['projectId']))
        return AutoResearchRuntime(ctx, service, launcher=launcher, project_id=spec['projectId'],
            credential=lambda: resolve(project['modelCredentialRef']),
            billing_authorized=lambda: project['billingAuthorized'],
            max_requests=project['limits']['modelRequests'], max_output_tokens=project['limits']['modelOutputTokens'])
    preset = make_preset(OperatorScientificConfig(project['id'], project['name'], project['ownerId'],
        project['defaultGoal'], project['manifest'], project['limits'], lambda: _upstream(project), baseline,
        microbatch=project['microbatch'], review_owner=config['publication']['reviewer']),
        runtime_factory=runtime, subordinate_executor=experiment, result_verifier=verify)
    preset = replace(preset, application_ref=project['applicationRef'] or {})
    return replace(settings, jwt_key=resolve(config['jwtRef']), handoff_targets={target.reference: target},
        autoresearch_presets={preset.id: preset}, autoresearch_children_factory=child_factory,
        remote_scientific_factory=remote_factory)


def _state(app):
    current = app
    while not hasattr(current, 'state') and hasattr(current, 'app'):
        current = current.app
    require(hasattr(current, 'state') and hasattr(current.state, 'factory'))
    return current.state.factory


def prepare_publication(app, publication):
    """Use actual distinct-manager governance; never approve a task here."""
    from agent_factory import remote_scientific_profile as profile
    from agent_factory.store import digest
    from agent_factory.autoresearch_profile import material_drafts, application_definition
    state = _state(app); config = app.operator_config; project = project_descriptor(config)
    author, reviewer = publication['author'], publication['reviewer']
    require(author != reviewer)
    state['auth'].require(author, 'components:write'); state['auth'].require(reviewer, 'agent_os:admin')
    governance, applications = state['material_governance'], state['applications']
    def material(definition):
        key = 'remote-science:' + digest(definition)
        row = governance.create_draft(author, definition, key + ':draft')
        review = governance.request_publication(author, row['id'], row['version'], key + ':review')
        governance.decide_publication(reviewer, review['id'], True, key + ':approve')
        return row
    budget = {key: project['limits'][key] for key in ('toolCalls', 'experimentSeconds', 'outputBytes')}
    budget.update(maxDepth=1, maxChildren=3)
    modes = {profile.MODE_NAMES[phase]: profile.mode_definition(
        [material(row) for row in profile.material_drafts(project['id'], phase)], phase, limits=budget)
        for phase in profile.PHASES}
    # Both endpoints govern the identical full application; role-specific
    # execution authority lives in registrations/services, not a divergent hash.
    materials = [material(row) for row in material_drafts(project['id'], external_session=True)]
    definition = application_definition(materials, project['id'], limits=budget, external_session=True,
        scientific_modes={'scientific-' + phase: modes[profile.MODE_NAMES[phase]] for phase in profile.PHASES})
    definition['modes'] = {'research': definition['modes']['research'], **modes}
    from agent_factory.applications import ApplicationDefinition
    normalized = ApplicationDefinition.model_validate(definition).model_dump(exclude_none=True)
    snapshot = project.get('applicationSnapshot')
    if snapshot is not None:
        # Only the exact shared definition is importable. Preserve source
        # timestamp/version/digest; local publication remains independently reviewed.
        require({field: snapshot[field] for field in ApplicationDefinition.model_fields} == normalized)
        key = 'remote-science-app-import:' + digest(snapshot)
        row = applications.import_snapshot(author, snapshot, key + ':import')
    else:
        key = 'remote-science-app:' + digest(definition)
        row = applications.create_draft(author, definition, key + ':draft')
    review = applications.request_publication(author, row['id'], row['version'], key + ':review')
    applications.decide_publication(reviewer, review['id'], True, key + ':approve')
    ref = {key: row[key] for key in ('id', 'version', 'sha256')}
    if config['role'] == 'controller':
        from dataclasses import replace
        preset = next(iter(state['settings'].autoresearch_presets.values()))
        approved = replace(preset, application_ref=ref)
        state['settings'].autoresearch_presets[approved.id] = approved
        state['store'].autoresearch.presets[approved.id] = approved
    return {'applicationRef': ref, 'applicationSnapshot': deepcopy(row)}


def _receiver(config, settings, resolve, stack):
    from dataclasses import replace
    from sqlalchemy import create_engine
    from agent_factory.config import Settings
    from agent_factory.gpu_custody import GpuBinding
    from agent_factory.process_enforcement import ResearchProcessLimits, UvResearchProcessSpec
    from agent_factory.process_runtime_profile import process_settings
    from agent_factory.remote_authority import OriginAuthorityTransport
    from agent_factory.remote_handoff import TrustedOrigin
    from agent_factory.remote_scientific_receiver import RemoteScientificProject, RemoteScientificReceiver
    from agent_factory.research_bootstrap_policy import development_settings
    from agent_factory.research_bootstrap_database_preflight import database_preflight
    from agent_factory.research_checkpoint_store import ResearchCheckpointStore
    from agent_factory.research_device_observer import NvidiaSmiObserver
    from agent_factory.research_manifest import manifest_fingerprint
    from agent_factory.research_preparation_store import ResearchPreparationStore
    from agent_factory.research_staging import FilePin, InputPin, RootIdentity
    from autoresearch_baseline_context import BaselineServiceFactory
    from autoresearch_retained_baseline import RetainedBaselineReader
    from autoresearch_scientific_assembly import ScientificPhaseAssembler, ScientificStage
    from research_candidate_state import open_state
    from research_candidate_reopen import reconstruct_preparation_target
    from run_research_baseline import config_from_bytes, read_private, unique, identity
    import hashlib
    import json
    project = project_descriptor(config); source = project['baseline']; descriptor = project['assembly']
    scientific_runtime = ScientificRuntimePin.from_dict(source['scientificRuntime'])
    factory = BaselineServiceFactory(baseline_database_url=resolve(source['databaseRef']),
        controller_database_url=settings.db_url, scientific_runtime=scientific_runtime)
    reader = RetainedBaselineReader(source['configFile'], source['evaluationReceiptFile'], source['trainingRunConfigFile'],
        expected_manifest_sha256=manifest_fingerprint(project['manifest']), owner_id=project['ownerId'], service_factory=factory)
    original = config_from_bytes(read_private(Path(source['configFile'])))
    require(original['microbatch'] == project['microbatch'])
    captured = reader._load()
    require(captured['originalConfig'] == original and captured['contract']['comparisonManifest'] == project['manifest'])
    def load(path_value):
        return json.loads(read_private(Path(path_value), 16 * 1024**2), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError(ERROR)))
    prep_snapshot = load(descriptor['preparationSnapshotFile'])
    baseline_db = resolve(source['databaseRef'])
    basic = development_settings(Settings(db_url=baseline_db, workspace=Path(original['workspace']),
        temporary_policy='admin-review', max_workers=1))
    engine = create_engine(baseline_db, connect_args={'connect_timeout': 5})
    try:
        require(database_preflight(engine, basic)['status'] == 'PASS')
    finally:
        engine.dispose()
    provider_state = stack.enter_context(open_state(basic))
    rebuilt = reconstruct_preparation_target(provider_state, prep_snapshot, owner=project['ownerId'])
    prep_settings = development_settings(process_settings(db_url=baseline_db, workspace=Path(original['workspace']),
        target_ref=rebuilt['reference'], remote_targets={rebuilt['reference']: rebuilt['target']}))
    prep_state = stack.enter_context(open_state(prep_settings, full_verification=True))
    preparation = ResearchPreparationStore(prep_state['store'], prep_state['auth'], prep_state['resources'],
        prep_state['store'].storage, preparation_manifest_sha256=prep_snapshot['preparationManifestSha256'],
        source_sha256=rebuilt['driver'].configuration_fingerprint)
    origin = project['origin']
    authority = OriginAuthorityTransport(base_url=origin['baseUrl'], origin_ref=origin['originRef'],
        target_ref=origin['targetRef'], target_revision=origin['revision'], target_fingerprint=origin['targetFingerprint'],
        receiver_identity_map={origin['originOwnerId']: project['ownerId']},
        credential_provider=lambda owner_id: resolve(config['handoffBearerRef'])
            if owner_id == origin['originOwnerId'] else '', configuration_revision=origin['revision'])
    trusted = TrustedOrigin(origin['originRef'], {origin['originOwnerId']: project['ownerId']}, authority,
        capabilities=frozenset({'compute:local', 'research:read'}),
        tools=frozenset({'research_process_run', 'research_preparation_verify'}),
        budget={'toolCalls': project['limits']['toolCalls'], 'maxDepth': 1, 'maxChildren': 3,
            'experimentSeconds': project['limits']['experimentSeconds'], 'outputBytes': project['limits']['outputBytes']},
        configuration_revision=origin['revision'], tool_contract='autoresearch-session-v1')
    def receiver_factory(store, auth, resources, handoff_client, receiver, commands):
        stages = {}
        for phase in ('training', 'evaluation'):
            roots = descriptor['stageRoots'][phase]
            for value in roots.values():
                actual = Path(value)
                require(actual.is_absolute() and actual.is_relative_to(settings.workspace)
                    and actual != settings.workspace and not actual.is_relative_to(Path(original['workspace']))
                    and not actual.is_relative_to(Path(original['venvRoot'])))
            pin = RootIdentity(**identity(Path(roots['program'])))
            # Reuse the exact original interpreter contract without copying or importing its package.
            raw = deepcopy(captured['snapshots'][phase]['launchSpec'])
            raw['argv'] = ('-B', str(Path(roots['program']) / ('evaluate.py' if phase == 'evaluation' else 'train_candidate.py')),
                '--config', str(Path(roots['program']) / 'run-config.json'))
            raw['working_directory'] = roots['program']; raw['working_directory_identity'] = (pin.device, pin.inode)
            env = dict(raw['environment'])
            for key in ('HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR'):
                env[key] = roots['cache']
            env['PYTHONPYCACHEPREFIX'] = roots['program']
            raw['environment'] = tuple(sorted(env.items()))
            spec = UvResearchProcessSpec(**raw)
            stages[phase] = ScientificStage(spec, pin, Path(roots['cache']),
                RootIdentity(**identity(Path(roots['cache']))), Path(roots['custody']))
        snapshot = captured['snapshots']['training']
        pins = tuple(InputPin(row['label'], row['kind'], row['root'], RootIdentity(**row['root_identity']),
            FilePin(**row['file'])) for row in snapshot['environmentPins'])
        gpu = GpuBinding(original['receiverNamespaceSha256'], hashlib.sha256(original['deviceUuid'].encode()).hexdigest())
        observer = NvidiaSmiObserver(Path(original['nvidiaSmi']['executable']), original['nvidiaSmi']['sha256'],
            original['deviceUuid'], gpu, 'task-local-real-observer-v1')
        checkpoints = ResearchCheckpointStore(store, auth, resources, store.storage)
        assembler = ScientificPhaseAssembler({'store': store, 'auth': auth, 'resources': resources, 'settings': settings},
            owner=project['ownerId'], upstream_files=_upstream(project), captured_inputs=snapshot['capturedInputs'],
            environment_pins=pins, stages=stages, limits=ResearchProcessLimits(**original['limits']),
            gpu_binding=gpu, device_observer=observer, preparation=preparation, checkpoints=checkpoints,
            preparation_target_ref=rebuilt['reference'], preparation_reference=descriptor['preparationReference'],
            microbatch=project['microbatch'], bounds_profile=snapshot['boundsProfile'],
            scientific_runtime=scientific_runtime, preparation_state=prep_state)
        registered = RemoteScientificProject(project['ownerId'], descriptor['projectPin'], assembler,
            preparation, checkpoints, project['manifest'], reader)
        return RemoteScientificReceiver(store, auth, {project['id']: registered}, commands)
    return replace(settings, jwt_key=resolve(config['jwtRef']), handoff_origins={trusted.reference: trusted},
        remote_scientific_factory=receiver_factory)


class OperatorApplication:
    """Own explicitly retained baseline contexts until serve or prepare finishes."""
    def __init__(self, app, config, stack):
        self.app, self.operator_config, self.stack = app, deepcopy(config), stack
    async def __call__(self, scope, receive, send):
        try:
            await self.app(scope, receive, send)
        finally:
            if scope['type'] == 'lifespan': self.close()
    def close(self):
        self.stack.close()


def construct_application(config, settings, resolve):
    from contextlib import ExitStack
    from agent_factory.main import create_app
    stack = ExitStack()
    try:
        configured = _controller(config, settings, resolve) if config['role'] == 'controller' else _receiver(config, settings, resolve, stack)
        app = create_app(configured)
        state = _state(app)
        store = state['store']
        stack.callback(store.engine.dispose)
        stack.callback(store.native_db.db_engine.dispose)
        stack.callback(store.dispose_root_locks)
        schedules = state.get('schedules')
        if schedules is not None:
            stack.callback(schedules.manager.close)
            stack.callback(schedules.lock_engine.dispose)
            stack.callback(schedules.diagnostics.engine.dispose)
        if config['project']['applicationRef'] is not None:
            state['applications'].require_current(config['project']['applicationRef'])
        return OperatorApplication(app, config, stack)
    except BaseException:
        stack.close()
        raise
