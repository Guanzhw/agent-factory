"""Cancel one original waiting native research ticket without starting a worker."""
from agno.agent import Agent
from agno.job_queue.config import QueueConfig
from agno.os.job_queue import QueueWorker, resolve_queue_store

_FIELDS = {'ownerId', 'taskId', 'nativeRunId', 'planId', 'requestId'}


def _require(value):
    if not value:
        raise ValueError('RESEARCH_NATIVE_STOP_UNCONFIRMED')


def _root_only(store, task, plan):
    application = plan.get('application')
    profiles = {'research-process-fixture-v1': 'research_process_run',
                'bounded-process-fixture-v1': 'bounded_process_run'}
    _require(application in profiles and (plan.get('applicationRef') or {}).get('id') == application
        and plan.get('mode') == 'controlled-fixture' and plan.get('tools') == [profiles[application]]
        and plan.get('capabilities') == ['compute:local']
        and not plan.get('delegation') and not plan.get('remoteHandoff'))
    rows = store.sql("""
        WITH related AS (
          SELECT run_id AS id FROM ai.agno_runs
          WHERE session_id=:task OR run_id=:run
             OR run_data #>> '{session_state,factory_envelope,task_id}'=:task
             OR (run_data #>> '{session_state,factory_envelope,user_id}'=:owner
                 AND run_data #>> '{session_state,factory_envelope,request_id}'=:request)
          UNION SELECT id FROM ai.agno_jobs
          WHERE session_id=:task OR id=:run
             OR payload #>> '{kwargs,session_state,factory_envelope,task_id}'=:task
             OR (payload #>> '{kwargs,session_state,factory_envelope,user_id}'=:owner
                 AND payload #>> '{kwargs,session_state,factory_envelope,request_id}'=:request)
        ), conflicts AS (
          SELECT 'factory-edge' AS reason FROM af_delegation_links
          WHERE root_id=:task OR parent_id=:task OR child_id=:task
          UNION ALL SELECT 'native-sibling' FROM related WHERE id<>:run
          UNION ALL SELECT 'native-run-edge' FROM ai.agno_runs r
          WHERE (r.run_id IN (SELECT id FROM related) AND r.parent_run_id IS NOT NULL)
             OR r.parent_run_id IN (SELECT id FROM related)
             OR (r.run_id IN (SELECT id FROM related)
                 AND jsonb_path_exists(r.run_data,'$.**.parent_run_id ? (@ != null)'))
             OR EXISTS (SELECT 1 FROM jsonb_path_query(r.run_data,'$.**.parent_run_id') v
                        WHERE v #>> '{}' IN (SELECT id FROM related))
          UNION ALL SELECT 'native-job-edge' FROM ai.agno_jobs j
          WHERE (j.id IN (SELECT id FROM related)
                 AND jsonb_path_exists(j.payload,'$.**.parent_run_id ? (@ != null)'))
             OR EXISTS (SELECT 1 FROM jsonb_path_query(j.payload,'$.**.parent_run_id') v
                        WHERE v #>> '{}' IN (SELECT id FROM related))
        ) SELECT count(*) AS count FROM conflicts
        """, task=task['id'], run=task['run_id'], owner=task['owner_id'], request=task['request_id'])
    _require(len(rows) == 1 and rows[0]['count'] == 0)


def _binding(state, task_id, expected):
    _require(type(expected) is dict and set(expected) == _FIELDS and expected['taskId'] == task_id)
    store = state['store']
    task = store.task(task_id, expected['ownerId'])
    _require(all(task[field] == expected[key] for key, field in (
        ('ownerId', 'owner_id'), ('taskId', 'id'), ('nativeRunId', 'run_id'),
        ('planId', 'plan_id'), ('requestId', 'request_id'))))
    plan = store.plan(task['plan_id'], task['owner_id'])
    _root_only(store, task, plan)
    ticket = store.lifecycle_observer._binding(task)
    _require(ticket is not None and ticket['id'] == expected['nativeRunId'])
    return task, ticket


async def cancel_native_original(state, task_id, expected):
    """Use native acancel_queued only; never claim, enqueue, resume or run a model.

    Waiting cancellation requires a previously persisted original cancellation intent. Process
    release is a separate requirement. False means native custody remains open.
    This helper does not mark the Factory task terminal or release its capacity.
    """
    task, before = _binding(state, task_id, expected)
    result = {'nativeCleanupConfirmed': False, 'taskId': task_id, 'nativeRunId': expected['nativeRunId'],
              'nativeStatus': before['status'], 'persistedRunStatus': before.get('persistedRunStatus'),
              'terminalStatus': None}
    terminal = {'completed': ('completed', 'completed'), 'failed': ('error', 'failed'),
                'cancelled': ('cancelled', 'canceled')}
    if before['status'] in terminal:
        persisted, outcome = terminal[before['status']]
        confirmed = before.get('persistedRunStatus') == persisted
        return {**result, 'nativeCleanupConfirmed': confirmed, 'terminalStatus': outcome if confirmed else None}
    if before['status'] not in {'queued', 'paused'}:
        return result
    # Only waiting tickets with an observable original run can be certified.
    if before.get('persistedRunStatus') not in {'pending', 'paused', 'running'}:
        return result
    _require(task['cancel_requested'] is True)
    state['auth'].require(task['owner_id'], 'run')
    native = state['store'].native_db
    inert = Agent(id='factory-executor', db=native, telemetry=False)

    def resolve(component_type, component_id):
        _require(component_type == 'agent' and component_id == 'factory-executor')
        return inert

    config = QueueConfig(durable=True, max_concurrency=1, max_attempts=1,
                         lock_grace_seconds=6, stop_timeout_seconds=2)
    worker = QueueWorker(resolve_queue_store(config, native), resolve, config,
                         stop_timeout=2, auto_provision=False)
    # Construction does not start polling or provisioning. Never call start().
    await worker.acancel_queued(expected['nativeRunId'])
    _, after = _binding(state, task_id, expected)
    return {**result, 'nativeStatus': after['status'], 'persistedRunStatus': after.get('persistedRunStatus'),
            'nativeCleanupConfirmed': after['status'] == 'cancelled' and after.get('persistedRunStatus') == 'cancelled',
            'terminalStatus': 'canceled' if after['status'] == 'cancelled' and after.get('persistedRunStatus') == 'cancelled' else None}
