"""Final smoke orchestration over real durable synthetic history, mock HTTP only."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
from agent_factory.go_live import GoLiveCampaign
from agent_factory.go_single_smoke import GoSingleSmokeCampaign
from agent_factory.opencode_go import open_go_client

spec = importlib.util.spec_from_file_location('final_runner', Path(__file__).resolve().parents[2] / 'scripts/run_go_final_smoke.py')
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@unittest.skipUnless(os.name == 'posix', 'Private campaign requires POSIX')
class FinalRunnerTests(unittest.TestCase):
    def fixture(self, root):
        history = Path(root) / 'old.sqlite'
        old = GoLiveCampaign.create(history, campaign_id='old', owner_id='alice', confirmation_id='yes', expires_at=time.time()+600)
        def body(model):
            return {'model': model, 'stream': True, 'messages': [{'role':'user','content':'Write add.'}], 'max_tokens':32, 'stream_options':{'include_usage':True}}
        old.authorize('old-session', 'deepseek-v4-flash', owner_id='alice')
        old.finish(old.begin('old-session', 'deepseek-v4-flash', body('deepseek-v4-flash')), error_code='UNKNOWN')
        second = GoSingleSmokeCampaign.create(str(history)+'.budget.sqlite', history_path=history, campaign_id='second', owner_id='alice', confirmation_id='yes', expires_at=time.time()+600)
        second.authorize('second-session', 'deepseek-flash', owner_id='alice')
        second.finish(second.begin('second-session','deepseek-flash',body('deepseek-flash')),error_code='UNKNOWN')
        return argparse.Namespace(history_path=str(history), owner_id='alice', confirmation_id='final-yes', evidence_directory=str(Path(root)/'evidence'), execute_authorized_live=True, use_balance_off=True, auto_reload_off=True, synthetic_only=True, confirm_one_attempt=True, exact_model='deepseek-flash')

    def test_success_or_auth_or_usage_unknown_each_sends_once_never_reopens(self):
        for status, usage in ((200,True),(401,True),(200,False)):
            with self.subTest(status=status,usage=usage), tempfile.TemporaryDirectory() as root:
                args=self.fixture(root)
                calls=[]
                def handler(request):
                    calls.append(request)
                    payload=json.loads(request.content)
                    self.assertEqual(str(request.url),'https://opencode.ai/zen/go/v1/chat/completions')
                    self.assertEqual(payload['model'],'deepseek-flash')
                    self.assertEqual(payload['max_tokens'],64)
                    self.assertNotIn('tools',payload)
                    self.assertEqual(request.headers['x-opencode-session'],'second-session')
                    event={'model':'deepseek-flash','choices':[{'index':0,'delta':{'content':'unpersisted-fixture-content'},'finish_reason':'stop'}]}
                    if usage: event['usage']={'prompt_tokens':9,'completion_tokens':3,'total_tokens':12}
                    return httpx.Response(status, headers={'content-type':'text/event-stream'}, text='data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n')
                transport=httpx.MockTransport(handler)
                def client(**kwargs):
                    self.assertEqual(kwargs['timeout'],60)
                    self.assertIsNone(kwargs['transport'])
                    return open_go_client(timeout=60,transport=transport)
                with patch.object(runner,'credential',return_value='synthetic-only-credential') as key, patch('agent_factory.opencode_go.open_go_client',side_effect=client):
                    result=runner.run(args)
                    self.assertEqual(len(calls),1)
                    self.assertEqual(key.call_count,1)
                    self.assertEqual(result['campaign']['budgetCounts'],{'deepseek':3,'gpt-6-luna':0})
                    self.assertEqual([t['state'] for t in result['campaign']['tickets'][:2]],['UNKNOWN','UNKNOWN'])
                    self.assertEqual(result['status'],'completed' if status==200 and usage else 'stopped')
                    self.assertEqual(result['finishReason'],'stop' if status==200 else None)
                    serialized=json.dumps(result)
                    self.assertNotIn('unpersisted-fixture-content',serialized)
                    self.assertNotIn('synthetic-only-credential',serialized)
                    with self.assertRaises(Exception): runner.run(args)
                    self.assertEqual(len(calls),1)
                    self.assertEqual(key.call_count,1)

    def test_missing_confirmation_never_reads_credential_or_authorizes(self):
        with tempfile.TemporaryDirectory() as root:
            args=self.fixture(root)
            args.confirm_one_attempt=False
            with patch.object(runner,'credential',side_effect=AssertionError) as key, patch.object(runner.GoFinalSmokeCampaign,'authorize_final') as gate:
                with self.assertRaises(ValueError): runner.run(args)
                key.assert_not_called()
                gate.assert_not_called()
