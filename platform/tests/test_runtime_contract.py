"""Actual native Agent tool/HITL loop and bounded compute contract tests."""
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

from agno.db.sqlite import SqliteDb
from agno.run import RunContext
from agno.run.base import RunStatus
from agent_factory.runtime import build_runtime
from core_native_fixture import SEEDS
from agent_factory.store import digest
from core_native_fixture import fixture_bindings as default_bindings


def process_running(pid):
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle: return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally: kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        stat = Path(f'/proc/{pid}/stat')
        return not stat.exists() or stat.read_text().split(') ',1)[1].split()[0] != 'Z'
    except ProcessLookupError: return False


class ContractStore:
    """Only persistence/authority is a fixture here; the Agno loop is actual."""
    def __init__(self, application='fixture-text', mode='literature', config=None, tools=None):
        self.plan = {'id':'synthetic-plan@1','ownerId':'test-user','fingerprint':'synthetic-plan-sha', 'application':application,'mode':mode,'normalizedGoal':'bounded synthetic method comparison','instructions':['PINNED ORIGINAL PLAN'], 'tools':tools or (['checksum'] if application == 'fixture-checksum' else ['ask_scope','checksum']), 'config':config or {}}
        self.tasks = {}
        self.bindings = {}; self.events = []; self.artifacts = []; self.effects = {}; self.revoked = False; self.cancelled = False
        self.lock = threading.RLock()
        self.revoke_after_compute = False

    def bind_run(self, ctx):
        if ctx.user_id != self.plan['ownerId']: raise PermissionError('Owner mismatch')
        self.bindings.setdefault(ctx.run_id, copy.deepcopy(self.plan))
        self.tasks[ctx.session_id] = {'id':ctx.session_id,'owner_id':ctx.user_id,'plan_id':self.plan['id'],'request_id':'synthetic-request-'+ctx.session_id,'run_id':ctx.run_id,'cancel_requested':False}
        ctx.session_state = ctx.session_state or {}
        ctx.session_state['factory_envelope'] = {'plan_ref':self.plan['id'],'user_id':ctx.user_id,'task_id':ctx.session_id,'request_id':'synthetic-request-'+ctx.session_id}
        return self.resolve_run(ctx)

    def resolve_run(self, ctx):
        plan = self.bindings[ctx.run_id]
        if ctx.user_id != plan['ownerId']: raise PermissionError('Owner mismatch')
        return copy.deepcopy(plan)

    def task(self, identifier, owner=None):
        value = self.tasks.get(identifier) or next(item for item in self.tasks.values() if item['run_id'] == identifier)
        if owner is not None and value['owner_id'] != owner: raise PermissionError('Owner mismatch')
        return {**value,'cancel_requested':self.cancelled}

    def require_plan_execution(self, owner, plan, *, run_context=None):
        # Fixture has a fixed explicit model grant; revoked below is the
        # protected-tool policy tested by the original domain-loop contracts.
        if owner != plan['ownerId']: raise PermissionError('Owner mismatch')

    def authorize_tool(self, ctx, name):
        plan = self.resolve_run(ctx)
        if self.revoke_after_compute and any(e['type'] == 'compute_stopped' for e in self.events): self.revoked = True
        if self.revoked or name not in plan['tools']: raise PermissionError('Current authority denied')

    def effect_reserve(self, run_id, key, request):
        with self.lock:
            old = self.effects.get((run_id,key))
            if old: return copy.deepcopy(old)
            self.effects[(run_id,key)] = {'status':'unknown','request':request,'result':None}
            return {'status':'new','result':None}

    def effect_complete(self, run_id, key, result):
        with self.lock: self.effects[(run_id,key)] = {'status':'done','result':result}

    def event(self, run_id, event_type, message, data):
        with self.lock: self.events.append({'runId':run_id,'type':event_type,'message':message,'data':data})

    def artifact_write(self, run_id, name, content, media_type, metadata):
        self.artifacts.append({'runId':run_id,'name':name,'content':content,'mediaType':media_type,'metadata':metadata})

    def cancellation_requested(self, run_id): return self.cancelled


