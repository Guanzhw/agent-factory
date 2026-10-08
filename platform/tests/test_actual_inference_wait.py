"""Controlled inference outage plus actual reviewed Linux ORX/native PostgreSQL."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import socket
import httpx
import sys
import tempfile
import time
import unittest
from uuid import uuid4

from agno.exceptions import ModelProviderError
from fastapi.testclient import TestClient
from pg_fixture import IsolatedPostgres
from agent_factory.main import create_app
from agent_factory.local_orx_profile import local_profile_settings, publish_local_orx_application, REGISTRATION_REF
from agent_factory.orx_local import TaskLocalORXProvider
from agent_factory.orx_experiment_tools import LocalORXWorkflowModel, MODEL_ADAPTER_ID, TOOL_NAMES
from agent_factory.inference_wait import CONTROL_NAME


@unittest.skipUnless(os.getenv('FACTORY_ORX_LINUX_CONTAINER') == '1' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires explicitly approved Linux ORX/container and isolated PostgreSQL')
class InferenceWaitFixture(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.directory = tempfile.TemporaryDirectory(prefix='factory-at10-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.addCleanup(self.clean_containers)
        self.provider = TaskLocalORXProvider(binary=Path(os.environ['FACTORY_ORX_BINARY']),
            source_archive=Path(os.environ['FACTORY_ORX_SOURCE_ARCHIVE']), git_binary=Path(os.environ['FACTORY_ORX_GIT_BINARY']),
            python_binary=Path(sys._base_executable))
        self.settings = local_profile_settings(db_url=self.database.url, workspace=self.root, provider=self.provider, contract_revision='2')
        self.settings.queue_poll=.1
        self.gate={'failures':1, 'actualFailures':0}
        self.start_app()
        auth=self.state['auth'];auth.authorization.unassign('bob','factory-user');auth.authorization.assign('bob','factory-manager')
        self.application=publish_local_orx_application(self.state,author='manager',reviewer='bob',contract_revision='2')
        self.pins={name:self.state['connections'].bind('alice',REGISTRATION_REF,name,capabilities=[cap])
            for name,cap in (('localExperimentRead','research:read'),('localExperimentRun','compute:local'))}

    def start_app(self):
        self.app=create_app(self.settings);self.state=self.app.app.state.factory;self.store=self.state['store']
        self.addCleanup(self.store.engine.dispose);self.addCleanup(self.store.native_db.db_engine.dispose)
        gate=self.gate
        class FaultModel(LocalORXWorkflowModel):
            def _response(self,messages):
                launched=any(m.role=='tool' and m.tool_name==TOOL_NAMES[1] and 'orxRunId' in str(m.content) for m in messages)
                if launched and gate['failures']:
                    gate['failures']-=1;gate['actualFailures']+=1
                    raise ModelProviderError('Controlled temporary inference outage; no provider request',status_code=503)
                return super()._response(messages)
        bindings=self.state['execution_bindings'];key=('model',MODEL_ADAPTER_ID,'1')
        bindings._adapters[key]=replace(bindings._adapters[key],factory=lambda _:FaultModel())
        self.client=TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)

    def clean_containers(self):
        for marker in self.root.rglob('factory-linux-container.json'):
            saved=json.loads(marker.read_text());cid=saved['containerId']
            obj=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
            self.assertEqual(obj['Config']['Labels']['agent-factory.orx-spec'],saved['specSha256'])
            self.assertIn(str(marker.parent),[m['Source'] for m in obj['Mounts'] if m['RW']])
            if obj['State']['Running']:subprocess.run(['docker','kill',cid],check=True,capture_output=True)
            subprocess.run(['docker','rm',cid],check=True,capture_output=True)

    def request(self,method,path,body=None,owner='alice'):
        result=self.client.request(method,'/api/factory'+path,json=body,
            headers={'Authorization':'Bearer '+self.state['auth']._issue_native_token(owner)})
        self.assertTrue(result.is_success,result.text)
        return result.json()

    def wait(self,predicate,seconds=80):
        end=time.monotonic()+seconds
        previous=None
        while time.monotonic()<end:
            detail=self.request('GET','/jobs/'+self.task)
            observed=(detail['job']['status'],detail['snapshot'].get('status'),detail['snapshot'].get('queue',{}).get('status'),[(r.get('tool_execution',{}).get('tool_name'),r.get('tool_execution',{}).get('external_execution_required')) for r in detail['snapshot'].get('requirements',[])],detail['job'].get('approvalDetail',{}).get('toolName'))
            if observed!=previous:print('AT10 state',observed,flush=True);previous=observed
            if predicate(detail):return detail
            if detail['job']['status'] in {'failed','canceled'}:break
            time.sleep(.1)
        self.fail(str({'status':detail['job']['status'],'gate':self.gate,'native':detail['snapshot'].get('status'),'events':[(e['type'],e['data'].get('error'),e['data'].get('reason'),e['data'].get('code')) for e in self.store.events(self.task)]}))

    def launch(self):
        def post(path,body,owner='alice'):return self.request('POST',path,{'requestId':str(uuid4()),**body},owner)
        proposal=post('/compositions/proposals',{'goal':'AT10 controlled inference outage and real owned ORX experiment','mode':'cancellable',
            'applicationRef':{k:self.application[k] for k in ('id','version','sha256')},
            'connectionRefs':{n:p['ref'] for n,p in self.pins.items()}})
        plan=post('/compositions/proposals/'+proposal['id']+'/accept',{})
        review=post('/plan-reviews',{'planId':plan['id']});post('/plan-reviews/'+review['id']+'/decision',{'approved':True},'manager')
        job=post('/instances',{'planId':plan['id']});self.task=job['id']
        d=self.wait(lambda d:d['job']['status']=='waiting_approval')
        self.approve(d)
        return self.wait(lambda d:d['job'].get('approvalDetail',{}).get('toolName')==CONTROL_NAME)

    def approve(self,d):
        a=d['job']['approvalDetail']
        return self.request('POST','/jobs/'+self.task+'/approve',{'requirementId':a['id'],'version':a['version'],'approved':True})

    def record_evidence(self,data):
        directory=os.getenv('FACTORY_AT10_EVIDENCE_DIR')
        if directory:
            target=Path(directory);target.mkdir(parents=True,exist_ok=True)
            (target/(type(self).__name__+'-'+self._testMethodName+'.json')).write_text(json.dumps(data,indent=2)+'\n')

    def after_pause(self,paused):
        pass


class ActualInferenceWaitTests(InferenceWaitFixture):
    def test_transient_fault_keeps_real_work_and_resumes_same_native_run(self):
        paused=self.launch()
        self.assertEqual(paused['job']['status'],'waiting_approval',paused['job'])
        original=self.store.task(self.task)['run_id'];orx=paused['orxExperiment']['orxRunId']
        self.assertEqual(paused['snapshot']['queue']['status'],'paused')
        self.assertFalse(self.store.task(self.task)['cancel_requested'])
        self.assertFalse(paused['orxExperiment']['stopEvidence']['allStopped'])
        self.assertEqual(self.gate['actualFailures'],1)
        self.after_pause(paused)
        observed=self.wait(lambda d:d['orxExperiment']['status']=='done',seconds=25)
        self.assertEqual(observed['orxExperiment']['orxRunId'],orx)
        self.assertFalse(self.store.task(self.task)['cancel_requested'])
        self.approve(observed)
        self.approve(observed)  # Same durable decision cannot enqueue a second continuation.
        done=self.wait(lambda d:d['job']['status'] in {'completed','failed','canceled'})
        self.assertEqual(done['job']['status'],'completed',{'job':done['job'],'events':done['events'][-5:]})
        self.assertEqual(self.store.task(self.task)['run_id'],original)
        self.assertEqual(done['orxExperiment']['orxRunId'],orx)
        self.assertEqual(done['orxExperiment']['status'],'done')
        self.assertTrue(done['orxExperiment']['stopEvidence']['allStopped'])
        self.assertEqual(len([e for e in self.store.events(self.task) if e['type']=='orx_experiment_launch_intent' and e['data']['newIntent']]),1)
        self.record_evidence({'controlledInferenceFailures':self.gate['actualFailures'],'realORX':True,'nativeRunId':original,'orxRunId':orx,
            'nativeStatus':done['snapshot']['queue']['status'],'launchCount':1,'stopEvidence':done['orxExperiment']['stopEvidence'],
            'inferenceWait':done['inferenceWait'],'processRestart':isinstance(self,ActualInferenceRestartTests)})


class ActualInferenceRestartTests(ActualInferenceWaitTests):
    def start_app(self):
        # Parent is a read/control fixture with no lifespan/worker. The actual
        # native queue runs only in the separately owned server process.
        self.app=create_app(self.settings);self.state=self.app.app.state.factory;self.store=self.state['store']
        self.addCleanup(self.store.engine.dispose);self.addCleanup(self.store.native_db.db_engine.dispose)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.gate_path=self.root/'inference-fault.json';self.gate_path.write_text(json.dumps(self.gate))
        self.log=(self.root/'worker.log').open('w');self.addCleanup(self.log.close)
        self.client=httpx.Client(base_url=f'http://127.0.0.1:{self.port}',timeout=30)
        self.addCleanup(self.client.close)
        self.worker=None
        self.addCleanup(self.stop_worker)
        self.boot_worker()

    def boot_worker(self):
        env={**os.environ,'AT10_FIXTURE_DATABASE_URL':self.database.url,'AT10_FIXTURE_WORKSPACE':str(self.root),
            'AT10_FIXTURE_PORT':str(self.port),'AT10_FIXTURE_JWT_KEY':self.settings.jwt_key}
        self.worker=subprocess.Popen([sys.executable,str(Path(__file__).with_name('inference_wait_worker.py'))],
            env=env,stdout=self.log,stderr=self.log)
        end=time.monotonic()+30
        while time.monotonic()<end:
            self.assertIsNone(self.worker.poll(),'Owned fixture service exited')
            try:
                if self.client.get('/api/health').is_success:return
            except httpx.TransportError:pass
            time.sleep(.1)
        self.fail('Owned fixture service startup timed out')

    def stop_worker(self):
        if self.worker and self.worker.poll() is None:
            self.worker.terminate()
            try:self.worker.wait(timeout=10)
            except subprocess.TimeoutExpired:self.worker.kill();self.worker.wait(timeout=10)

    def request(self,*args,**kwargs):
        result=super().request(*args,**kwargs)
        self.gate=json.loads(self.gate_path.read_text())
        return result

    def after_pause(self,paused):
        old_run=self.store.task(self.task)['run_id'];old_orx=paused['orxExperiment']['orxRunId']
        self.worker.kill();self.worker.wait(timeout=10)
        self.boot_worker()
        restored=self.wait(lambda d:d['job'].get('approvalDetail',{}).get('toolName')==CONTROL_NAME,seconds=15)
        self.assertEqual(self.store.task(self.task)['run_id'],old_run)
        self.assertEqual(restored['orxExperiment']['orxRunId'],old_orx)
        self.assertEqual(restored['inferenceWait']['controlId'],paused['inferenceWait']['controlId'])
        self.assertEqual(restored['inferenceWait']['deadline'],paused['inferenceWait']['deadline'])
        self.assertFalse(self.store.task(self.task)['cancel_requested'])


class ActualInferenceStopTests(InferenceWaitFixture):
    def assert_stopped(self,original,*,failure=True):
        d=self.wait(lambda d:d['job']['status'] in {'failed','canceled'},seconds=35)
        self.assertEqual(d['job']['status'],'failed' if failure else 'canceled')
        self.assertEqual(d['orxExperiment']['orxRunId'],original)
        self.assertTrue(d['orxExperiment']['stopEvidence']['allStopped'])
        self.assertEqual(len([e for e in self.store.events(self.task) if e['type']=='orx_experiment_launch_intent' and e['data']['newIntent']]),1)
        self.record_evidence({'realORX':True,'orxRunId':original,'status':d['job']['status'],'launchCount':1,
            'stopEvidence':d['orxExperiment']['stopEvidence'],'inferenceWait':d['inferenceWait']})
        return d

    def test_user_cancel_stops_waiting_external_work(self):
        d=self.launch();original=d['orxExperiment']['orxRunId']
        self.request('POST','/jobs/'+self.task+'/cancel',{})
        self.assert_stopped(original,failure=False)

    def test_declined_recovery_stops_work_and_records_decision(self):
        d=self.launch();a=d['job']['approvalDetail'];original=d['orxExperiment']['orxRunId']
        result=self.request('POST','/jobs/'+self.task+'/commands',{'commandId':str(uuid4()),'action':'approve',
            'requirementId':a['id'],'version':a['version'],'approved':False})
        self.assertTrue(result['decisionRecorded'],result)
        self.assert_stopped(original,failure=False)

    def test_connection_revocation_during_inference_wait_stops_work(self):
        d=self.launch();original=d['orxExperiment']['orxRunId']
        self.state['connections'].revoke('alice',self.pins['localExperimentRun']['ref'],str(uuid4()))
        stopped=self.assert_stopped(original)
        from datetime import datetime, timedelta
        denied=next(e for e in stopped['events'] if e['type']=='protected_denied')
        self.assertLess(datetime.fromisoformat(denied['createdAt']),datetime.fromisoformat(d['inferenceWait']['deadline'])-timedelta(seconds=1))

    def test_original_wait_deadline_cleans_up_without_any_resume(self):
        d=self.launch();original=d['orxExperiment']['orxRunId']
        stopped=self.assert_stopped(original)
        self.assertTrue(any(e['type']=='protected_denied' and e['data'].get('code')=='INFERENCE_WAIT_EXPIRED' for e in stopped['events']))

    def test_authoritative_over_budget_usage_stops_waiting_work(self):
        from agent_factory.usage_ledger import UsageEvidence
        d=self.launch();original=d['orxExperiment']['orxRunId']
        attempts=self.store.usage_ledger.inspect('alice',self.task)['attempts']
        unknown=next(a for a in reversed(attempts) if a['state']=='UNKNOWN')
        # Adversarial authoritative usage for an existing held attempt; no new
        # call, fake provider receipt or paid execution is introduced.
        scopes=self.store.usage_ledger.inspect('alice',self.task)['scopes']
        over_limit=min(scope['tokenLimit'] for scope in scopes)+1
        self.store.usage_ledger.finish_attempt(unknown['id'],UsageEvidence(over_limit,0,"controlled-over-budget-acceptance"))
        stopped=self.assert_stopped(original)
        self.assertTrue(any(e['type']=='protected_denied' and e['data'].get('code')=='USAGE_BUDGET_EXCEEDED' for e in stopped['events']))

    def test_source_drift_stops_original_tree_without_fabricating_success(self):
        from agent_factory.orx_experiment_tools import original_experiment_binding
        d=self.launch();original=d['orxExperiment']['orxRunId']
        binding=original_experiment_binding(self.settings,self.store,self.task)[3]
        source=binding.adapter.scope/'toy-repository'/'candidate.py'
        self.assertTrue(source.resolve().is_relative_to(self.root))
        source.write_text(source.read_text()+'\n# generated acceptance source drift\n')
        deadline=time.monotonic()+25
        evidence=None
        while time.monotonic()<deadline:
            evidence=next((e['data'] for e in self.store.events(self.task) if e['type']=='orx_cleanup_source_unverified'),None)
            if evidence:break
            time.sleep(.2)
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence['orxRunId'],original)
        self.assertTrue(evidence['stopEvidence']['allStopped'])
        self.assertFalse(evidence['sourceVerified'])
        self.assertFalse(self.store.task(self.task)['terminal'])
        self.assertTrue(self.store.task(self.task)['cancel_requested'])
        self.assertEqual(self.store.effects(self.task)[0]['status'],'UNKNOWN')
        self.record_evidence({'realORX':True,'sourceDrift':True,**evidence})


@unittest.skipUnless(os.getenv('FACTORY_AT10_BROWSER') == '1', 'Explicit actual Chromium acceptance opt-in')
class ActualInferenceBrowserTests(ActualInferenceRestartTests):
    def after_pause(self,paused):
        super().after_pause(paused)
        from playwright.sync_api import sync_playwright
        self.playwright=sync_playwright().start();self.addCleanup(self.playwright.stop)
        self.browser=self.playwright.chromium.launch(headless=True);self.addCleanup(self.browser.close)
        context=self.browser.new_context(extra_http_headers={'Authorization':'Bearer '+self.state['auth']._issue_native_token('alice')},
            viewport={'width':1440,'height':1000})
        self.page=context.new_page();self.page.set_default_timeout(12000)
        self.page.goto(f'http://127.0.0.1:{self.port}')
        self.page.locator('button.task-row').filter(has_text='AT10 controlled inference outage').click()
        self.page.get_by_role('heading',name='推理服务暂时不可用',exact=True).wait_for()
        self.page.get_by_role('button',name='恢复本次推理',exact=True).wait_for()
        self.assertTrue(self.page.get_by_role('button',name='停止本任务',exact=True).is_visible())
        target=Path(os.getenv('FACTORY_AT10_EVIDENCE_DIR',str(self.root)))
        target.mkdir(parents=True,exist_ok=True)
        self.page.screenshot(path=str(target/'inference-recovery-desktop.png'),full_page=True)
        self.page.set_viewport_size({'width':390,'height':844})
        self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'))
        self.page.screenshot(path=str(target/'inference-recovery-mobile.png'),full_page=True)
        self.browser_recovered=False

    def approve(self,d):
        if d['job']['approvalDetail']['toolName']==CONTROL_NAME and not self.browser_recovered:
            self.page.get_by_role('button',name='恢复本次推理',exact=True).dblclick()
            self.browser_recovered=True
            self.wait(lambda d:d['snapshot']['queue']['status']!='paused',seconds=10)
            return None
        if d['job']['approvalDetail']['toolName']==CONTROL_NAME:
            self.assertEqual(len(self.store.sql("SELECT command_id FROM af_control_commands WHERE root_task_id=:task AND body->>'inferenceRecovery'='true'",task=self.task)),1)
            return None
        return super().approve(d)
