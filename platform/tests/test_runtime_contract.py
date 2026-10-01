"""Actual native Agent tool/HITL loop and bounded compute contract tests."""
import asyncio
import copy
import ctypes
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import signal
import subprocess
import sys
from types import SimpleNamespace
import unittest
from uuid import uuid4

from agno.db.sqlite import SqliteDb
from agno.run import RunContext
from agno.run.base import RunStatus
from agent_factory.runtime import build_runtime
from agent_factory.tools import _WindowsJob


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
    def __init__(self, application='research', mode='literature', config=None, tools=None):
        self.plan = {'id':'synthetic-plan@1','ownerId':'test-user','fingerprint':'synthetic-plan-sha', 'application':application,'mode':mode,'normalizedGoal':'bounded synthetic method comparison','instructions':['PINNED ORIGINAL PLAN'], 'tools':tools or (['checksum'] if application == 'checksum' else ['literature_search','run_experiment','ask_scope']), 'config':config or {}}
        self.bindings = {}; self.events = []; self.artifacts = []; self.effects = {}; self.revoked = False; self.cancelled = False
        self.lock = threading.RLock()
        self.revoke_after_compute = False

    def bind_run(self, ctx):
        if ctx.user_id != self.plan['ownerId']: raise PermissionError('Owner mismatch')
        self.bindings.setdefault(ctx.run_id, copy.deepcopy(self.plan))
        return self.resolve_run(ctx)

    def resolve_run(self, ctx):
        plan = self.bindings[ctx.run_id]
        if ctx.user_id != plan['ownerId']: raise PermissionError('Owner mismatch')
        return copy.deepcopy(plan)

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


class RuntimeContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(runtime_directory=Path(self.directory.name)/'runtime', max_tool_calls=8, experiment_timeout_seconds=5, experiment_output_bytes=65536)
        self.db = SqliteDb(db_file=str(Path(self.directory.name)/'native.sqlite'), id='native-contract-db')

    async def asyncTearDown(self):
        self.db.db_engine.dispose()
        self.directory.cleanup()

    async def run_agent(self, store):
        agent, registry = build_runtime(self.settings, store, self.db)
        output = await agent.arun('Run the bounded fixture', user_id='test-user', session_id='test-session')
        return agent, output

    async def resume(self, agent, output):
        return await agent.acontinue_run(run_id=output.run_id, session_id='test-session', user_id='test-user', requirements=output.requirements)

    async def test_native_checksum_loop_hashes_actual_input_and_filters_tools(self):
        store = ContractStore(application='checksum', config={'sample':'actual UTF-8 input 雪'})
        agent, output = await self.run_agent(store)
        self.assertEqual(output.status, RunStatus.completed)
        content = json.loads(output.content)
        self.assertEqual(content['results']['checksum']['sha256'], hashlib.sha256('actual UTF-8 input 雪'.encode()).hexdigest())
        ctx = RunContext(run_id=output.run_id, session_id='test-session', user_id='test-user')
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
        self.assertEqual(json.loads(resumed.content)['results']['literature_search']['query'], 'specific synthetic inversion metric question')
        self.assertIn('PINNED ORIGINAL PLAN', str(resumed.messages[0].content))
        self.assertNotIn('CHANGED CATALOG', str(resumed.messages[0].content))

    async def test_native_confirmation_executes_real_bounded_synthetic_process(self):
        store = ContractStore(mode='experiment')
        agent, output = await self.run_agent(store)
        self.assertEqual(output.status, RunStatus.paused)
        self.assertFalse(store.effects)
        output.requirements[0].confirm()
        resumed = await self.resume(agent, output)
        self.assertEqual(resumed.status, RunStatus.completed)
        metric = json.loads(resumed.content)['results']['run_experiment']
        self.assertGreater(metric['baseline'], metric['candidate'])
        self.assertEqual(metric['evidenceKind'], 'synthetic')
        self.assertEqual(metric['evaluatorVersion'], '1')
        stopped = next(e for e in store.events if e['type'] == 'compute_stopped')
        self.assertTrue(stopped['data']['cleanupComplete'])
        self.assertEqual(stopped['data']['returnCode'], 0)
        self.assertFalse(process_running(stopped['data']['pid']))
        self.assertEqual(len(store.effects), 1)

    async def test_revocation_before_approved_tool_never_starts_compute(self):
        store = ContractStore(mode='experiment')
        agent, output = await self.run_agent(store)
        output.requirements[0].confirm(); store.revoked = True
        resumed = await self.resume(agent, output)
        self.assertEqual(json.loads(resumed.content)['status'], 'failed')
        self.assertFalse(store.effects)
        self.assertFalse(any(e['type'] == 'compute_started' for e in store.events))
        self.assertTrue(any(e['type'] == 'protected_denied' for e in store.events))

    async def test_unknown_effect_refuses_native_approved_retry(self):
        store = ContractStore(mode='experiment')
        agent, output = await self.run_agent(store)
        store.effects[(output.run_id,'experiment:bounded-sort-v1')] = {'status':'unknown','result':None}
        output.requirements[0].confirm()
        resumed = await self.resume(agent, output)
        self.assertEqual(json.loads(resumed.content)['status'], 'blocked-unknown')
        self.assertFalse(any(e['type'] == 'compute_started' for e in store.events))
        self.assertTrue(any(e['type'] == 'effect_unknown' for e in store.events))

    async def test_postcompute_revocation_preserves_actual_effect_without_publication(self):
        store = ContractStore(mode='experiment'); store.revoke_after_compute = True
        agent, output = await self.run_agent(store)
        output.requirements[0].confirm()
        resumed = await self.resume(agent, output)
        self.assertEqual(json.loads(resumed.content)['status'], 'failed')
        effect = store.effects[(output.run_id,'experiment:bounded-sort-v1')]
        self.assertEqual(effect['status'], 'done')
        self.assertIn('baseline', effect['result'])
        self.assertFalse(any(a['name'] == 'synthetic-experiment.json' for a in store.artifacts))
        self.assertFalse(any(e['type'] == 'effect_unknown' for e in store.events))

    async def test_running_cancel_cleans_own_compute_and_settles_known_cancellation(self):
        store = ContractStore(mode='experiment', config={'experimentDurationSeconds':3})
        agent, output = await self.run_agent(store)
        output.requirements[0].confirm()
        pending = asyncio.create_task(self.resume(agent, output))
        deadline = asyncio.get_running_loop().time() + 5
        while not any(e['type'] == 'compute_started' for e in store.events):
            if pending.done(): await pending; self.fail('No compute started')
            if asyncio.get_running_loop().time() > deadline: self.fail('Compute did not start in time')
            await asyncio.sleep(.02)
        store.cancelled = True
        resumed = await asyncio.wait_for(pending, timeout=5)
        self.assertEqual(resumed.status, RunStatus.cancelled)
        stopped = next(e for e in store.events if e['type'] == 'compute_stopped')
        self.assertTrue(stopped['data']['cleanupComplete'])
        self.assertIsNotNone(stopped['data']['returnCode'])
        self.assertFalse(process_running(stopped['data']['pid']))
        self.assertEqual(store.effects[(output.run_id,'experiment:bounded-sort-v1')]['status'], 'done')
        self.assertEqual(store.effects[(output.run_id,'experiment:bounded-sort-v1')]['result']['cancelled'], True)
        self.assertFalse(any(e['type'] == 'effect_unknown' for e in store.events))

    async def test_invalid_owner_pre_hook_fails_closed_before_model_tools(self):
        store = ContractStore()
        store.plan['ownerId'] = 'another-user'
        agent, _ = build_runtime(self.settings, store, self.db)
        output = await agent.arun('Denied', user_id='test-user', session_id='denied')
        self.assertEqual(output.status, RunStatus.error)
        self.assertFalse(store.artifacts)
        self.assertFalse(store.effects)

    async def test_executor_task_cancel_waits_for_compute_cleanup(self):
        store = ContractStore(mode='experiment', config={'experimentDurationSeconds':3})
        agent, output = await self.run_agent(store)
        output.requirements[0].confirm()
        pending = asyncio.create_task(self.resume(agent, output))
        deadline = asyncio.get_running_loop().time() + 5
        while not any(e['type'] == 'compute_started' for e in store.events):
            if pending.done(): await pending; self.fail('No compute started')
            if asyncio.get_running_loop().time() > deadline: self.fail('Compute did not start in time')
            await asyncio.sleep(.02)
        pending.cancel()
        try: await asyncio.wait_for(pending, timeout=5)
        except asyncio.CancelledError: pass
        stopped = next(e for e in store.events if e['type'] == 'compute_stopped')
        self.assertTrue(stopped['data']['cleanupComplete'])
        self.assertFalse(process_running(stopped['data']['pid']))
        self.assertEqual(store.effects[(output.run_id,'experiment:bounded-sort-v1')]['status'], 'done')
        self.assertTrue(store.effects[(output.run_id,'experiment:bounded-sort-v1')]['result']['cleanupComplete'])

    async def test_containment_closes_spawned_descendant(self):
        # The production program cannot spawn descendants. This separate
        # fixed test program proves its OS containment also handles them.
        program = "import subprocess,sys,time; time.sleep(.15); child=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(30)']); print(child.pid,flush=True); time.sleep(30)"
        proc = subprocess.Popen([sys.executable,'-I','-c',program], stdout=subprocess.PIPE, text=True,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, start_new_session=os.name != 'nt')
        job = None
        try:
            if os.name == 'nt': job = _WindowsJob(proc.pid)
            child_pid = int(await asyncio.wait_for(asyncio.to_thread(proc.stdout.readline), timeout=5))
            self.assertTrue(process_running(child_pid))
            if job: job.close()
            else: os.killpg(proc.pid, signal.SIGKILL)
            await asyncio.to_thread(proc.wait, 5)
            deadline = asyncio.get_running_loop().time() + 5
            while process_running(child_pid) and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(.02)
            self.assertFalse(process_running(child_pid))
            self.assertFalse(process_running(proc.pid))
        finally:
            if job: job.close()
            if proc.poll() is None:
                if os.name == 'nt': proc.kill()
                else:
                    try: os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                proc.wait(5)
            proc.stdout.close()

    async def test_native_tool_pre_hook_budget_denial_stops_actual_tool(self):
        store = ContractStore(application='checksum', tools=['checksum'])
        class DenyBudget:
            calls = 0
            def consume_tool_budget(self, ctx, call_id, name):
                self.calls += 1
                if not call_id:
                    raise AssertionError('Native call ID absent')
                raise PermissionError('Shared durable execution budget exhausted')
        store.delegation = DenyBudget()
        agent, _ = build_runtime(self.settings, store, self.db)
        await agent.arun('synthetic checksum', user_id='test-user', session_id='synthetic-budget-denial')
        self.assertEqual(store.delegation.calls, 1)
        self.assertEqual(store.artifacts, [])
        self.assertTrue(any(e['type'] == 'protected_denied' for e in store.events))


