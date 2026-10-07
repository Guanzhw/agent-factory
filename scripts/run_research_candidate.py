"""Single external candidate invocation over the installed research runtime.

No automatic retries, baseline rerun, keep/rollback, credential acquisition or GPU
work at import time. Original baseline evidence is read only; all new receipts
stay in a fresh private workspace. Recovery is separate from execution.
"""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import time
import warnings

import run_research_baseline as baseline
from run_research_baseline import (canonical, read_private, write_private, identity,
    runtime_identity, environment_pins, launch_environment, request_client)

ERROR = 'RESEARCH_CANDIDATE_STOPPED'
_KEYS = {'schema', 'baselineConfigFile', 'baselineEvaluationReceiptFile', 'baselineRunConfigFile',
         'candidateTrainFile', 'candidateSha256', 'workspace', 'requestId', 'totalSeconds', 'ackCandidate'}


def require(value):
    if not value:
        raise ValueError(ERROR)


def decode(raw):
    require(type(raw) is bytes and 0 < len(raw) <= 16 * 1024**2)
    return json.loads(raw, object_pairs_hook=baseline.unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError(ERROR)))


def config_from_bytes(raw):
    value = decode(raw)
    require(type(value) is dict and set(value) == _KEYS and type(value['schema']) is int
            and value['schema'] == 1 and value['ackCandidate'] is True)
    for key in ('baselineConfigFile', 'baselineEvaluationReceiptFile', 'baselineRunConfigFile',
                'candidateTrainFile', 'workspace'):
        path = value[key]
        require(type(path) is str and path.startswith('/') and str(Path(path)) == path
                and '..' not in Path(path).parts)
    require(type(value['candidateSha256']) is str and re.fullmatch('[a-f0-9]{64}', value['candidateSha256']))
    require(type(value['requestId']) is str and re.fullmatch('[A-Za-z0-9_.:-]{8,40}', value['requestId']))
    require(type(value['totalSeconds']) is int and 1 <= value['totalSeconds'] <= 86400)
    return value


def load_inputs(config):
    from agent_factory.research_manifest import validate_manifest, manifest_fingerprint
    from agent_factory.research_assessment import assess_observations
    raw = {key: read_private(config[key]) for key in
        ('baselineConfigFile', 'baselineEvaluationReceiptFile', 'baselineRunConfigFile')}
    original = baseline.config_from_bytes(raw['baselineConfigFile'])
    require(config['workspace'] != original['workspace'] and config['requestId'] != original['requestId'])
    receipt = decode(raw['baselineEvaluationReceiptFile'])
    run_config = decode(raw['baselineRunConfigFile'])
    manifest = validate_manifest(run_config['comparisonManifest'])
    observation = receipt['imported']['observation']
    assess_observations(observation, observation)
    fingerprint = manifest_fingerprint(manifest)
    require(observation['status'] == 'completed' and observation['comparisonIdentitySha256'] == fingerprint
            and observation['variantSha256'] == manifest['baselineSourceManifestSha256'])
    candidate = read_private(config['candidateTrainFile'], 8 * 1024**2, private=False)
    require(hashlib.sha256(candidate).hexdigest() == config['candidateSha256'])
    return {'baselineConfig': original, 'baselineReceipt': receipt, 'baselineRunConfig': run_config,
        'manifestSha256': fingerprint, 'observation': observation, 'candidateBytes': candidate,
        'identity': {'baselineManifestSha256': fingerprint, 'candidateSha256': config['candidateSha256'],
                     'configSha256': hashlib.sha256(canonical({'config': config, 'retained':
                         {key: hashlib.sha256(value).hexdigest() for key, value in raw.items()}})).hexdigest()}}


def stage_timeout(journal, wall_seconds):
    remaining = journal.remaining()
    require(type(remaining) in {int, float} and math.isfinite(remaining) and remaining >= 1)
    return int(min(remaining, wall_seconds + 120, 86400))


