"""Actual Linux AT10 across delegated native tickets and independent HTTP services."""
import copy
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import uuid4

import httpx

from pg_fixture import IsolatedPostgres
from inference_tree_worker import build, ORIGIN, TARGET
from agent_factory.local_orx_profile import publish_local_orx_application, REGISTRATION_REF
from agent_factory.inference_wait import CONTROL_NAME


class Service:
    def __init__(self, config, directory):
        self.config=config;self.path=directory/(config['role']+'.json')
        self.process=None;self.log=None
        self.app,self.state=build(config)
        self.url='http://127.0.0.1:'+str(config['port'])

    def start(self):
        self.path.write_text(json.dumps(self.config))
        if self.log:self.log.close()
        self.log=self.path.with_suffix('.log').open('a')
        self.process=subprocess.Popen([sys.executable,'-m','inference_tree_worker'],
            env={**os.environ,'FACTORY_AT10_TREE_CONFIG':str(self.path)},stdout=self.log,stderr=self.log)
        end=time.monotonic()+25
        with httpx.Client(timeout=1,trust_env=False) as client:
            while time.monotonic()<end:
                if self.process.poll() is not None:raise AssertionError(self.path.with_suffix('.log').read_text()[-4000:])
                try:
                    if client.get(self.url+'/api/health').is_success:return
                except httpx.TransportError:pass
                time.sleep(.1)
        raise AssertionError('Owned service startup exceeded bound')

    def stop(self, hard=False):
        if self.process and self.process.poll() is None:
            self.process.kill() if hard else self.process.terminate()
            try:self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
        if self.log:self.log.close();self.log=None

    def close(self):
        self.stop();self.state['store'].engine.dispose();self.state['store'].native_db.db_engine.dispose()


