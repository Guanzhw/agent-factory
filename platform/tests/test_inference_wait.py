"""Recovery admission denies non-transient failures, drift and stale controls."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agno.exceptions import RunCancelledException, ModelAuthenticationError, ModelProviderError, ModelRateLimitError, ContextWindowExceededError
from fastapi import HTTPException
from agent_factory import inference_wait as wait
from agent_factory.store import digest


class InferenceWaitContractTests(unittest.TestCase):
    def test_only_narrow_transient_provider_failures_qualify(self):
        for status in (408,500,502,503,504):
            self.assertTrue(wait.transient(ModelProviderError('controlled',status_code=status)))
        for error in (ModelAuthenticationError('controlled'), ModelRateLimitError('controlled'),
                ContextWindowExceededError('controlled'), ModelProviderError('quota',status_code=429),
                ModelProviderError('bad request',status_code=400), TimeoutError(), PermissionError(), RuntimeError()):
            self.assertFalse(wait.transient(error),type(error).__name__)

    def fixture(self):
        task={'id':'task','owner_id':'owner','run_id':'native','plan_id':'plan','request_id':'request','cancel_requested':False}
        body={'taskId':'task','ownerId':'owner','nativeRunId':'native','planId':'plan','controlId':'control',
            'deadline':(datetime.now(timezone.utc)+timedelta(seconds=20)).isoformat()}
        row={'body':body,'hash':digest(body),'state':'WAITING'}
        store=SimpleNamespace(sql=lambda *args,**kwargs:[row],task=lambda *args:task,
            plan=lambda *args:{'id':'plan','tools':list(wait.TOOL_NAMES)},has_failures=lambda _:False,
            require_plan_execution=lambda *args,**kwargs:None,authorize_tool=lambda *args:None,
            usage_ledger=SimpleNamespace(inspect=lambda *args:{'scopes':[]}))
        return task,body,row,store

    def test_owner_run_plan_and_integrity_cannot_be_rebound(self):
        for key in ('ownerId','nativeRunId','planId','taskId'):
            task,body,row,store=self.fixture();body[key]='other';row['hash']=digest(body)
            with self.assertRaises(PermissionError):wait.read(store,task['id'])
        task,body,row,store=self.fixture();body['deadline']='changed'
        with self.assertRaises(PermissionError):wait.read(store,task['id'])

    def test_expired_cancelled_and_over_budget_work_cannot_wait_or_resume(self):
        task,body,row,store=self.fixture()
        body['deadline']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with self.assertRaises(HTTPException):wait.current(store,task,body)
        task['cancel_requested']=True
        with self.assertRaises(RunCancelledException):wait.current(store,task)
        task['cancel_requested']=False
        store.usage_ledger.inspect=lambda *args:{'scopes':[{'settledTokens':4,'heldTokens':7,'tokenLimit':10,
            'settledAmountMicros':0,'heldAmountMicros':0,'amountMicrosLimit':0}]}
        with self.assertRaises(HTTPException):wait.current(store,task)

    def test_disabled_money_management_preserves_original_recovery_guards(self):
        from unittest.mock import Mock
        task, body, row, store = self.fixture()
        store.usage_ledger = None
        check = Mock(return_value={})
        store.require_plan_execution = check
        wait.current(store, task, body)
        check.assert_called_once()
        task['cancel_requested'] = True
        with self.assertRaises(RunCancelledException): wait.current(store, task, body)
        task['cancel_requested'] = False
        check.side_effect = PermissionError('Original native grant revoked')
        with self.assertRaises(PermissionError): wait.current(store, task, body)
        check.side_effect = None
        body['deadline'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        with self.assertRaises(HTTPException): wait.current(store, task, body)

    def test_control_result_and_identity_cannot_be_supplied_or_replayed(self):
        task,body,row,store=self.fixture()
        tool={'tool_name':wait.CONTROL_NAME,'tool_call_id':'control','tool_args':{},'external_execution_required':True}
        with patch.object(wait,'observe') as observe:
            self.assertEqual(wait.validate_requirement(store,task,tool)['controlId'],'control')
            observe.assert_called_once_with(store,task,wait.read(store,task['id']))
        for patch_value in ({'tool_call_id':'foreign'},{'tool_args':{'command':'run'}},{'result':'forged'},{'external_execution_required':False}):
            with self.assertRaises(HTTPException):wait.validate_requirement(store,task,{**tool,**patch_value})
        row['state']='RESUMING'
        with self.assertRaises(HTTPException):wait.validate_requirement(store,task,tool)

    @patch.object(wait.os, 'name', 'posix')
    def test_model_failure_before_acknowledged_launch_never_gains_wait_authority(self):
        task,body,row,store=self.fixture()
        store.plan=lambda *args:{'id':'plan','executionBindings':{'tools':[{'adapterId':wait.ADAPTER_ID+'-run','revision':'2'}]}}
        response=SimpleNamespace(session_id='task',user_id='owner')
        with patch.object(wait,'inspect_orx_experiment',return_value={'status':'UNKNOWN','orxRunId':None}), patch.object(wait,'observe') as observe:
            self.assertIsNone(wait.pause(store,response,[],ModelProviderError('controlled',status_code=503)))
            observe.assert_not_called()

    @patch.object(wait.os, 'name', 'posix')
    def test_pause_persists_before_exposing_native_requirement_and_hides_error_text(self):
        import json
        from agno.run.agent import RunOutput
        from unittest.mock import Mock
        task,body,row,store=self.fixture()
        plan={'id':'plan','executionBindings':{'tools':[{'adapterId':wait.ADAPTER_ID+'-run','revision':'2'}]}}
        store.plan=lambda *args:plan
        store.sql=Mock();store.event=Mock()
        experiment={'status':'running','orxRunId':'orx-original','effectFingerprint':'fixed',
            'provenance':{'environment':{'timeoutSeconds':30}}}
        response=RunOutput(run_id='native',session_id='task',user_id='owner')
        messages=[]
        with patch.object(wait,'inspect_orx_experiment',return_value=experiment),patch.object(wait,'read',return_value=None),patch.object(wait,'current'),patch.object(wait,'observe'):
            result=wait.pause(store,response,messages,ModelProviderError('sensitive provider body',status_code=503))
        saved=json.loads(store.sql.call_args.kwargs['body'])
        self.assertEqual(saved['orxRunId'],'orx-original')
        self.assertEqual(response.requirements[-1].tool_execution.tool_call_id,saved['controlId'])
        self.assertEqual(result.tool_executions[-1].tool_call_id,saved['controlId'])
        self.assertTrue(result.tool_executions[-1].external_execution_required)
        self.assertNotIn('sensitive',str(saved)+str(messages))

    @patch.object(wait.os, 'name', 'posix')
    def test_repeated_failure_cannot_extend_deadline_or_exceed_two_waits(self):
        from agno.run.agent import RunOutput
        from unittest.mock import Mock
        import json
        task,body,row,store=self.fixture()
        store.plan=lambda *args:{'id':'plan','executionBindings':{'tools':[{'adapterId':wait.ADAPTER_ID+'-run','revision':'2'}]}}
        store.sql=Mock();store.event=Mock()
        previous={**body,'state':'RECOVERED','failures':1,'createdAt':'original-time'}
        experiment={'status':'running','orxRunId':'orx-original','effectFingerprint':'fixed',
            'provenance':{'environment':{'timeoutSeconds':30}}}
        response=RunOutput(run_id='native',session_id='task',user_id='owner')
        with patch.object(wait,'inspect_orx_experiment',return_value=experiment),patch.object(wait,'read',return_value=previous),patch.object(wait,'current'),patch.object(wait,'observe'):
            wait.pause(store,response,[],ModelProviderError('controlled',status_code=503))
            saved=json.loads(store.sql.call_args.kwargs['body'])
            self.assertEqual(saved['deadline'],previous['deadline']);self.assertEqual(saved['failures'],2)
            previous['failures']=2;store.sql.reset_mock()
            self.assertIsNone(wait.pause(store,response,[],ModelProviderError('controlled',status_code=503)))
            store.sql.assert_not_called()

    def test_receiver_wait_cannot_survive_missing_guard_or_changed_origin_binding(self):
        task,body,row,store=self.fixture()
        remote={'receiptId':'original-receipt','originTaskId':'original-origin'}
        store.plan=lambda *args:{'id':'plan','tools':list(wait.TOOL_NAMES),'remoteHandoff':remote}
        with self.assertRaises(PermissionError):wait.execution_owner(store,task)
        store.execution_guards={'remote_receiver':lambda *args:None}
        body['executionOwner']=wait.execution_owner(store,task)
        wait.current(store,task,body)
        remote['originTaskId']='different-origin'
        # The persisted body is a JSON value, not a mutable alias to a plan.
        body['executionOwner']['receiver']={'receiptId':'original-receipt','originTaskId':'original-origin'}
        with self.assertRaises(PermissionError):wait.current(store,task,body)

    def test_wait_cannot_change_ancestor_root_or_native_owner(self):
        task,body,row,store=self.fixture()
        parent={**task,'id':'parent','run_id':'original-parent-run'}
        store.delegation=SimpleNamespace(_ancestry=lambda _:('parent',[parent]))
        body['executionOwner']=wait.execution_owner(store,task)
        parent['run_id']='replacement-run'
        with self.assertRaises(PermissionError):wait.current(store,task,body)

    def test_current_source_budget_check_retains_unknown_holds_and_checks_money(self):
        from agent_factory.usage_ledger import UsageLedger
        scope={'settledTokens':2,'heldTokens':8,'tokenLimit':10,'settledAmountMicros':2,'heldAmountMicros':8,'amountMicrosLimit':10}
        ledger=SimpleNamespace(inspect=lambda *args:{'scopes':[scope]})
        UsageLedger.require_within_limits(ledger,'owner','task')
        for key in ('settledTokens','settledAmountMicros'):
            scope[key]=3
            with self.assertRaises(HTTPException):UsageLedger.require_within_limits(ledger,'owner','task')
            scope[key]=2
        self.assertEqual(scope['heldTokens'],8);self.assertEqual(scope['heldAmountMicros'],8)

    def test_completed_child_requires_original_external_terminal_and_kernel_stop(self):
        from unittest.mock import Mock
        task,body,row,store=self.fixture()
        store.settings=SimpleNamespace()
        store.effects=Mock()
        identity={'orxRunId':'original','effectFingerprint':'fixed'}
        binding=SimpleNamespace(adapter=SimpleNamespace(observe_existing=lambda:{'run_id':'original'}))
        for status,stopped in [('running',False),('running',True),('done',False)]:
            result={'status':status,'stopEvidence':{'allStopped':stopped},'effectFingerprint':'fixed'}
            with patch.object(wait,'original_experiment_binding',return_value=(task,{},wait.context(task),binding)), \
                    patch.object(wait,'_request',return_value={}),patch.object(wait,'_public_result',return_value=result), \
                    patch.object(wait,'_persist_result') as persist,patch.object(wait,'_observe') as observed:
                with self.assertRaises(PermissionError):wait.observe_work(store,task,identity,require_stopped=True)
                persist.assert_not_called();observed.assert_not_called();store.effects.assert_not_called()

    def test_missing_child_native_ticket_cannot_be_observed(self):
        task,body,row,store=self.fixture()
        child={**task,'id':'child','run_id':'child-native'}
        store.task=lambda task_id,*args:child if task_id=='child' else task
        store.delegation=SimpleNamespace(_ancestry=lambda _:('task',[task]))
        store.native_db=SimpleNamespace(get_job=lambda *args,**kwargs:None)
        body['externalWork']=[{'taskId':'child','nativeRunId':'child-native','planId':'plan'}]
        with patch.object(wait,'current'),patch.object(wait,'observe_work') as observed:
            with self.assertRaises(PermissionError):wait.observe(store,task,body,admitting=True)
            observed.assert_not_called()


    def test_recovered_parent_reconciles_only_original_active_child_without_new_wait(self):
        from unittest.mock import Mock
        task,body,row,store=self.fixture()
        child={**task,'id':'child','run_id':'child-native'}
        store.task=lambda task_id,*args:child if task_id=='child' else task
        store.delegation=SimpleNamespace(_ancestry=lambda owned:('task',[task]) if owned['id']=='child' else ('task',[]))
        body['executionOwner']=wait.execution_owner(store,task)
        identity={'taskId':'child','nativeRunId':'child-native','planId':'plan','orxRunId':'original','effectFingerprint':'fixed'}
        body['externalWork']=[identity];row['state']='RECOVERED';row['hash']=digest(body)
        effect={'effect_key':'child-native:'+wait.LAUNCH_EFFECT_KEY,'status':'UNKNOWN'}
        ticket={'status':'paused'}
        store.effects=lambda _:[effect]
        store.native_db=SimpleNamespace(get_job=lambda *args,**kwargs:ticket)
        store.sql=Mock(return_value=[row])
        with patch.object(wait,'current') as current,patch.object(wait,'observe_work') as observe:
            wait.reconcile_recovered_children(store,task,{**body,'state':'RECOVERED'})
            current.assert_called_once_with(store,child);observe.assert_called_once_with(store,child,identity)
            for state in ('completed','failed','cancelled'):
                observe.reset_mock();ticket['status']=state
                wait.reconcile_recovered_children(store,task,{**body,'state':'RECOVERED'})
                observe.assert_not_called()
            self.assertTrue(all(call.args[0].startswith('SELECT') for call in store.sql.call_args_list))

@unittest.skipUnless(wait.os.name == "posix", "Existing completed-work observation is Linux-only")
class CompletedExperimentReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_wait_checks_evidence_without_cli_or_new_launch(self):
        from contextlib import ExitStack
        from unittest.mock import AsyncMock, Mock
        from agent_factory import orx_experiment_tools as tools
        from agno.run import RunContext
        ctx=RunContext(user_id='owner',session_id='task',run_id='native')
        request={'original':True}
        result={'taskId':'task','planId':'plan','nativeRunId':'native','orxRunId':'orx',
            'effectFingerprint':digest(request),'status':'done','stopEvidence':{'allStopped':True}}
        adapter=SimpleNamespace(ensure_experiment=AsyncMock(side_effect=AssertionError("No namespace wake")),wait_experiment=AsyncMock(),
            observe_existing=Mock(return_value={'run_id':'orx'}),
            read_completed_logs=Mock(return_value=SimpleNamespace(stdout='original',stdout_sha256='log-sha')))
        binding=SimpleNamespace(adapter=adapter,contract_revision='2',ref='ref',version=1,
            fingerprint='pin',revision='2',capabilities=['read'])
        plan={'id':'plan'}
        store=SimpleNamespace(resolve_run=lambda _:plan,effects=lambda _:[{'effect_key':'native:'+tools.LAUNCH_EFFECT_KEY,
            'status':'DONE','result':result}])
        for wrong in (None,'orxRunId','stopEvidence','effectFingerprint'):
            observed={**result}
            if wrong:observed[wrong]={'allStopped':False} if wrong=='stopEvidence' else 'changed'
            with ExitStack() as stack:
                stack.enter_context(patch.object(tools,'_plan_check'))
                stack.enter_context(patch.object(tools,'_record_binding'))
                stack.enter_context(patch.object(tools,'_resolve',new=AsyncMock(return_value=binding)))
                stack.enter_context(patch.object(tools,'original_experiment_binding',return_value=(None,plan,ctx,binding)))
                stack.enter_context(patch.object(tools,'_public_result',return_value=observed))
                stack.enter_context(patch.object(tools,'_request',return_value=request))
                operation=stack.enter_context(patch.object(tools,'_operation',new=AsyncMock()))
                calls=tools.make_orx_experiment_tools(None,store,lambda *args:binding,'2')
                for name in ('orx_experiment_wait','orx_experiment_run','orx_experiment_logs'):
                    if wrong:
                        with self.assertRaises(PermissionError):await calls[name](ctx)
                    else:
                        import json
                        actual=json.loads(await calls[name](ctx))
                        if name=='orx_experiment_logs':self.assertEqual(actual['stdout'],'original')
                        else:self.assertEqual(actual,result)
                operation.assert_not_called();adapter.wait_experiment.assert_not_called();adapter.ensure_experiment.assert_not_called()

    def test_completed_log_read_is_bounded_and_rejects_symlinks_and_running_work(self):
        import tempfile
        from pathlib import Path
        from agent_factory.orx_local import TaskLocalORXAdapter
        from agent_factory.openresearch import OpenResearchError
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);logs=root/'orx-store'/'run-logs';logs.mkdir(parents=True)
            path=logs/'run.log';path.write_bytes(b'original')
            receipt={'state':'done','run_id':'run','stop_evidence':{'allStopped':True}}
            adapter=SimpleNamespace(scope=root,max_output_bytes=8,observe_existing=lambda:receipt,_id=lambda value:value)
            self.assertEqual(TaskLocalORXAdapter.read_completed_logs(adapter).stdout,'original')
            path.write_bytes(b'oversized')
            with self.assertRaises(OpenResearchError):TaskLocalORXAdapter.read_completed_logs(adapter)
            path.unlink();path.symlink_to(root/'other')
            with self.assertRaises(OpenResearchError):TaskLocalORXAdapter.read_completed_logs(adapter)
            path.unlink()
            import os
            os.mkfifo(path)
            with self.assertRaises(OpenResearchError):TaskLocalORXAdapter.read_completed_logs(adapter)
            path.unlink();path.mkdir()
            with self.assertRaises((OpenResearchError, IsADirectoryError)):TaskLocalORXAdapter.read_completed_logs(adapter)
            receipt['stop_evidence']['allStopped']=False
            with self.assertRaises(OpenResearchError):TaskLocalORXAdapter.read_completed_logs(adapter)

    def _assert_completed_logs_require_flag(self, flag):
        import os
        import tempfile
        from pathlib import Path
        from agent_factory.orx_local import TaskLocalORXAdapter
        from agent_factory.openresearch import OpenResearchError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logs = root / 'orx-store' / 'run-logs'
            logs.mkdir(parents=True)
            (logs / 'run.log').write_bytes(b'original')
            adapter = SimpleNamespace(scope=root, max_output_bytes=8, _id=lambda value: value,
                observe_existing=lambda: {'state': 'done', 'run_id': 'run', 'stop_evidence': {'allStopped': True}})
            for value in (None, 0, 'unsupported'):
                with self.subTest(flag=flag, value=value), patch.object(os, flag, value, create=True), patch.object(os, 'open') as opener:
                    if value is None:
                        delattr(os, flag)  # Exercise genuinely absent platform capability.
                    with self.assertRaises(OpenResearchError) as raised:
                        TaskLocalORXAdapter.read_completed_logs(adapter)
                    self.assertEqual(raised.exception.code, 'UNSUPPORTED_PLATFORM')
                    opener.assert_not_called()

    def test_completed_log_read_fails_closed_without_nofollow(self):
        self._assert_completed_logs_require_flag('O_NOFOLLOW')

    def test_completed_log_read_fails_closed_without_nonblock(self):
        self._assert_completed_logs_require_flag('O_NONBLOCK')


class RecoveredChildCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_child_and_origin_cancellation_do_not_become_parent_failure(self):
        from contextlib import nullcontext
        from unittest.mock import Mock
        from agent_factory.lifecycle_observer import FactoryLifecycleObserver
        from agent_factory.remote_handoff import HandoffCancellationRequested
        root={'id':'root','owner_id':'owner','cancel_requested':False}
        store=SimpleNamespace(task=lambda *args:root,event=Mock(),
            delegation=SimpleNamespace(_root_lock=lambda _:nullcontext()))
        observer=FactoryLifecycleObserver(store,None,None,lambda:None)
        observer._group=Mock(return_value=([root],[]));observer._binding=Mock(return_value={})
        observer._reason=Mock(return_value=None);observer._facts=Mock(return_value={'stopped':False})
        for error in (RunCancelledException('child cancelled'),HandoffCancellationRequested('owner','root','manifest')):
            with patch.object(wait,'read',return_value={'state':'RECOVERED','controlId':'original'}), \
                    patch.object(wait,'reconcile_recovered_children',side_effect=error):
                await observer.observe_root('root')
            store.event.assert_not_called()