def preparation_phase(bundle, client, request_id, progress, journal):
    require(journal.remaining() >= 60)
    from bootstrap_research_control import ensure_task_development_reviewer
    from agent_factory.process_runtime_profile import publish_process_application
    state, store = bundle['state'], bundle['state']['store']
    progress.at('PREPARATION_PUBLICATION')
    reviewer = ensure_task_development_reviewer(state)
    app = publish_process_application(state, target_ref='preparation', author='manager', reviewer=reviewer)
    original_request = request_client(bundle, client)
    deadline, task_id, plan_id = time.monotonic() + 60, None, None
    def request(*args, **kwargs):
        journal.remaining()
        require(time.monotonic() < deadline)
        return original_request(*args, **kwargs)
    def post(path, body, key, owner='alice'):
        return request('POST', '/api/factory' + path, {**body, 'requestId': request_id + ':prep:' + key}, owner=owner)
    try:
        progress.at('PREPARATION_PROPOSAL')
        proposal = post('/compositions/proposals', {'goal': 'Prepare source-bound tokenizer byte lengths',
            'mode': 'controlled-fixture', 'applicationRef': {k: app[k] for k in ('id', 'version', 'sha256')}}, 'proposal')
        progress.at('PREPARATION_PLAN')
        plan = post('/compositions/proposals/' + proposal['id'] + '/accept', {}, 'accept')
        plan_id = plan['id']
        progress.at('PREPARATION_REVIEW')
        review = post('/plan-reviews', {'planId': plan['id']}, 'review')
        progress.at('PREPARATION_APPROVAL')
        post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, 'decision', reviewer)
        try:
            progress.at('PREPARATION_SUBMIT')
            task = post('/instances', {'planId': plan['id']}, 'instance')
            task_id = task['id']
        except BaseException as error:
            progress.capture(error)
            progress.at('PREPARATION_RECEIPT')
            # Read-only lost-ACK recovery has its own bounded HTTP timeout and
            # must remain available after the execution admission deadline.
            receipt = original_request('GET', '/api/factory/requests/' + request_id + ':prep:instance', None, owner='alice')
            require(receipt['planId'] == plan['id'] and receipt['requestId'] == request_id + ':prep:instance')
            task_id = receipt['taskId']
            progress.record('preparation', {'taskId': task_id, 'planId': plan['id'], 'phase': 'ACCEPTED'})
            raise
        progress.record('preparation', {'taskId': task_id, 'planId': plan['id'], 'phase': 'ACCEPTED'})
        progress.at('PREPARATION_WAIT')
        while True:
            require(time.monotonic() < deadline)
            detail = request('GET', '/api/factory/jobs/' + task_id, None, owner='alice')
            require(detail['job']['status'] not in {'failed', 'canceled', 'unknown'})
            if detail['job']['status'] == 'completed':
                break
            time.sleep(.1)
        progress.at('PREPARATION_IMPORT')
        original = store.process_runtime._original(task_id)
        require(original is not None)
        lease = store.process_runtime.resources.inspect('alice', original['lease_id'])
        require(lease['state'] == 'RECLAIMED' and lease['executionStatus'] == 'COMPLETED'
                and lease['capacityHeld'] is False and lease['stopEvidence']['allStopped'] is True)
        artifact = bundle['preparation'].import_completed('alice', lease['id'])
        pin = bundle['preparation'].input_pin('alice', task_id, artifact['id'])
        progress.record('preparation', {'phase': 'IMPORTED', 'taskId': task_id, 'nativeRunId': lease['nativeRunId'],
            'leaseId': lease['id'], 'providerJobId': lease['providerJobId'], 'artifactId': artifact['id']})
        return task_id, artifact['id'], pin
    except BaseException as error:
        progress.capture(error)
        progress.at('PREPARATION_CLEANUP')
        validated_original = False
        if task_id is not None:
            try:
                original_task = store.task(task_id, 'alice')
                require(original_task['id'] == task_id and original_task['owner_id'] == 'alice'
                        and plan_id is not None and original_task['plan_id'] == plan_id)
                validated_original = True
            except Exception:
                pass
        if validated_original:
            assert task_id is not None
            from agent_factory.research_bootstrap_controller import cleanup_original
            assert client.portal is not None
            cleanup = cleanup_original(state, 'alice', task_id, runtime=store.process_runtime,
                                       call_async=client.portal.call)
            progress.record('preparation', {'phase': 'STOPPED', 'taskId': task_id, **cleanup})
            try:
                original_request('POST', '/api/factory/jobs/' + task_id + '/cancel', {}, owner='alice')
            except Exception:
                pass
        raise