@unittest.skipUnless(os.getenv('FACTORY_ORX_LINUX_CONTAINER')=='1' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Explicit owned Linux ORX/isolated PostgreSQL opt-in')
class TreeFixture(unittest.TestCase):
    remote=False
    fault_scope='child'

    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='factory-at10-tree-',dir=os.getenv('FACTORY_AT10_FIXTURE_ROOT'));self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name);self.services=[];self.extra_evidence={}
        self.addCleanup(self.clean_containers)
        self.gate=self.root/'fault.json';self.gate.write_text(json.dumps({'scope':self.fault_scope,'failedTasks':[]}))
        configs=[]
        for role in (('origin','receiver') if self.remote else ('local',)):
            database=IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__();self.addCleanup(database.__exit__,None,None,None)
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            configs.append({'role':role,'dbUrl':database.url,'workspace':str(self.root/role),'port':port,
                'jwtKey':secrets.token_urlsafe(48),'gate':str(self.gate)})
        if self.remote:
            common={'originUrl':'http://127.0.0.1:'+str(configs[0]['port']),'receiverUrl':'http://127.0.0.1:'+str(configs[1]['port']),
                'originJwtKey':configs[0]['jwtKey'],'receiverJwtKey':configs[1]['jwtKey']}
            for c in configs:c.update(common)
        application=None
        for config in configs:
            server=Service(config,self.root);self.services.append(server);self.addCleanup(server.close)
            state=server.state;state['auth'].authorization.unassign('bob','factory-user');state['auth'].authorization.assign('bob','factory-manager')
            parent_gate=None
            if self.fault_scope=='parent':
                governance=state['material_governance']
                parent_gate=governance.create_draft('manager',{'id':'at10-parent-scope-tool','kind':'tool',
                    'name':'AT10 parent scope confirmation','description':'Native user-input gate for synthetic lifecycle coordination',
                    'content':'ask_scope','license':'MIT','compatibility':['agno:3.1.0'],'dependencies':[],
                    'permissions':['question:ask'],'runtimeBinding':{'adapterId':'native-ask-scope-v1','revision':'1','config':{}},
                    'provenance':{'kind':'original','notice':'Synthetic test coordination only'}},'at10-parent-scope-draft')
                review=governance.request_publication('manager',parent_gate['id'],parent_gate['version'],'at10-parent-scope-review')
                governance.decide_publication('bob',review['id'],True,'at10-parent-scope-approve')
            first_application=application is None
            application=publish_local_orx_application(state,author='manager',reviewer='bob',contract_revision='2',source_application=application)
            if parent_gate and first_application:
                from agent_factory.applications import ApplicationDefinition
                definition={k:copy.deepcopy(application[k]) for k in ApplicationDefinition.model_fields if k in application}
                definition['id']='at10-parent-tree-application'
                for mode in definition['modes'].values():
                    mode['materialRefs'].append({k:parent_gate[k] for k in ('id','version','sha256')})
                    mode['toolOrder'].append('ask_scope');mode['capabilities'].append('question:ask')
                applications=state['applications']
                application=applications.create_draft('manager',definition,'at10-parent-app-draft')
                review=applications.request_publication('manager',application['id'],application['version'],'at10-parent-app-review')
                applications.decide_publication('bob',review['id'],True,'at10-parent-app-approve')
            server.pins={n:state['connections'].bind('alice',REGISTRATION_REF,config['role']+'-'+n,capabilities=[cap])
                for n,cap in (('localExperimentRead','research:read'),('localExperimentRun','compute:local'))}
        self.application=application;self.origin=self.services[0];self.receiver=self.services[-1]
        self.origin.start()

    def clean_containers(self):
        for marker in self.root.rglob('factory-linux-container.json'):
            saved=json.loads(marker.read_text());cid=saved['containerId']
            obj=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
            self.assertEqual(obj['Config']['Labels']['agent-factory.orx-spec'],saved['specSha256'])
            self.assertIn(str(marker.parent),[m['Source'] for m in obj['Mounts'] if m['RW']])
            if obj['State']['Running']:subprocess.run(['docker','kill',cid],capture_output=True,check=True)
            subprocess.run(['docker','rm',cid],capture_output=True,check=True)

    def tearDown(self):
        out=os.getenv('FACTORY_AT10_TREE_EVIDENCE_DIR')
        if out:
            path=Path(out);path.mkdir(parents=True,exist_ok=True)
            for server in self.services:
                server.stop()
                log=server.path.with_suffix('.log')
                if log.exists():
                    (path/(type(self).__name__+'-'+self._testMethodName+'-'+server.config['role']+'.log')).write_bytes(log.read_bytes())
                timing=server.path.with_suffix('.timings.json')
                if timing.exists():(path/(type(self).__name__+'-'+self._testMethodName+'-'+server.config['role']+'.timings.json')).write_bytes(timing.read_bytes())

    def call(self,server,method,path,body=None,owner='alice'):
        token=server.state['auth']._issue_native_token(owner)
        with httpx.Client(timeout=75,trust_env=False) as client:
            r=client.request(method,server.url+'/api/factory'+path,json=body,headers={'Authorization':'Bearer '+token})
        self.assertTrue(r.is_success,{'status':r.status_code,'body':r.text[:1500]})
        return r.json()

    def post(self,server,path,body,owner='alice'):
        return self.call(server,'POST',path,{'requestId':str(uuid4()),**body},owner)

    def review(self,server,plan):
        r=self.post(server,'/plan-reviews',{'planId':plan})
        self.post(server,'/plan-reviews/'+r['id']+'/decision',{'approved':True},'manager')

    def wait(self,server,task,predicate,seconds=90):
        end=time.monotonic()+seconds
        previous=None
        while time.monotonic()<end:
            d=self.call(server,'GET','/jobs/'+task)
            state=(d['job']['status'],d['job'].get('approvalDetail',{}).get('toolName'))
            if state!=previous:
                print('AT10 tree',time.strftime('%H:%M:%S',time.gmtime()),task,state,flush=True);previous=state
            if predicate(d):return d
            if d['job']['status'] in {'failed','canceled'}:break
            time.sleep(.12)
        self.fail(str({'task':task,'status':d['job']['status'],'wait':d.get('inferenceWait'),
            'events':[(e['type'],e['message'],e['data']) for e in d['events'][-15:]]}))

    def approval(self,server,task,d,approved=True):
        a=d['job']['approvalDetail']
        return self.call(server,'POST','/jobs/'+task+'/approve',{'requirementId':a['id'],'version':a['version'],'approved':approved})

    def prepare(self, *, parent_inference=False):
        proposal=self.post(self.origin,'/compositions/proposals',{'goal':'Owned AT10 delegated receiver experiment','mode':'cancellable',
            'applicationRef':{k:self.application[k] for k in ('id','version','sha256')},
            'connectionRefs':{n:p['ref'] for n,p in self.origin.pins.items()}})
        self.assertEqual(proposal['candidate']['status'],'ready',proposal)
        plan=self.post(self.origin,'/compositions/proposals/'+proposal['id']+'/accept',{})
        self.review(self.origin,plan['id']);body={'planId':plan['id'],'requestId':str(uuid4())}
        if self.remote:
            mappings=[]
            for spec in plan['executionBindings']['tools']:
                effective=copy.deepcopy(spec)
                if 'connection' in spec:
                    pin=self.receiver.pins[spec['config']['connectionName']]
                    effective['connection']={k:copy.deepcopy(pin[k]) for k in spec['connection']}
                mappings.append({'reference':'at10-map-'+spec['toolName'],'revision':'2','origin_ref':ORIGIN,
                    'origin_owner':'alice','receiver_owner':'alice','kind':'tool','source_spec':spec,'effective_spec':effective})
            self.receiver.config['mappings']=mappings;self.receiver.start();body['executionTargetRef']=TARGET
            job=self.call(self.origin,'POST','/instances',body);self.origin_task=job['id']
            d=self.call(self.origin,'GET','/jobs/'+job['id']);receipt=d['snapshot']['remoteHandoff']
            self.review(self.receiver,receipt['remotePlanId'])
            self.call(self.origin,'POST','/instances',body)
            d=self.call(self.origin,'GET','/jobs/'+job['id']);self.parent=d['snapshot']['remoteHandoff']['remoteTaskId']
            self.instance_body=body
        else:
            self.parent=self.call(self.origin,'POST','/instances',body)['id'];self.origin_task=self.parent
        self.parent_approval=self.wait(self.receiver,self.parent,lambda d:d['job']['status']==('waiting_input' if parent_inference else 'waiting_approval'))
        return self.parent_approval

    def launch_child(self):
        self.prepare()
        result=self.post(self.receiver,'/jobs/'+self.parent+'/children',{'goal':'Same approved child experiment','mode':'cancellable'})
        child=result['childTask']['id']
        approved=self.wait(self.receiver,child,lambda d:d['job']['status']=='waiting_approval')
        self.approval(self.receiver,child,approved)
        paused=self.wait(self.receiver,child,lambda d:d['job'].get('approvalDetail',{}).get('toolName')==CONTROL_NAME and d['job']['status']=='waiting_approval')
        self.assertEqual(paused['job']['status'],'waiting_approval',paused['job'])
        self.assertFalse(paused['orxExperiment']['stopEvidence']['allStopped'])
        return child,paused

    def launch_root(self):
        approved=self.prepare();self.approval(self.receiver,self.parent,approved)
        paused=self.wait(self.receiver,self.parent,lambda d:d['job'].get('approvalDetail',{}).get('toolName')==CONTROL_NAME and d['job']['status']=='waiting_approval')
        self.assertEqual(paused['job']['status'],'waiting_approval',paused['job'])
        self.assertFalse(paused['orxExperiment']['stopEvidence']['allStopped'])
        return self.parent,paused

    def proof(self,task,original):
        store=self.receiver.state['store'];value=store.task(task)
        self.assertEqual(value['run_id'],original['inferenceWait']['nativeRunId'])
        self.assertEqual(len([e for e in store.events(task) if e['type']=='orx_experiment_launch_intent' and e['data']['newIntent']]),1)
        d=self.call(self.receiver,'GET','/jobs/'+task)
        self.assertEqual(d['orxExperiment']['orxRunId'],original['orxExperiment']['orxRunId'])
        self.assertTrue(d['orxExperiment']['stopEvidence']['allStopped'])
        if self.remote:
            self.assertIsNone(self.origin.state['store'].task(self.origin_task)['run_id'])
        out=os.getenv('FACTORY_AT10_TREE_EVIDENCE_DIR')
        if out:
            path=Path(out);path.mkdir(parents=True,exist_ok=True)
            (path/(type(self).__name__+'-'+self._testMethodName+'.json')).write_text(json.dumps({
                'nativeRunId':value['run_id'],'orxRunId':d['orxExperiment']['orxRunId'],'launchCount':1,
                'status':d['job']['status'],'inferenceWait':d['inferenceWait'],'stopEvidence':d['orxExperiment']['stopEvidence'],
                'remote':self.remote,'independentServices':len(self.services),'originHasNativeRun':False if self.remote else None,
                **self.extra_evidence},indent=2)+'\n')
        return d

    def recover(self,task,paused,restart=True):
        print('AT10 recovery begin',time.strftime('%H:%M:%S',time.gmtime()),paused['inferenceWait']['deadline'],flush=True)
        if restart:
            old=self.receiver.process.pid;self.receiver.stop(hard=True);self.receiver.start()
            self.assertNotEqual(self.receiver.process.pid,old)
        print('AT10 restarted',time.strftime('%H:%M:%S',time.gmtime()),flush=True)
        restored=self.call(self.receiver,'GET','/jobs/'+task)
        self.assertEqual(restored['inferenceWait']['controlId'],paused['inferenceWait']['controlId'])
        self.assertEqual(restored['inferenceWait']['deadline'],paused['inferenceWait']['deadline'])
        self.approval(self.receiver,task,restored);self.approval(self.receiver,task,restored)
        print('AT10 continuation accepted',time.strftime('%H:%M:%S',time.gmtime()),flush=True)
        self.wait(self.receiver,task,lambda d:d['job']['status']=='completed',seconds=60)
        self.proof(task,paused)


