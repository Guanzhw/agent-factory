"""Controlled native-session/provider wires; no remote install, model or OS proof."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import httpx
from sqlalchemy import create_engine, text

from agent_factory.managed_orx_attachment import (
    AttachmentControlWitness, InstalledAttachment, ManagedORXSessionProvider, EFFECT,
)
from agent_factory.managed_orx_profile import ManagedAttachmentControlModel, exact_input_schema
from agent_factory.input_schema import validate_input_schema, validate_input_values
from agent_factory.orx_research_session import OpenResearchSessionHTTP, OrxSessionUnknown
from agent_factory.process_enforcement import ProcessLimits
from agent_factory.store import canonical, digest


class DiskState:
    def __init__(self, path):
        self.engine = create_engine('sqlite:///' + str(path))
        self.sql('CREATE TABLE IF NOT EXISTS af_leases(id TEXT PRIMARY KEY,owner_id TEXT,body TEXT)')
        self.sql('CREATE TABLE IF NOT EXISTS effects(effect_key TEXT PRIMARY KEY, fingerprint TEXT,status TEXT,result TEXT)')
        self.sql('CREATE TABLE IF NOT EXISTS events(body TEXT)')
        self.allowed = True
        self.usage_ledger = SimpleNamespace(begin_attempt=self.begin, finish_attempt=self.finish)
        self.attempts, self.settlements = [], []
        self.budget_allowed = True
    def sql(self, statement, **params):
        with self.engine.begin() as conn:
            result = conn.execute(text(statement), params)
            return [dict(row) for row in result.mappings()] if result.returns_rows else []
    def task(self, identifier, owner=None):
        if identifier not in {self.t['id'], self.t['run_id']} or owner not in (None, self.t['owner_id']):
            raise ValueError('foreign task')
        return dict(self.t)
    def plan(self, identifier, owner):
        if identifier != self.p['id'] or owner != self.p['ownerId']:
            raise ValueError('foreign plan')
        return dict(self.p)
    def require_plan_execution(self, *args, **kwargs):
        if not self.allowed:
            raise PermissionError('fixture authority revoked')
    def authorize_tool(self, *args): self.require_plan_execution()
    def effect_reserve(self, run, key, request):
        key = run + ':' + key
        rows = self.sql("INSERT INTO effects VALUES(:key,:fp,'UNKNOWN',NULL) ON CONFLICT DO NOTHING RETURNING effect_key", key=key, fp=digest(request))
        if rows: return {'status': 'new'}
        value = self.sql('SELECT * FROM effects WHERE effect_key=:key', key=key)[0]
        if value['fingerprint'] != digest(request): raise ValueError('effect fingerprint conflict')
        return {'status': 'done' if value['status'] == 'DONE' else 'unknown'}
    def effect_complete(self, run, key, result):
        self.sql("UPDATE effects SET status='DONE',result=:result WHERE effect_key=:key", key=run+':'+key, result=canonical(result))
    def effects(self, task): return self.sql('SELECT * FROM effects')
    def artifact_write(self, *args, **kwargs): return {'id': 'fixture-artifact'}
    def event(self, *values): self.sql('INSERT INTO events VALUES(:body)', body=canonical(values))
    def begin(self, *args, **kwargs):
        if not self.budget_allowed: raise ValueError('fixture usage ceiling')
        self.attempts.append(kwargs)
        return 'attempt-' + str(len(self.attempts))
    def finish(self, ticket, usage): self.settlements.append((ticket, usage))


class ControlledProcess:
    """Existing ResourceProvider shape, explicitly synthetic kernel evidence."""
    limits = ProcessLimits()
    configuration_fingerprint = 'f' * 64
    capacity_namespace = 'e' * 64
    def __init__(self): self.records, self.allocations, self.cancellations = {}, 0, 0
    async def allocate_bound(self, lease, *, before_effect):
        before_effect(); self.allocations += 1
        self.records[lease['id']] = {'leaseId': lease['id'], 'ownerId': lease['ownerId'],
            'fingerprint': lease['fingerprint'], 'state': 'RUNNING', 'providerJobId': 'fixture-supervisor-job',
            'processBinding': {'taskId': lease['localTaskId'], 'nativeRunId': lease['nativeRunId'],
                'planId': lease['planId'], 'bindingFingerprint': digest(lease)},
            'enforcement': {'cpu': 'per-process-RLIMIT_CPU', 'memory': 'per-process-RLIMIT_AS',
                'fileSize': 'per-file-RLIMIT_FSIZE', 'wall': 'cooperative-process-group-guardian',
                'aggregateQuota': False, 'hostileCodeSandbox': False, 'networkIsolation': False},
            'executionStatus': 'RUNNING', 'exitCode': None, 'stopEvidence': None}
        return dict(self.records[lease['id']])
    def finish(self, lease_id, state='COMPLETED'):
        self.records[lease_id].update(state=state, executionStatus='CANCELLED' if state == 'CANCEL_CONFIRMED' else 'COMPLETED',
            exitCode=0, stopEvidence={'allStopped': True, 'kind': 'original-root-reaped-and-no-live-process-group-members'})
    async def inspect(self, lease_id, owner):
        result = self.records[lease_id]
        if result['ownerId'] != owner: raise ValueError('foreign custody')
        return dict(result)
    async def cancel(self, lease_id, owner):
        await self.inspect(lease_id, owner); self.cancellations += 1
        self.finish(lease_id, 'CANCEL_CONFIRMED')
        return await self.inspect(lease_id, owner)
    async def reclaim(self, lease_id, owner):
        original = await self.inspect(lease_id, owner)
        if (original.get('stopEvidence') or {}).get('allStopped') is not True: raise ValueError('not stopped')
        self.records[lease_id].update(state='RECLAIMED', released=True)
        return await self.inspect(lease_id, owner)


class ManagedFixture:
    def __init__(self, store):
        self.store, self.process = store, ControlledProcess()
        self.authority = object()
        self.installation = InstalledAttachment('fixture-supervisor', '1', 'a' * 64, self.authority)
        profile = {'harness': 'opencode', 'model': 'factory/deepseek-flash'}
        self.attachment = {'ownerId': 'alice', 'connectionRef': 'original-orx', 'connectionFingerprint': 'c' * 64, 'connectionVersion': 1, 'connectionRevision': '1',
            'projectId': 'original-project', 'projectIdentityHash': 'b' * 64, 'sessionId': 'original-session',
            'profile': profile, 'profileSha256': digest(profile)}
        self.provider_calls, self.messages, self.binds = 0, 0, 0
        self.lose_ack, self.complete = False, True
        self.bad_witness, self.bad_identity = False, False
        self.resource_allowed = True
        self.credential_calls = 0
        self.capability, self.broker, self.lease = None, None, None
        self.transcript = []
        self.provider = self.new_provider()
    def credential(self):
        self.credential_calls += 1
        return 'synthetic-no-access-credential'
    def controls(self, *, lease, contract):
        value = AttachmentControlWitness(self.authority, lease['id'], lease['fingerprint'], 'a' * 64,
            hashlib.sha256(self.capability.encode()).hexdigest(), contract['projectIdentityHash'],
            contract['connectionFingerprint'], contract['profileSha256'], contract['sessionId'], True, lease['id'], True, True, True)
        return dict(allStopped=True, brokerOnly=True) if self.bad_witness else value
    async def bind(self, *, lease, contract, broker, capability):
        self.binds += 1
        self.broker, self.capability, self.lease = broker, capability, lease
        return OpenResearchSessionHTTP(38123, project_id='wrong-project' if self.bad_identity else 'original-project',
            harness='opencode', model='factory/deepseek-flash', transport=httpx.MockTransport(self.native))
    async def provider_wire(self, request):
        self.provider_calls += 1
        return httpx.Response(200, json={'id': 'controlled-provider-request', 'model': 'deepseek-flash',
            'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'Controlled text'}}],
            'usage': {'prompt_tokens': 12, 'completion_tokens': 7, 'total_tokens': 19}})
    async def native(self, request):
        path = request.url.path
        if path == '/api/chat/sessions':
            return httpx.Response(200, json={'sessions': [{'id': 'original-session', 'projectId': 'original-project',
                'harness': 'opencode', 'model': 'factory/deepseek-flash', 'busy': False, 'archived': False}]})
        if path.endswith('/messages'):
            return httpx.Response(200, json={'messages': self.transcript, 'queued': [], 'activeLeafId': self.transcript[-1]['id'] if self.transcript else None})
        if path.endswith('/message'):
            self.messages += 1
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.broker), base_url='http://broker') as client:
                reply = await client.post('/v1/chat/completions', headers={'Authorization': 'Bearer ' + self.capability},
                    json={'model': 'deepseek-flash', 'messages': [{'role': 'user', 'content': json.loads(request.content)['text']}]})
            if reply.status_code != 200:
                raise ValueError('controlled broker rejected')
            goal = json.loads(request.content)['text']
            self.transcript = [{'id': 'original-user', 'role': 'user', 'parentId': None, 'createdAt': 1, 'completedAt': 1,
                'parts': [{'id': 'original-native-user-part', 'type': 'text', 'text': goal}]},
                {'id': 'original-answer', 'role': 'assistant', 'parentId': 'original-user', 'createdAt': 2, 'completedAt': 3,
                'parts': [{'type': 'text', 'text': 'Controlled text'}]}]
            if self.complete: self.process.finish(self.lease['id'])
            if self.lose_ack: raise httpx.ReadTimeout('controlled lost ack')
            return httpx.Response(200, json={'ok': True, 'turn': {'queued': False, 'existing': False, 'turnId': 'original-turn'}})
        raise AssertionError('Unexpected native path')
    def new_provider(self):
        return ManagedORXSessionProvider(store=self.store, process_provider=self.process, attachment=self.attachment,
            installation=self.installation, read_controls=self.controls, bind_session=self.bind,
            credential=self.credential, ledger_model=ManagedAttachmentControlModel(),
            observe_session=lambda **_: OpenResearchSessionHTTP(38123, project_id='original-project', harness='opencode',
                model='factory/deepseek-flash', transport=httpx.MockTransport(self.native)), broker_transport=httpx.MockTransport(self.provider_wire))
    def seed(self):
        self.store.t = {'id': 'task', 'owner_id': 'alice', 'plan_id': 'plan', 'run_id': 'run', 'request_id': 'original-request',
            'terminal': False, 'cancel_requested': False}
        self.store.p = {'id': 'plan', 'ownerId': 'alice', 'normalizedGoal': 'One approved text-only turn',
            'inputValues': {'managedAttachment': self.provider.contract},
            'usageBudget': {'model': 'deepseek-flash', 'provider': 'opencode-go-development', 'perAttemptOutputTokens': 32}}
        lease = {'id': 'lease', 'ownerId': 'alice', 'localTaskId': 'task', 'nativeRunId': 'run', 'planId': 'plan',
            'planHash': digest(self.store.p), 'fingerprint': 'd' * 64, 'connectionRef': 'managed-target',
            'targetFingerprint': 'f' * 64, 'state': 'RESERVED', 'providerNamespace': self.provider.capacity_namespace,
            'deadlineAt': (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}
        def authorize(*_):
            if not self.resource_allowed: raise PermissionError('resource grant revoked')
            return SimpleNamespace(provider=self.provider)
        self.store.connections = SimpleNamespace(preflight=lambda *_args, **_kwargs: None)
        self.store.process_runtime = SimpleNamespace(resources=SimpleNamespace(_authorize=authorize,
            _target_fingerprint=lambda _: 'f' * 64, _admit_effect=lambda *_: None))
        self.store.sql('INSERT INTO af_leases VALUES(:id,:owner,:body)', id=lease['id'], owner='alice', body=canonical(lease))
        return lease


class ManagedAttachmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = DiskState(Path(self.tmp.name) / 'intent.sqlite'); self.addCleanup(self.store.engine.dispose)
        self.f = ManagedFixture(self.store); self.lease = self.f.seed()
    async def allocate(self): return await self.f.provider.allocate_bound(self.lease, before_effect=lambda: None)
    async def test_original_session_broker_usage_and_positive_process_receipt(self):
        result = await self.allocate()
        self.assertEqual((self.f.messages, self.f.provider_calls, self.f.credential_calls), (1, 1, 1))
        self.assertEqual(len(self.store.attempts), 1)
        self.assertEqual(self.store.settlements[0][1].input_tokens, 12)
        self.assertEqual(self.store.settlements[0][1].output_tokens, 7)
        self.assertTrue(result['stopEvidence']['allStopped'])
        observed = self.store.sql('SELECT result FROM effects WHERE effect_key=:key', key='run:'+EFFECT)[0]
        native = json.loads(observed['result'])['nativeResult']
        self.assertEqual((native['sessionId'], native['turnId'], native['assistantMessageId'], native['text']),
            ('original-session', 'original-turn', 'original-answer', 'Controlled text'))
        self.assertEqual(result['processBinding']['nativeRunId'], 'run')
        reclaimed = await self.f.provider.reclaim('lease', 'alice')
        self.assertEqual(reclaimed['state'], 'RECLAIMED')
        saved = self.store.sql('SELECT * FROM effects')
        self.assertEqual(len(saved), 3)
        self.assertNotIn(self.f.capability, canonical(saved))
    async def test_known_ack_restart_recovers_original_text_without_new_broker_or_turn(self):
        self.f.complete = False
        await self.allocate()
        self.f.process.finish('lease')
        reopened = self.f.new_provider()
        self.f.provider = reopened
        result = await reopened.inspect('lease', 'alice')
        self.assertTrue(result['stopEvidence']['allStopped'])
        native = json.loads(self.store.sql('SELECT result FROM effects WHERE effect_key=:key', key='run:'+EFFECT)[0]['result'])['nativeResult']
        self.assertEqual(native['text'], 'Controlled text')
        self.assertEqual((self.f.binds, self.f.messages, self.f.provider_calls), (1, 1, 1))
        self.assertEqual(reopened._brokers, {})

    async def test_unknown_ack_reopen_never_repeats_message_or_provider_request(self):
        self.f.lose_ack = True
        with self.assertRaises(OrxSessionUnknown): await self.allocate()
        reopened = self.f.new_provider()
        self.f.provider = reopened
        with self.assertRaises(ValueError): await reopened.allocate_bound(self.lease, before_effect=lambda: None)
        await reopened.inspect('lease', 'alice')
        self.assertEqual((self.f.messages, self.f.provider_calls, self.process_allocations()), (1, 1, 1))
        message = self.store.sql('SELECT * FROM effects WHERE effect_key=:key', key='run:'+EFFECT+':one-original-message')[0]
        self.assertEqual(json.loads(message['result'])['deliveryOutcome'], 'unknown')
        self.assertTrue(json.loads(message['result'])['allStopped'])
    def process_allocations(self): return self.f.process.allocations
    async def test_runtime_self_report_is_not_installer_control_witness(self):
        self.f.bad_witness = True
        with self.assertRaises(ValueError): await self.allocate()
        self.assertEqual((self.f.messages, self.f.provider_calls, self.f.credential_calls), (0, 0, 0))
    async def test_wrong_original_session_transport_is_denied(self):
        self.f.bad_identity = True
        with self.assertRaises(ValueError): await self.allocate()
        self.assertEqual(self.f.messages, 0)
    async def test_shared_budget_denial_precedes_credential_and_provider(self):
        self.store.budget_allowed = False
        with self.assertRaises(OrxSessionUnknown): await self.allocate()
        self.assertEqual((self.f.credential_calls, self.f.provider_calls), (0, 0))
    async def test_revoked_original_cleanup_retains_task_scope_and_requires_stop(self):
        self.f.complete = False
        await self.allocate()
        with self.assertRaises(ValueError): await self.f.provider.reclaim('lease', 'alice')
        self.store.allowed = False
        result = await self.f.provider.cancel('lease', 'alice')
        self.assertTrue(result['stopEvidence']['allStopped'])
        self.assertEqual((await self.f.provider.reclaim('lease', 'alice'))['state'], 'RECLAIMED')
        self.assertEqual(self.f.messages, 1)
    async def test_foreign_owner_plan_drift_and_false_stop_never_release(self):
        await self.allocate()
        with self.assertRaises(ValueError): await self.f.provider.cancel('lease', 'bob')
        self.f.process.records['lease']['stopEvidence']['allStopped'] = 1
        with self.assertRaises(ValueError): await self.f.provider.reclaim('lease', 'alice')
        self.store.p['normalizedGoal'] = 'changed'
        with self.assertRaises(ValueError): await self.f.provider.inspect('lease', 'alice')
    async def test_retained_broker_denies_resource_grant_and_lease_cancellation(self):
        self.f.complete = False
        await self.allocate()
        self.f.resource_allowed = False
        with self.assertRaises(PermissionError): self.f.provider._current(self.lease)
        self.f.resource_allowed = True
        body = dict(self.lease, cancelRequested=True)
        self.store.sql('UPDATE af_leases SET body=:body WHERE id=:id', body=canonical(body), id='lease')
        with self.assertRaises(ValueError): self.f.provider._current(self.lease)
        self.assertEqual(self.f.provider_calls, 1)

    async def test_terminal_allocation_never_binds_or_sends_native_turn(self):
        allocate = self.f.process.allocate_bound
        async def terminal(lease, **kwargs):
            await allocate(lease, **kwargs)
            self.f.process.finish(lease['id'])
            return await self.f.process.inspect(lease['id'], lease['ownerId'])
        self.f.process.allocate_bound = terminal
        with self.assertRaises(ValueError): await self.allocate()
        self.assertEqual((self.f.binds, self.f.messages, self.f.provider_calls), (0, 0, 0))

    async def test_unrelated_active_leaf_is_never_adopted_as_original_response(self):
        native = self.f.native
        async def replaced(request):
            result = await native(request)
            if request.url.path.endswith('/message'):
                self.f.transcript[-1]['parentId'] = 'unrelated-user'
            return result
        self.f.native = replaced
        with self.assertRaises(ValueError): await self.allocate()
        self.assertEqual(self.f.provider_calls, 1)
        events = self.store.sql('SELECT body FROM events')
        self.assertFalse(any('managed_native_session_result' in e['body'] for e in events))

    async def test_session_exclusivity_false_denies_before_native_message(self):
        from dataclasses import replace
        original = self.f.controls
        self.f.provider.read_controls = lambda **kwargs: replace(original(**kwargs), session_exclusive=False)
        with self.assertRaises(ValueError): await self.allocate()
        self.assertEqual((self.f.messages, self.f.provider_calls), (0, 0))

    async def test_revocation_during_independent_control_read_denies_dispatch(self):
        original = self.f.controls
        async def revoked(**kwargs):
            value = original(**kwargs)
            self.store.allowed = False
            return value
        self.f.provider.read_controls = revoked
        with self.assertRaises(PermissionError): await self.allocate()
        self.assertEqual((self.f.messages, self.f.provider_calls, self.f.credential_calls), (0, 0, 0))

    def test_contract_is_detached_and_validates_as_exact_governed_input(self):
        value = self.f.provider.contract; value['profile']['model'] = 'other'
        self.assertNotEqual(value, self.f.provider.contract)
        schema = exact_input_schema(self.f.provider.contract)
        validate_input_schema(schema)
        self.assertEqual(validate_input_values(schema, {'managedAttachment': self.f.provider.contract}), {'managedAttachment': self.f.provider.contract})
        with self.assertRaises(ValueError): validate_input_values(schema, {'managedAttachment': value})