def execute(candidate_config, workspace, progress, journal):
    inputs = load_inputs(candidate_config)
    require(inputs['identity'] == journal.snapshot()['identity'])
    config = inputs['baselineConfig']
    config = {**config, 'workspace': str(workspace), 'requestId': candidate_config['requestId']}
    # Imports stay inside the explicitly acknowledged execution path. No Torch import.
    progress.at('EXECUTION_IMPORTS')
    from fastapi.testclient import TestClient
    from bootstrap_research_control import read_database_url, ensure_task_development_reviewer
    from agent_factory.research_bootstrap_assembly import prepare_application
    from research_candidate_assembly import research_application
    from research_candidate_baseline import authorize_baseline
    from research_candidate_reopen import make_snapshot, make_preparation_snapshot
    from agent_factory.research_local_driver import derive_local_identities
    from agent_factory.research_manifest import manifest_fingerprint
    from agent_factory.research_assessment import assess_observations
    from agent_factory.research_bootstrap_inventory import build_inventory
    from agent_factory.research_bootstrap_inputs import capture_bootstrap_inputs
    from agent_factory.research_interpreter import capture_interpreter_contract
    from agent_factory.research_profile import SOURCE_SHA256, verify_upstream_source
    from agent_factory.gpu_custody import GpuBinding
    from agent_factory.research_device_observer import NvidiaSmiObserver
    from agent_factory.process_enforcement import ResearchProcessLimits, UvResearchProcessSpec
    from agent_factory.research_runtime_profile import publish_research_application
    from agent_factory.research_bootstrap_controller import ResearchBootstrapController
    progress.at('EXECUTION_IDENTITY')
    runtime_identity(config)
    # Authenticate the retained original via its real providers and evaluator
    # service before preparation or any candidate native instance is created.
    require(authorize_baseline(inputs) == inputs['observation'])
    progress.at('DATABASE_CONFIG')
    db = read_database_url(config['databaseUrlFile'])
    progress.at('UPSTREAM_READ')
    upstream = {name: read_private(Path(config['upstreamRoot']) / name, 8 * 1024**2, private=False) for name in SOURCE_SHA256}
    progress.at('UPSTREAM_VERIFY')
    verify_upstream_source(upstream)
    candidate_files = {**upstream, 'train.py': inputs['candidateBytes']}
    derived = derive_local_identities(upstream, candidate_files, microbatch=config['microbatch'])
    variant = derived['identities']['candidate']['sha256']
    require(variant != derived['identities']['baseline']['sha256'])
    require(inputs['observation']['variantSha256'] == derived['identities']['baseline']['sha256'])
    progress.at('TOKENIZER_READ')
    tokenizer = read_private(Path(config['inputRoot']) / config['tokenizerBasename'], 1024**2)
    progress.at('RESOURCE_LIMITS')
    limits = ResearchProcessLimits(**config['limits'])
    require(limits.disk_bytes >= 2 * limits.file_size_bytes + limits.output_bytes)
    def directory(name):
        path = workspace / name; path.mkdir(mode=0o700)
        return path
    progress.at('DEVICE_OBSERVER')
    gpu = GpuBinding(config['receiverNamespaceSha256'], hashlib.sha256(config['deviceUuid'].encode()).hexdigest())
    device = NvidiaSmiObserver(Path(config['nvidiaSmi']['executable']), config['nvidiaSmi']['sha256'],
                               config['deviceUuid'], gpu, 'task-local-real-observer-v1')
    bundles = []
    def retain(bundle):
        bundles.append(bundle)
        return bundle
    try:
        journal.begin_stage('preparation')
        journal.record_progress('preparation', {'requestId': config['requestId'] + ':prep:instance'})
        progress.at('PREPARATION_ASSEMBLY')
        program = directory('preparation-program')
        prep_custody = directory('preparation-custody')
        prep_manifest = hashlib.sha256(canonical({'schema': 1, 'purpose': 'tokenizer-preparation',
            'tokenizerSha256': hashlib.sha256(tokenizer).hexdigest()})).hexdigest()
        write_private(workspace / 'preparation-recovery.json', canonical(make_preparation_snapshot(
            program_root=program, program_identity=identity(program), custody_root=prep_custody,
            executable=config['interpreterTarget'], executable_sha256=config['interpreterSha256'],
            tokenizer_json=tokenizer, preparation_manifest_sha256=prep_manifest)))
        prep = retain(prepare_application(db_url=db, workspace=workspace, program_root=program, diagnostics=progress,
            program_identity=identity(program), custody_root=prep_custody,
            executable=config['interpreterTarget'], executable_sha256=config['interpreterSha256'],
            tokenizer_json=tokenizer, preparation_manifest_sha256=prep_manifest))
        progress.at('PREPARATION_STARTUP')
        with TestClient(prep['app']) as client:
            try:
                prep_task, prep_artifact, token_pin = preparation_phase(prep, client, config['requestId'], progress, journal)
                journal.finish_stage('preparation', {'status': 'COMPLETED', 'cleanupConfirmed': True})
            except BaseException as error:
                progress.capture(error)
                raise
            finally:
                progress.at('PREPARATION_SHUTDOWN')
        progress.at('ENVIRONMENT_INVENTORY')
        evidence = directory('environment')
        inventory = build_inventory(project_root=config['projectRoot'], venv_root=config['venvRoot'],
            interpreter_target=config['interpreterTarget'], interpreter_sha256=config['interpreterSha256'],
            approved_interpreter_roots=config['approvedInterpreterRoots'], inventory_path=evidence / 'inventory.json',
            startup_profile='uv0117-setuptools82-local-v1')
        write_private(evidence / 'inventory.json', inventory['inventoryBytes'])
        write_private(evidence / 'kernel.json', inventory['kernelBytes'])
        progress.at('INTERPRETER_CONTRACT')
        contract = capture_interpreter_contract(**inventory['captureKwargs'])
        write_private(evidence / 'interpreter-contract.json', contract.encode())
        progress.at('ENVIRONMENT_PINS')
        pins = environment_pins(config, evidence, inventory)
        progress.at('INPUT_CAPTURE')
        captured = capture_bootstrap_inputs(input_root=Path(config['inputRoot']), tokenizer_basename=config['tokenizerBasename'],
            shards=tuple((row['id'], row['basename']) for row in config['shards']), validation_ids=tuple(config['validationIds']),
            upstream_files=upstream, environment_pins=pins, gpu_binding=gpu, limits=limits,
            token_bytes_pin=token_pin, microbatch=config['microbatch'])
        require(manifest_fingerprint(captured['comparisonManifest']) == inputs['manifestSha256'])
        prior, training, training_store = prep, None, None
        results = {}
        for stage in ('training', 'evaluation'):
            journal.begin_stage(stage)
            progress.at(stage.upper() + '_ASSEMBLY')
            program, cache, custody = directory(stage + '-program'), directory(stage + '-cache'), directory(stage + '-custody')
            entry = 'train_candidate.py' if stage == 'training' else 'evaluate.py'
            env = launch_environment(config, program, cache)
            spec = UvResearchProcessSpec(str(Path(config['venvRoot']) / 'bin/python'), config['interpreterSha256'],
                ('-B', str(program / entry), '--config', str(program / 'run-config.json')), working_directory=str(program),
                working_directory_identity=(identity(program)['device'], identity(program)['inode']), environment=tuple(sorted(env.items())),
                interpreter_contract=contract)
            write_private(workspace / (stage + '-recovery.json'), canonical(make_snapshot(
                stage=stage, captured_inputs=captured, environment_pins=pins, launch_spec=spec,
                program_identity=identity(program), cache_root=cache, cache_identity=identity(cache),
                custody_root=custody, upstream_files=upstream, candidate_files=candidate_files,
                training=training, microbatch=config['microbatch'],
                bounds_profile=inventory['captureKwargs']['bounds_profile'])))
            bundle = retain(research_application(db_url=db, workspace=workspace, upstream_files=upstream, candidate_files=candidate_files,
                captured_inputs=captured, environment_pins=pins, launch_spec=spec, program_identity=identity(program),
                cache_root=cache, cache_identity=identity(cache), custody_root=custody, limits=limits, gpu_binding=gpu,
                device_observer=device, preparation=prep['preparation'], preparation_task_id=prep_task,
                preparation_artifact_id=prep_artifact, prior_targets=prior['settings'].remote_targets,
                prior_adapters=prior['settings'].runtime_adapters, prior_pricing=prior['settings'].usage_pricing,
                training_store=training_store, training=training, microbatch=config['microbatch'],
                bounds_profile=inventory['captureKwargs']['bounds_profile']))
            progress.at(stage.upper() + '_STARTUP')
            with TestClient(bundle['app']) as client:
                try:
                    progress.at(stage.upper() + '_PUBLICATION')
                    reviewer = ensure_task_development_reviewer(bundle['state'])
                    app = publish_research_application(bundle['state'], target_ref=stage,
                        comparison_manifest=captured['comparisonManifest'], author='manager', reviewer=reviewer,
                        variant_sha256=variant, adapter_suffix='-candidate-' + stage)
                    assert client.portal is not None
                    portal = client.portal
                    def imported(owner, task, lease):
                        if stage == 'training':
                            artifact = bundle['checkpoints'].import_completed(owner, lease['id'])
                            _, checked = bundle['checkpoints'].identity(task['id'], artifact['id'], limits.file_size_bytes)
                            plan = bundle['state']['store'].plan(task['plan_id'], owner)
                            return {**{key: lease[field] for key, field in (('ownerId', 'ownerId'), ('taskId', 'localTaskId'),
                                ('nativeRunId', 'nativeRunId'), ('planId', 'planId'), ('leaseId', 'id'), ('providerJobId', 'providerJobId'))},
                                'planFingerprint': plan['fingerprint'], 'variantSha256': lease['executionGuard']['variantSha256'],
                                'checkpoint': {'artifactId': artifact['id'], **checked}}
                        return portal.call(bundle['state']['store'].research_evaluation.verify,
                            owner, bundle['pending']['evaluationContract'])
                    progress.at(stage.upper() + '_RUN')
                    result = ResearchBootstrapController(bundle['state'], request_client(bundle, client), portal.call).run(
                        owner='alice', reviewer=reviewer, application_ref={k: app[k] for k in ('id', 'version', 'sha256')},
                        goal='Source-bound candidate' if stage == 'training' else 'Independent checkpoint evaluation',
                        request_id=config['requestId'] + ':' + stage, timeout_seconds=stage_timeout(journal, limits.wall_seconds),
                        after_reclaimed=imported, on_progress=lambda value: progress.record(stage, value))
                    progress.at(stage.upper() + '_RECEIPT')
                    journal.finish_stage(stage, {'status': 'COMPLETED', 'cleanupConfirmed': True})
                    results[stage] = result
                    write_private(workspace / (stage + '-receipt.json'), canonical(result))
                    if stage == 'training':
                        training, training_store = result['imported'], bundle['checkpoints']
                except BaseException as error:
                    progress.capture(error)
                    raise
                finally:
                    progress.at(stage.upper() + '_SHUTDOWN')
            prior = bundle
        assessment = assess_observations(inputs['observation'], results['evaluation']['imported']['observation'])
        write_private(workspace / 'assessment.json', canonical(assessment))
        return {**results, 'assessment': assessment}
    except BaseException as error:
        progress.capture(error)
        raise
    finally:
        progress.at('CLEANUP')
        for bundle in reversed(bundles):
            for store in (bundle['state']['store'], bundle['providerStore']):
                store.dispose_root_locks(); store.engine.dispose()
                native = getattr(store, 'native_db', None)
                if native is not None:
                    native.db_engine.dispose()