class ActualDelegatedInferenceTests(TreeFixture):
    def test_child_recovery_after_service_restart_keeps_one_run(self):
        child,paused=self.launch_child();self.recover(child,paused)
        self.call(self.receiver,'POST','/jobs/'+self.parent+'/cancel',{})


class ActualReceiverInferenceTests(TreeFixture):
    remote=True
    fault_scope='root'
    def test_receiver_restart_recovers_same_original_run(self):
        task,paused=self.launch_root();self.recover(task,paused)
        self.call(self.origin,'POST','/jobs/'+self.origin_task+'/reconcile',{})
        self.assertIsNone(self.origin.state['store'].task(self.origin_task)['run_id'])


class ActualReceiverChildInferenceTests(TreeFixture):
    remote=True
    def test_receiver_child_restart_preserves_root_receipt_and_child_run(self):
        child,paused=self.launch_child();self.recover(child,paused)
        owner=paused['inferenceWait']['executionOwner']
        self.assertEqual(owner['rootTaskId'],self.parent)
        self.assertEqual(owner['ancestorTaskIds'],[self.parent])
        self.assertEqual(owner['receiver']['originTaskId'],self.origin_task)
        self.call(self.origin,'POST','/jobs/'+self.origin_task+'/cancel',{})


class ActualParentInferenceTests(TreeFixture):
    fault_scope='parent'
    def test_parent_inference_fault_preserves_acknowledged_child_work(self):
        self.prepare(parent_inference=True)
        result=self.post(self.receiver,'/jobs/'+self.parent+'/children',{'goal':'Child independent approved work','mode':'cancellable'})
        child=result['childTask']['id']
        child_approval=self.wait(self.receiver,child,lambda d:d['job']['status']=='waiting_approval')
        control_server=self.origin if self.remote else self.receiver
        control_task=self.origin_task+'~'+child if self.remote else child
        self.approval(control_server,control_task,child_approval)
        running=self.wait(self.receiver,child,lambda d:(d.get('orxExperiment') or {}).get('orxRunId') is not None)
        self.assertFalse(running['orxExperiment']['stopEvidence']['allStopped'])
        gate=json.loads(self.gate.read_text());gate['parentFaultTask']=self.parent;self.gate.write_text(json.dumps(gate))
        question=self.parent_approval['job']['questionDetail']
        self.call(self.receiver,'POST','/jobs/'+self.parent+'/answer',{'questionId':question['id'],
            'version':question['version'],'answer':'Observe only the original independently approved child'})
        # Native user input starts a fresh bounded inference leg only after
        # the independently approved real child has acknowledged launch.
        paused=self.wait(self.receiver,self.parent,lambda d:d['job'].get('approvalDetail',{}).get('toolName')==CONTROL_NAME and d['job']['status']=='waiting_approval')
        self.assertEqual([w['taskId'] for w in paused['inferenceWait']['externalWork']],[child])
        self.assertFalse(self.receiver.state['store'].task(child)['cancel_requested'])
        self.receiver.stop(hard=True);self.receiver.start()
        restored=self.call(self.receiver,'GET','/jobs/'+self.parent)
        self.assertEqual(restored['inferenceWait']['controlId'],paused['inferenceWait']['controlId'])
        self.approval(self.receiver,self.parent,restored)
        child_state=self.wait(self.receiver,child,lambda d:d['job']['status'] in {'completed','waiting_approval'},seconds=60)
        if child_state['job']['status']=='waiting_approval':
            # Native Agno can replay a pending confirmation after worker loss.
            # The current owner explicitly approves; the durable original effect
            # must reconcile, never grant a second launch.
            self.assertEqual(child_state['job']['approvalDetail']['toolName'],'orx_experiment_run')
            self.assertEqual(self.receiver.state['store'].task(child)['run_id'],running['orxExperiment']['nativeRunId'])
            self.assertIn('resume_approved',child_state['job']['allowedActions'])
            projected=self.call(control_server,'GET','/jobs/'+control_task)
            recovery=projected['job']['recoveryDetail']
            command={'commandId':str(uuid4()),'action':'resume_approved',
                **{k:recovery[k] for k in ('approvalCommandId','requirementId','version')}}
            browser_python=os.getenv('FACTORY_AT10_BROWSER_PYTHON')
            if browser_python and not self.remote:
                out=Path(os.environ['FACTORY_AT10_TREE_EVIDENCE_DIR']);out.mkdir(parents=True,exist_ok=True)
                config={'baseUrl':control_server.url,'headers':{'Authorization':'Bearer '+control_server.state['auth']._issue_native_token('alice')},
                    'beforeScreenshot':str(out/'recorded-approval-before.png'),'afterScreenshot':str(out/'recorded-approval-after.png'),
                    'receiptPath':str(out/'recorded-approval-browser.json')}
                private=self.root/'browser-config.json';private.write_text(json.dumps(config))
                subprocess.run([browser_python,str(Path(__file__).with_name('inference_recovery_browser.py')),str(private)],check=True,timeout=100)
                first=json.loads(Path(config['receiptPath']).read_text())['receipt'];command['commandId']=first['commandId']
            else:
                first=self.call(control_server,'POST','/jobs/'+control_task+'/commands',command)
            duplicate=self.call(control_server,'POST','/jobs/'+control_task+'/commands',command)
            self.assertEqual(first['commandId'],duplicate['commandId'])
            self.extra_evidence.update(repairReceipt=first,duplicateRepairReceipt=duplicate,approvalAndRepairFromOrigin=self.remote)
        self.wait(self.receiver,child,lambda d:d['job']['status']=='completed',seconds=60)
        self.wait(self.receiver,self.parent,lambda d:d['job']['status']=='completed',seconds=25)
        # The wait owner is the parent; the experiment owner stays the child.
        self.extra_evidence['parentInferenceWait']=self.call(self.receiver,'GET','/jobs/'+self.parent)['inferenceWait']
        proof={**running,'inferenceWait':{'nativeRunId':self.receiver.state['store'].task(child)['run_id']}}
        self.proof(child,proof)
        self.assertFalse(self.receiver.state['store'].sql('SELECT 1 FROM af_orx_task_experiments WHERE task_id=:task',task=self.parent))


