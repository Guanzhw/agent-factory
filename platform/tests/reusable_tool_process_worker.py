"""Owned native process for reusable CLI acceptance; no external providers.

The parent allocates disposable loopback PG and a shared workspace. Phase two
starts fresh services and only reads original definitions/accounts before use.
"""
import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy.engine import make_url

from agent_factory.application_runs import factory_request_id
from agent_factory.config import Settings
from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.personal_cli import cli_destination
from agent_factory.personal_mcp import mcp_url
from agent_factory.personal_tool_contract import ToolInvocationError
import test_reusable_tool_operations_postgres as fixture


def effect_identity(harness, task):
    return [{key: row.get(key) for key in ('effect_key', 'status', 'result')}
            for row in harness.store.effects(task['id'])]


def task_identity(task):
    return {key: task[key] for key in ('id', 'run_id', 'plan_id', 'request_id', 'owner_id')}


def first(harness, database_url, workspace):
    # Reuse the actual native/CLI fixture, borrowing only the parent's allocation.
    class BorrowedDatabase:
        def __init__(self, _):
            self.url = database_url
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    directory = SimpleNamespace(name=str(workspace), cleanup=lambda: None)
    with patch.object(fixture, 'IsolatedPostgres', BorrowedDatabase), \
            patch.object(fixture, 'TemporaryDirectory', return_value=directory), \
            patch.dict(os.environ, {'FACTORY_TEST_DATABASE_URL': database_url}):
        harness.setup_transport('cli')
    accounts, connections, tasks = {}, {}, {}
    for owner in ('alice', 'bob'):
        account, connection = harness.account(owner, owner)
        accounts[owner] = {key: account[key] for key in ('registrationRef', 'revision', 'operationRef')}
        connections[owner] = {'ref': connection['ref']}
        public_request_id = 'process-completed-' + owner
        task = harness.assert_run(owner, connection, owner, public_request_id)
        harness.assertEqual(task['request_id'], factory_request_id(public_request_id))
        tasks[owner] = {'publicRequestId': public_request_id,
                        'task': task_identity(task), 'effects': effect_identity(harness, task)}
    adapter = harness.store.personal_tools.adapters[harness.operation['runtimeBinding']['adapterId']]
    invoke = adapter.invoke
    async def lose_ack(invocation):
        result = await invoke(invocation)
        if invocation.arguments['value'] == 'stock-2':
            raise ToolInvocationError('SYNTHETIC_PROCESS_ACK_LOST')
        return result
    adapter.invoke = lose_ack
    body, started = harness.submit('alice', connections['alice'], 'process-original-unknown')
    unknown = harness.wait(started, 'alice', expected={'completed', 'cancelled'})
    effects = effect_identity(harness, unknown)
    harness.assertEqual(len(effects), 2)
    harness.assertEqual({row['status'] for row in effects}, {'DONE', 'UNKNOWN'})
    harness.assertEqual(harness.calls(), ['alice', 'alice', 'bob', 'bob', 'alice', 'alice'])
    return {'pid': os.getpid(), 'operation': harness.operation, 'materialRef': harness.material_ref,
            'accounts': accounts, 'connections': connections, 'completed': tasks,
            'unknown': {'task': task_identity(unknown), 'effects': effects, 'body': body},
            'calls': harness.calls()}


