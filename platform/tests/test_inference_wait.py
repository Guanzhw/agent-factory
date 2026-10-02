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

    def test_control_result_and_identity_cannot_be_supplied_or_replayed(self):
        task,body,row,store=self.fixture()
        tool={'tool_name':wait.CONTROL_NAME,'tool_call_id':'control','tool_args':{},'external_execution_required':True}
        self.assertEqual(wait.validate_requirement(store,task,tool)['controlId'],'control')
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