class ActualReceiverParentInferenceTests(ActualParentInferenceTests):
    remote=True


class ActualDelegatedStopTests(TreeFixture):
    def test_parent_cancel_stops_waiting_child_without_releasing_unknown_usage(self):
        child,paused=self.launch_child()
        self.call(self.receiver,'POST','/jobs/'+self.parent+'/cancel',{})
        self.wait(self.receiver,child,lambda d:d['job']['status']=='canceled',seconds=35)
        self.proof(child,paused)
        ledger=self.receiver.state['store'].usage_ledger.inspect('alice',child)
        self.assertTrue(any(a['state']=='UNKNOWN' for a in ledger['attempts']))
        self.assertTrue(any(s['heldTokens']>0 for s in ledger['scopes']))

    def test_child_overrun_stops_work_under_shared_ancestor_budget(self):
        from agent_factory.usage_ledger import UsageEvidence
        child,paused=self.launch_child();ledger=self.receiver.state['store'].usage_ledger
        state=ledger.inspect('alice',child);attempt=next(a for a in state['attempts'] if a['state']=='UNKNOWN')
        limit=min(s['tokenLimit'] for s in state['scopes'])
        ledger.finish_attempt(attempt['id'],UsageEvidence(limit+1,0,'controlled-child-overrun'))
        self.wait(self.receiver,child,lambda d:d['job']['status']=='failed',seconds=35)
        d=self.proof(child,paused)
        self.assertTrue(any(e['type']=='protected_denied' and e['data'].get('code')=='USAGE_BUDGET_EXCEEDED' for e in d['events']))
        root=next(s for s in ledger.inspect('alice',child)['scopes'] if s['scope']=='root')
        self.assertGreater(root['settledTokens'],root['tokenLimit'])
        self.call(self.receiver,'POST','/jobs/'+self.parent+'/cancel',{})


