"""Explicit original-invocation stop/reconcile command; never restart a stage."""
import asyncio
from pathlib import Path


def recover(config, inputs, journal, *, database_url_file=None, database_url=None):
    from bootstrap_research_control import read_database_url
    from run_research_baseline import read_private, canonical, write_private
    from run_research_candidate import decode, require
    from research_candidate_state import open_state
    from research_candidate_reopen import reconstruct_research_target, reconstruct_preparation_target
    from research_candidate_recovery import recover_original
    from research_candidate_native_stop import cancel_native_original
    from agent_factory.config import Settings
    from agent_factory.research_bootstrap_policy import development_settings

    require(not journal.fresh and journal.snapshot()['identity'] == inputs['identity'])
    original = {**inputs['baselineConfig'], 'workspace': config['workspace'], 'requestId': config['requestId']}
    workspace = Path(config['workspace'])
    require(database_url_file is None or database_url is None)
    if database_url_file is not None:
        from research_candidate_database import resolve_database
        database_url = resolve_database(inputs, database_url_file)
    db = database_url if database_url is not None else read_database_url(original['databaseUrlFile'])
    settings = development_settings(Settings(db_url=db, workspace=workspace, max_workers=1,
                                             temporary_policy='admin-review'))
    report = {'schema': 1, 'kind': 'candidate-original-stop-only', 'stages': {},
              'trainingResumed': False, 'newAttempts': 0, 'scientificConclusionVerified': False}
    # Only one invocation's explicitly consumed stages are visited. No global tick.
    with open_state(settings) as state:
        for stage, row in journal.snapshot()['stages'].items():
            if not row['consumed']:
                continue
            progress = row['progress']
            result = {'cleanupConfirmed': False, 'nativeCleanupConfirmed': False,
                      'status': 'UNKNOWN'}
            try:
                snapshot = decode(read_private(workspace / (stage + '-recovery.json'), 16 * 1024**2))
                require(snapshot['stage'] == stage)
                rebuilt = (reconstruct_preparation_target(state, snapshot) if stage == 'preparation'
                           else reconstruct_research_target(state, original, snapshot))
                state['resources'].targets[stage] = rebuilt['target']
                store = state['store']
                request_id = config['requestId'] + (':prep:instance' if stage == 'preparation'
                                                     else ':' + stage + ':instance')
                task = store.task_for_request(request_id, 'alice')
                expected = {'ownerId': 'alice', 'taskId': task['id'], 'planId': task['plan_id'],
                            'nativeRunId': task['run_id'], 'requestId': request_id}
                require(task['owner_id'] == 'alice' and task['request_id'] == request_id
                        and type(task['run_id']) is str)
                for field in ('taskId', 'planId', 'nativeRunId'):
                    require(field not in progress or progress[field] == expected[field])
                # A source-bound request receipt may fill a lost ACK, never create one.
                state['lifecycle_observer']._binding(task)
                runtime = state['process_runtime' if stage == 'preparation' else 'research_runtime']
                mapping = runtime._original(task['id'])
                if mapping is None:
                    # Preserve uncertainty about external effects, but stop the
                    # exact queued/paused native intent before it can advance.
                    store.request_cancel(task['id'])
                    native = asyncio.run(cancel_native_original(state, task['id'], expected))
                    result['nativeCleanupConfirmed'] = native['nativeCleanupConfirmed'] is True
                    report['stages'][stage] = result
                    continue
                lease, _, current, ticket = runtime._custody(mapping['lease_id'])
                require(current['id'] == task['id'] and lease['connectionRef'] == stage)
                for field, key in (('leaseId', 'id'), ('providerJobId', 'providerJobId')):
                    require(field not in progress or progress[field] == lease.get(key))
                journal.record_progress(stage, {key: expected[key] for key in ('taskId', 'planId', 'nativeRunId')})
                if row['result'] and row['result']['status'] == 'COMPLETED':
                    require(lease['state'] == 'RECLAIMED' and lease['capacityHeld'] is False
                            and lease.get('stopEvidence', {}).get('allStopped') is True
                            and lease.get('executionStatus') == 'COMPLETED'
                            and type(lease.get('exitCode')) is int and lease['exitCode'] == 0
                            and (stage == 'preparation' or lease.get('gpuEvidence', {}).get('state') == 'RELEASED')
                            and ticket.get('status') == 'completed'
                            and ticket.get('persistedRunStatus') == 'completed')
                    result = {'status': 'COMPLETED', 'cleanupConfirmed': True,
                              'nativeCleanupConfirmed': task['terminal'] is True}
                else:
                    cleanup = asyncio.run(recover_original(state, runtime, 'alice', task['id'], 5))
                    require(cleanup['leaseId'] == lease['id'])
                    native = asyncio.run(cancel_native_original(state, task['id'], expected))
                    native_confirmed = native['nativeCleanupConfirmed'] is True
                    if cleanup['cleanupConfirmed'] and native_confirmed:
                        store.observed(store.task(task['id'], 'alice'), native['terminalStatus'], True)
                    result = {**cleanup, 'nativeCleanupConfirmed': native_confirmed,
                              'status': 'STOPPED' if cleanup['cleanupConfirmed'] and native_confirmed else 'UNKNOWN'}
                    journal.record_progress(stage, {**cleanup, 'phase': progress.get('phase', 'STOPPED')
                                                     if progress.get('phase') == 'COMPLETED' else 'STOPPED'})
                    old_status = (row['result'] or {}).get('status')
                    journal.finish_stage(stage, {'status': old_status or result['status'],
                                                 'cleanupConfirmed': cleanup['cleanupConfirmed']})
            except Exception:
                # No exception/path details in a public result; UNKNOWN holds remain.
                pass
            report['stages'][stage] = result
    report['cleanupConfirmed'] = bool(report['stages']) and all(
        row['cleanupConfirmed'] and row['nativeCleanupConfirmed'] for row in report['stages'].values())
    # Each recovery is evidence, never an overwrite of the original run receipt.
    import uuid
    write_private(workspace / ('recovery-' + uuid.uuid4().hex + '.json'), canonical(report))
    return report