class Progress(baseline.Progress):
    def __init__(self, workspace, journal):
        super().__init__(workspace)
        self.journal = journal

    def at(self, stage):
        # Deadline bounds admission and controller calls; cleanup must remain
        # available after expiry. It cannot interrupt synchronous database I/O.
        if stage not in {'CLEANUP', 'PREPARATION_RECEIPT'} and not stage.endswith('_SHUTDOWN') and not stage.endswith('_CLEANUP'):
            self.journal.remaining()
        super().at(stage)

    def record(self, stage, value):
        if stage in ('preparation', 'training', 'evaluation'):
            self.journal.record_progress(stage, value)
        super().record(stage, value)


def main(argv=None, run=execute):
    argv = sys.argv[1:] if argv is None else argv
    previous_logging = logging.root.manager.disable
    try:
        recovering = len(argv) == 3 and argv[0] == '--recover'
        if recovering:
            argv = argv[1:]
        require(len(argv) == 2 and argv[0] == '--config')
        config = config_from_bytes(read_private(argv[1]))
        from bootstrap_research_control import _workspace
        from research_candidate_recovery import CandidateJournal
        workspace = Path(config['workspace'])
        if recovering:
            identity(workspace)
            logging.disable(logging.CRITICAL)
            with warnings.catch_warnings(), open(os.devnull, 'w') as sink, \
                    redirect_stdout(sink), redirect_stderr(sink):
                warnings.simplefilter('ignore')
                from research_candidate_recover_command import recover
                inputs = load_inputs(config)
                with CandidateJournal(workspace / 'candidate-journal.json', identity=inputs['identity']) as journal:
                    report = recover(config, inputs, journal)
            print('RESEARCH_CANDIDATE_ORIGINAL_STOP_CONFIRMED' if report['cleanupConfirmed']
                  else 'RESEARCH_CANDIDATE_ORIGINAL_CUSTODY_UNKNOWN')
            return 0 if report['cleanupConfirmed'] else 2
        if workspace.exists() or workspace.is_symlink():
            identity(workspace)
            print('RESEARCH_CANDIDATE_EXISTING_INSPECT_ONLY')
            return 0
        logging.disable(logging.CRITICAL)
        with warnings.catch_warnings(), open(os.devnull, 'w') as sink, \
                redirect_stdout(sink), redirect_stderr(sink):
            warnings.simplefilter('ignore')
            inputs = load_inputs(config)
        _workspace(str(workspace), create=True)
        with CandidateJournal(workspace / 'candidate-journal.json', identity=inputs['identity'],
                              total_seconds=config['totalSeconds']) as journal:
            require(journal.fresh)
            progress = Progress(workspace, journal)
            progress.record('controller', {'phase': 'STARTED', 'requestId': config['requestId']})
            logging.disable(logging.CRITICAL)
            with warnings.catch_warnings(), open(os.devnull, 'w') as sink, \
                    redirect_stdout(sink), redirect_stderr(sink):
                warnings.simplefilter('ignore')
                try:
                    run(config, workspace, progress, journal)
                except BaseException:
                    for stage, row in journal.snapshot()['stages'].items():
                        if row['consumed'] and row['result'] is None:
                            journal.finish_stage(stage, {
                                'status': 'STOPPED' if row['progress'].get('phase') == 'STOPPED' else 'UNKNOWN',
                                'cleanupConfirmed': row['progress'].get('cleanupConfirmed') is True})
                    progress.record('controller', {'phase': 'STOPPED', 'cleanupConfirmed': False})
                    raise
            progress.record('controller', {'phase': 'COMPLETED', 'scientificConclusionVerified': False})
        print('RESEARCH_CANDIDATE_COMPLETED_PRIVATE_EVIDENCE')
        return 0
    except BaseException:
        print(ERROR, file=sys.stderr)
        return 2
    finally:
        logging.disable(previous_logging)


if __name__ == '__main__':
    raise SystemExit(main())