class ActualReceiverSafetyTests(TreeFixture):
    remote=True
    fault_scope='root'

    def stopped(self,task,paused,status='failed'):
        self.wait(self.receiver,task,lambda d:d['job']['status']==status,seconds=40)
        result=self.proof(task,paused)
        if status=='failed' and self._testMethodName!='test_original_wait_deadline_stops_receiver':
            from datetime import datetime
            denied=next(e for e in result['events'] if e['type']=='protected_denied')
            self.assertLess(datetime.fromisoformat(denied['createdAt']),datetime.fromisoformat(paused['inferenceWait']['deadline']))
        return result

    def test_origin_outage_fails_closed_restart_never_relaunches(self):
        task,paused=self.launch_root();self.origin.stop(hard=True)
        d=self.stopped(task,paused)
        self.assertEqual(d['inferenceWait']['state'],'STOPPING')
        self.origin.start()
        self.call(self.origin,'POST','/jobs/'+self.origin_task+'/reconcile',{})
        self.proof(task,paused)
        ledger=self.receiver.state['store'].usage_ledger.inspect('alice',task)
        self.assertTrue(any(a['state']=='UNKNOWN' for a in ledger['attempts']))
        self.assertTrue(any(s['heldTokens']>0 for s in ledger['scopes']))
        grants=self.origin.state['store'].sql('SELECT state FROM af_usage_remote_grants WHERE task_id=:task',task=self.origin_task)
        self.assertTrue(grants);self.assertEqual(grants[0]['state'],'ALLOCATED')

    def revoke(self,server):
        task,paused=self.launch_root()
        server.state['connections'].revoke('alice',server.pins['localExperimentRun']['ref'],str(uuid4()))
        d=self.stopped(task,paused)
        from datetime import datetime
        denied=next(e for e in d['events'] if e['type']=='protected_denied')
        self.assertLess(datetime.fromisoformat(denied['createdAt']),datetime.fromisoformat(paused['inferenceWait']['deadline']))

    def test_origin_connection_revocation_stops_receiver(self):
        self.revoke(self.origin)

    def test_receiver_connection_revocation_stops_original_pin(self):
        self.revoke(self.receiver)

    def test_origin_cancel_stops_receiver_as_cancellation(self):
        task,paused=self.launch_root()
        self.call(self.origin,'POST','/jobs/'+self.origin_task+'/cancel',{})
        self.stopped(task,paused,'canceled')

    def test_original_wait_deadline_stops_receiver(self):
        task,paused=self.launch_root();d=self.stopped(task,paused)
        self.assertTrue(any(e['type']=='protected_denied' and e['data'].get('code')=='INFERENCE_WAIT_EXPIRED' for e in d['events']))

    def test_receiver_authoritative_overrun_stops_original_work(self):
        from agent_factory.usage_ledger import UsageEvidence
        task,paused=self.launch_root();ledger=self.receiver.state['store'].usage_ledger
        state=ledger.inspect('alice',task);attempt=next(a for a in state['attempts'] if a['state']=='UNKNOWN')
        ledger.finish_attempt(attempt['id'],UsageEvidence(min(s['tokenLimit'] for s in state['scopes'])+1,0,'controlled-receiver-overrun'))
        d=self.stopped(task,paused)
        self.assertTrue(any(e['type']=='protected_denied' and e['data'].get('code')=='USAGE_BUDGET_EXCEEDED' for e in d['events']))

    def test_origin_account_overrun_revokes_current_receiver_authority(self):
        task,paused=self.launch_root();store=self.origin.state['store']
        # Controlled accounting fault at the existing source reservation, not
        # provider usage evidence or a new model invocation.
        account=store.sql("SELECT body FROM af_usage_accounts WHERE id=:id",id='task:'+self.origin_task)[0]['body']
        store.sql('UPDATE af_usage_accounts SET settled_tokens=:tokens WHERE id=:id',id='task:'+self.origin_task,tokens=account['tokenLimit']+1)
        self.stopped(task,paused)
        state=store.usage_ledger.inspect('alice',self.origin_task)
        self.assertTrue(any(s['settledTokens']>s['tokenLimit'] for s in state['scopes']))

    def test_receiver_source_drift_stops_tree_and_keeps_unknown_holds(self):
        from agent_factory.orx_experiment_tools import original_experiment_binding
        task,paused=self.launch_root();store=self.receiver.state['store']
        binding=original_experiment_binding(self.receiver.state['settings'],store,task)[3]
        source=binding.adapter.scope/'toy-repository'/'candidate.py'
        self.assertTrue(source.resolve().is_relative_to(self.root));source.write_text(source.read_text()+'\n# controlled owned source drift\n')
        end=time.monotonic()+30;evidence=None
        while time.monotonic()<end:
            evidence=next((e['data'] for e in store.events(task) if e['type']=='orx_cleanup_source_unverified'),None)
            if evidence:break
            time.sleep(.2)
        self.assertIsNotNone(evidence);self.assertTrue(evidence['stopEvidence']['allStopped'])
        self.assertEqual(evidence['orxRunId'],paused['orxExperiment']['orxRunId'])
        self.assertFalse(store.task(task)['terminal']);self.assertEqual(store.effects(task)[0]['status'],'UNKNOWN')
        hold=store.sql('SELECT state FROM af_disk_holds WHERE task_id=:task',task=task)[0]
        self.assertEqual(hold['state'],'HELD')
        out=os.getenv('FACTORY_AT10_TREE_EVIDENCE_DIR')
        if out:(Path(out)/(type(self).__name__+'-'+self._testMethodName+'.json')).write_text(json.dumps({'sourceDrift':True,'effectState':'UNKNOWN','diskHold':'HELD',**evidence},indent=2)+'\n')
