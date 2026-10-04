"""Project smoke invokes each native protocol once with synthetic durable history."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from agent_factory.opencode_go import open_go_client
import test_go_project_campaign as fixture

spec=importlib.util.spec_from_file_location('project_smoke',Path(__file__).resolve().parents[2]/'scripts/run_go_project_smoke.py')
assert spec and spec.loader
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@unittest.skipUnless(os.name=='posix','Private synthetic history')
class ProjectSmokeRunnerTests(unittest.TestCase):
    def test_each_protocol_single_request_durable_usage_and_no_replay(self):
        helper=fixture.ProjectCampaignTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        helper.migrate()
        calls=[]
        def handler(request):
            body=json.loads(request.content)
            calls.append(body['model'])
            self.assertNotIn('tools',body)
            self.assertEqual(body['model'],'gpt-6-luna' if str(request.url).endswith('/responses') else 'deepseek-flash')
            if body['model']=='gpt-6-luna':
                value={'type':'response.completed','response':{'model':body['model'],'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'private-generated-text'}]}],'usage':{'input_tokens':7,'output_tokens':3,'total_tokens':10}}}
                data='data: '+json.dumps(value)+'\n\n'
            else:
                value={'model':body['model'],'choices':[{'index':0,'delta':{'content':'private-generated-text'},'finish_reason':'stop'}],'usage':{'prompt_tokens':7,'completion_tokens':3,'total_tokens':10}}
                data='data: '+json.dumps(value)+'\n\ndata: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},text=data)
        transport=httpx.MockTransport(handler)
        def client(**kwargs):
            self.assertEqual(kwargs['timeout'],60)
            self.assertIsNone(kwargs['transport'])
            return open_go_client(timeout=60,transport=transport)
        for model in ('deepseek-flash','gpt-6-luna'):
            args=argparse.Namespace(model=model,budget_path=str(helper.path),owner_id='alice',output_tokens=512,evidence_directory=str(helper.path.parent/model))
            with patch.object(runner,'credential',return_value='synthetic-placeholder') as credential,patch('agent_factory.opencode_go.open_go_client',side_effect=client):
                result=runner.run(args)
                self.assertEqual(result['status'],'completed')
                self.assertEqual(result['campaign']['tickets'][-1]['total_tokens'],10)
                self.assertNotIn('private-generated-text',json.dumps(result))
                credential.assert_called_once()
                with self.assertRaises(FileExistsError):runner.run(args)
                credential.assert_called_once()
        self.assertEqual(calls,['deepseek-flash','gpt-6-luna'])