def attach_fixture_bindings(settings, store, plan):
    selected = []
    for mid, kind, name, content, permissions in SEEDS:
        if kind == 'tool' and content not in plan['tools']: continue
        if kind in {'skill','prompt','knowledge'} and plan['application'] == 'fixture-checksum': continue
        material = {'id':mid,'kind':kind,'name':name,'content':content,'permissions':permissions,'version':1}
        material['sha256'] = digest(material)
        selected.append(material)
    if 'fixture_operation' in plan['tools']:
        material = {'id': 'fixture-operation-tool', 'kind': 'tool', 'name': 'Controlled operation',
            'content': 'fixture_operation', 'permissions': ['fixture:operate'], 'version': 1,
            'runtimeBinding': {'adapterId': 'fixture-operation-v1', 'revision': '1', 'config': {}}}
        material['sha256'] = digest(material)
        selected.append(material)
    plan['materials'] = selected
    bindings = default_bindings(settings, store)
    plan['executionBindings'] = bindings.build(selected, plan['ownerId'])
    store.execution_bindings = bindings


class RuntimeContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(demo=True, runtime_directory=Path(self.directory.name)/'runtime', max_tool_calls=8, experiment_timeout_seconds=5, experiment_output_bytes=65536)
        self.db = SqliteDb(db_file=str(Path(self.directory.name)/'native.sqlite'), id='native-contract-db')

    async def asyncTearDown(self):
        self.db.db_engine.dispose()
        self.directory.cleanup()

    async def run_agent(self, store):
        attach_fixture_bindings(self.settings, store, store.plan)
        agent, registry = build_runtime(self.settings, store, self.db)
        output = await agent.arun('Run the bounded fixture', user_id='test-user', session_id='test-session')
        return agent, output

    async def resume(self, agent, output):
        return await agent.acontinue_run(run_id=output.run_id, session_id='test-session', user_id='test-user', requirements=output.requirements)

    async def test_native_checksum_loop_hashes_actual_input_and_filters_tools(self):
        store = ContractStore(application='fixture-checksum', config={'sample':'actual UTF-8 input 雪'})
        agent, output = await self.run_agent(store)
        self.assertEqual(output.status, RunStatus.completed)
        content = json.loads(output.content)
        self.assertEqual(content['results']['checksum']['sha256'], hashlib.sha256('actual UTF-8 input 雪'.encode()).hexdigest())
        ctx = RunContext(run_id=output.run_id, session_id='test-session', user_id='test-user', session_state={'factory_envelope':{'plan_ref':store.plan['id'],'user_id':'test-user','task_id':'test-session','request_id':'synthetic-request-test-session'}})
        self.assertEqual([tool.name for tool in agent.tools(ctx)], ['checksum'])
        self.assertEqual(len(store.artifacts), 1)
        self.assertEqual(agent.id, 'factory-executor')

    async def test_native_user_input_and_snapshot_survive_catalog_update(self):
        store = ContractStore(config={'askScope':True})
        agent, output = await self.run_agent(store)
        self.assertEqual(output.status, RunStatus.paused)
        output.requirements[0].provide_user_input({'scope':'specific synthetic inversion metric question'})
        store.plan['instructions'] = ['CHANGED CATALOG']
        resumed = await self.resume(agent, output)
        self.assertEqual(resumed.status, RunStatus.completed)
        self.assertEqual(json.loads(resumed.content)['results']['ask_scope']['scope'], 'specific synthetic inversion metric question')
        self.assertIn('PINNED ORIGINAL PLAN', str(resumed.messages[0].content))
        self.assertNotIn('CHANGED CATALOG', str(resumed.messages[0].content))






    async def test_invalid_owner_pre_hook_fails_closed_before_model_tools(self):
        store = ContractStore()
        store.plan['ownerId'] = 'another-user'
        agent, _ = build_runtime(self.settings, store, self.db)
        output = await agent.arun('Denied', user_id='test-user', session_id='denied')
        self.assertEqual(output.status, RunStatus.error)
        self.assertFalse(store.artifacts)
        self.assertFalse(store.effects)



    async def test_native_tool_pre_hook_budget_denial_stops_actual_tool(self):
        store = ContractStore(application='fixture-checksum', tools=['checksum'])
        class DenyBudget:
            calls = 0
            def consume_tool_budget(self, ctx, call_id, name):
                self.calls += 1
                if not call_id:
                    raise AssertionError('Native call ID absent')
                raise PermissionError('Shared durable execution budget exhausted')
        store.delegation = DenyBudget()
        attach_fixture_bindings(self.settings, store, store.plan)
        agent, _ = build_runtime(self.settings, store, self.db)
        await agent.arun('synthetic checksum', user_id='test-user', session_id='synthetic-budget-denial')
        self.assertEqual(store.delegation.calls, 1)
        self.assertEqual(store.artifacts, [])
        self.assertTrue(any(e['type'] == 'protected_denied' for e in store.events))


if __name__ == '__main__': unittest.main()