if __name__ == '__main__': unittest.main()


@unittest.skipUnless(os.environ.get('FACTORY_TEST_DATABASE_URL'), 'An isolated PostgreSQL test database is required')
class FullStoreRuntimeContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_store_running_cancel_settles_cancelled_effect(self):
        from agno.db.postgres import PostgresDb
        from agent_factory.auth import AuthService
        from agent_factory.config import Settings
        from agent_factory.store import Store
        directory = tempfile.TemporaryDirectory()
        from pg_fixture import IsolatedPostgres
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        settings = Settings(db_url=database.url, workspace=Path(directory.name), max_user_tasks=20, max_total_tasks=50)
        native_db = PostgresDb(db_url=settings.db_url, id='full-store-native-contract')
        store = Store(settings.db_url, settings)
        auth = AuthService(settings, native_db); auth.initialize_demo(); store.auth = auth
        plan = {'id':str(uuid4()), 'ownerId':'alice','fingerprint':'synthetic-full-store-plan','application':'research','mode':'experiment','normalizedGoal':'bounded synthetic method comparison','instructions':['PINNED FULL STORE PLAN'],'tools':['literature_search','run_experiment'],'config':{'experimentDurationSeconds':3},'materialRefs':[],'capabilities':['run'],'status':'ready'}
        store.save_plan(plan)
        task, _ = store.reserve_task(plan, str(uuid4()))
        agent, _ = build_runtime(settings, store, native_db)
        pending = None
        try:
            output = await agent.arun('Persisted plan', user_id='alice', session_id=task['id'], session_state={'factory_envelope':{'plan_ref':plan['id']}})
            self.assertEqual(output.status, RunStatus.paused)
            output.requirements[0].confirm()
            pending = asyncio.create_task(agent.acontinue_run(run_id=output.run_id, session_id=task['id'], user_id='alice', requirements=output.requirements))
            deadline = asyncio.get_running_loop().time() + 8
            while not any(e['type'] == 'compute_started' for e in store.events(task['id'])):
                if pending.done(): await pending; self.fail('No compute started')
                if asyncio.get_running_loop().time() > deadline: self.fail('Compute did not start in time')
                await asyncio.sleep(.03)
            store.request_cancel(task['id'])
            resumed = await asyncio.wait_for(pending, timeout=8)
            self.assertEqual(resumed.status, RunStatus.cancelled)
            effects = store.effects(task['id'])
            self.assertEqual(len(effects), 1)
            self.assertEqual(effects[0]['status'], 'CANCELLED')
            self.assertTrue(effects[0]['result']['cleanupComplete'])
            self.assertTrue(effects[0]['result']['cancelled'])
            stopped = next(e for e in store.events(task['id']) if e['type'] == 'compute_stopped')
            self.assertFalse(process_running(stopped['data']['pid']))
            self.assertFalse(any(e['type'] == 'effect_unknown' for e in store.events(task['id'])))
        finally:
            if pending and not pending.done():
                store.request_cancel(task['id'])
                try: await asyncio.wait_for(pending, 8)
                except BaseException: pass
            store.observed(store.task(task['id']), 'cancelled' if store.cancellation_requested(task['id']) else 'failed', True)
            store.engine.dispose(); native_db.db_engine.dispose(); directory.cleanup(); database.__exit__(None, None, None)