def restore(harness, database_url, workspace, saved):
    # No setup_transport/create/publish/configure calls: restoration must stand alone.
    harness.transport, harness.phases, harness.pause = 'cli', {}, None
    harness.marker = workspace / 'business.jsonl'
    harness.operation, harness.material_ref = saved['operation'], saved['materialRef']
    harness.settings = Settings(db_url=database_url, workspace=workspace, max_workers=2,
        max_user_tasks=2, temporary_policy='member-self-service',
        runtime_adapters=[AdapterRegistration('model', fixture.native.MODEL, '1',
            lambda _: fixture.OperationModel(), demo_only=True),
            AdapterRegistration('environment', fixture.native.ENVIRONMENT, '1', lambda _: EnvironmentLimits())],
        credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b't' * 32,
            {'member-cli': fixture.DestinationPolicy(cli_destination), 'member-mcp': fixture.DestinationPolicy(mcp_url)}))
    harness.client = None
    harness.start()
    harness.addCleanup(harness.stop)
    harness.assertNotEqual(saved['pid'], os.getpid())
    harness.assertIn(saved['operation'], harness.request('GET', '/personal-tools/operations', owner='bob'))
    handles = []
    for owner in ('alice', 'bob'):
        saved_account = saved['accounts'][owner]
        account = harness.request('GET', '/personal-tools/' + saved_account['registrationRef'], owner=owner)
        harness.assertEqual({key: account[key] for key in saved_account}, saved_account)
        handles.append(harness.store.connections.resolve(owner, saved['connections'][owner]['ref'], 'tool'))
        original = saved['completed'][owner]
        task = original['task']
        harness.assertEqual(task_identity(harness.store.task(task['id'], owner)), task)
        harness.assertEqual(effect_identity(harness, task), original['effects'])
        plan = harness.store.plan(task['plan_id'], owner)
        harness.assertIn(saved['materialRef'], plan['materialRefs'])
        harness.assertEqual(task['request_id'], factory_request_id(original['publicRequestId']))
        receipt = harness.request('GET', '/application-interface/v1/starts/' + original['publicRequestId'], owner=owner)
        harness.assertEqual((receipt['taskId'], receipt['runId']), (task['id'], task['run_id']))
        harness.assertFalse(receipt['automaticReplay'])
    singleton = harness.store.personal_tools.adapters[saved['operation']['runtimeBinding']['adapterId']]
    harness.assertTrue(all(handle.adapter is singleton for handle in handles))
    harness.assertEqual([handle.owner for handle in handles], ['alice', 'bob'])
    unknown = saved['unknown']['task']
    public_request_id = saved['unknown']['body']['requestId']
    harness.assertEqual(unknown['request_id'], factory_request_id(public_request_id))
    receipt = harness.request('GET', '/application-interface/v1/starts/' + public_request_id, owner='alice')
    harness.assertEqual((receipt['taskId'], receipt['runId']), (unknown['id'], unknown['run_id']))
    harness.assertFalse(receipt['automaticReplay'])
    harness.request('POST', '/jobs/' + unknown['id'] + '/reconcile')
    harness.assertEqual(task_identity(harness.store.task(unknown['id'], 'alice')), unknown)
    harness.assertEqual(effect_identity(harness, unknown), saved['unknown']['effects'])
    harness.assertFalse(harness.store.task(unknown['id'])['terminal'])
    harness.assertEqual(harness.calls(), saved['calls'], 'Restoring and reconciling must not redispatch original calls')
    new_task = harness.assert_run('bob', saved['connections']['bob'], 'bob', 'process-bob-after-restart')
    harness.assertNotEqual(new_task['run_id'], saved['completed']['bob']['task']['run_id'])
    harness.assertEqual(harness.calls(), saved['calls'] + ['bob', 'bob'])
    harness.assertEqual(effect_identity(harness, unknown), saved['unknown']['effects'])
    return {'pid': os.getpid(), 'previousPid': saved['pid'], 'singletonRestored': True,
            'unknown': task_identity(unknown), 'unknownEffects': effect_identity(harness, unknown),
            'newBobTask': task_identity(new_task), 'calls': harness.calls()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('first', 'restore'))
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    database_url = os.environ['REUSABLE_PROCESS_DATABASE_URL']
    url = make_url(database_url)
    if url.host not in {'127.0.0.1', 'localhost', '::1'} or not url.database.startswith('af_test_'):
        raise ValueError('Process fixture requires parent-owned disposable loopback PG')
    saved_path = args.workspace / 'first-report.json'
    harness = fixture.ReusableToolOperationPostgresTests('runTest')
    try:
        report = first(harness, database_url, args.workspace) if args.phase == 'first' else restore(
            harness, database_url, args.workspace, json.loads(saved_path.read_text()))
    finally:
        if not harness.doCleanups():
            raise RuntimeError('Owned native service cleanup failed')
    report['servicesClosed'] = True
    (args.workspace / (args.phase + '-report.json')).write_text(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
