"""Native process/PG restart; fixture identity and scripted provider, no external IO.

Reuse WorkflowServer's config, internal test authentication and cleanup. This
module can live in applications/tests; the audit copy changes no product file.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import httpx
from agno.db.postgres import PostgresDb
from sqlalchemy import text
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from fixture_auth import initialize_members
from fixture_settings import Settings
from pg_fixture import IsolatedPostgres
from research.session_tools import ResearchSessionTools
from test_native_workflow_factory_postgres import WorkflowServer, PROJECT

HERE = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def count(path):
    return len(path.read_text(encoding='utf-8').splitlines()) if path.exists() else 0


def serve(cfg):
    import uvicorn
    output = Path(cfg['output'])
    call_id = 'restart-' + cfg['mode']
    def provider(request):
        assert str(request.url) == 'http://127.0.0.1:1/v1/chat/completions'
        body = json.loads(request.content)
        with (output / 'scripted-calls.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'pid':os.getpid(),'phase':cfg['phase'],'messages':len(body['messages'])})+'\n')
            handle.flush(); os.fsync(handle.fileno())
        if cfg['mode'] == 'completed' and (cfg['phase'] == 'restart' or any(m['role']=='tool' for m in body['messages'])):
            message = {'role':'assistant','content':'SCRIPTED: original operation observed; no new side effect requested.'}
        else:
            message = {'role':'assistant','content':None,'tool_calls':[{'id':call_id,'type':'function',
                'function':{'name':'research_run','arguments':json.dumps({'argv':[Path(sys.executable).name,'-I','once.py']})}}]}
        return httpx.Response(200,json={'id':'explicit-restart-fixture','object':'chat.completion','model':'SCRIPTED-restart',
            'choices':[{'index':0,'message':message,'finish_reason':'tool_calls' if message.get('tool_calls') else 'stop'}],
            'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}})
    settings = Settings(db_url=cfg['dbUrl'],jwt_key=cfg['jwtKey'],workspace=Path(cfg['workspace']),
        max_workers=1,storage_task_reserve_bytes=8*1024*1024,
        owner_model_transport_factory=lambda:httpx.MockTransport(provider))
    tools = ResearchSessionTools(workspace_root=Path(cfg['coding']),host_commands=True,
                                command_path=str(Path(sys.executable).parent))
    app = create_app(settings,session_tools=tools)
    state = factory_state(app); store = state['store']
    initialize_members(state['auth'])
    if cfg['phase']=='first' and cfg['mode'] in ('unknown','done'):
        complete = store.effect_complete
        def crash_before_return(run_id,key,result):
            if not key.endswith(call_id): return complete(run_id,key,result)
            assert result['outcome']=='completed' and result['output']['stopped'] is True and result['output']['exitCode']==0
            if cfg['mode']=='done': complete(run_id,key,result)
            task=store.task(run_id)
            ticket=store.native_db.get_job(run_id)
            fault={'taskId':task['id'],'runId':run_id,'requestId':task['request_id'],'callId':call_id,
                   'attempt':ticket['attempt'],'effectState':store.effects(task['id']),
                   'point':'after durable DONE before tool return' if cfg['mode']=='done' else 'after actual command, before effect_complete'}
            with (output/'fault.json').open('w',encoding='utf-8') as handle:
                json.dump(fault,handle);handle.flush();os.fsync(handle.fileno())
            os._exit(83 if cfg['mode']=='done' else 82)
        store.effect_complete=crash_before_return
    uvicorn.run(state['http_app'],host='127.0.0.1',port=cfg['port'],log_level='error',access_log=False)


class RestartServer(WorkflowServer):
    def start(self):
        # The shared harness inherits the developer env; this probe passes no keys.
        env={'PATH':str(Path(sys.executable).parent), 'PYTHONNOUSERSITE':'1','AGNO_TELEMETRY':'false',
             'PYTHONPATH':os.pathsep.join([str(HERE),*[str(PROJECT/p) for p in ('platform','platform/tests','applications','applications/tests','deployment')]])}
        if os.name=='nt':
            env['SystemRoot']=os.environ['SystemRoot']
            env['TEMP']=env['TMP']=str(self.root)
        self.config.write_text(json.dumps(self.configuration),encoding='utf-8')
        self.log=(self.root/('server-'+self.configuration['phase']+'.log')).open('ab')
        self.process=subprocess.Popen([sys.executable,'-B',str(HERE/'test_research_windows_restart.py'),'--serve',str(self.config)],
            cwd=PROJECT,env=env,stdin=subprocess.DEVNULL,stdout=self.log,stderr=subprocess.STDOUT)
        self.pids.append(self.process.pid)
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            if self.process.poll() is not None: raise AssertionError('Restart fixture service exited before readiness')
            try:
                if httpx.get(self.url+'/api/health',timeout=1,trust_env=False).status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.1)
        raise AssertionError('Restart fixture service readiness deadline')


def conn_count(db):
    with db.db_engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM af_tasks WHERE owner_id='alice'")).scalar_one()


def observe(db,task_id):
    with db.db_engine.connect() as conn:
        task=dict(conn.execute(text('SELECT id,owner_id,run_id,request_id FROM af_tasks WHERE id=:id'),{'id':task_id}).mappings().one())
        effects=[dict(row) for row in conn.execute(text('SELECT effect_key,status,result FROM af_effects WHERE task_id=:id ORDER BY effect_key'),{'id':task_id}).mappings()]
        turns=[dict(row) for row in conn.execute(text('SELECT id,session_id,application_request_id,body FROM research_session_turns WHERE application_request_id=:id'),{'id':task['request_id'].removeprefix('application-start:')}).mappings()]
    ticket=db.get_job(task['run_id']); native=db.get_run(task['run_id'])
    return {'task':task,'effects':effects,'turns':turns,
            'job':{key:ticket.get(key) for key in ('id','session_id','user_id','status','attempt')},
            'ownerTaskCount':int(conn_count(db)),
            'nativeToolResults':sum(getattr(m,'role',None)=='tool' for m in (getattr(native,'messages',None) or []))}


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'),'Requires authorized disposable loopback PostgreSQL')
class ResearchWindowsRestartTests(unittest.TestCase):
    def case(self,mode):
        evidence_root=Path(os.environ['QA_RESTART_OUTPUT']) if os.getenv('QA_RESTART_OUTPUT') else None
        with ExitStack() as stack:
            db=stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
            root=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='research-restart-')))
            output=(evidence_root/(mode+'-'+str(time.time_ns()))) if evidence_root else root/'evidence'
            output.mkdir(parents=True)
            server=RestartServer(db.url,root)
            coding=root/'coding';coding.mkdir()
            server.configuration.update(mode=mode,phase='first',coding=str(coding),output=str(output))
            def cleanup():
                server.stop()
                for phase in ('first','restart'):
                    log=root/('server-'+phase+'.log')
                    if log.exists():
                        raw=log.read_text(encoding='utf-8',errors='replace')
                        for field in ('dbUrl','jwtKey','controlKey'):raw=raw.replace(server.configuration[field],'[QA_SECRET_REDACTED]')
                        (output/(phase+'.log')).write_text(raw,encoding='utf-8')
                save(output/'cleanup.json',{'serviceExited':server.process is not None and server.process.poll() is not None,'pids':server.pids,'method':'WorkflowServer.stop uses terminate, then kill on timeout; not product stop evidence'})
            stack.callback(cleanup)
            database=PostgresDb(db_url=db.url,id='factory-native-postgres');stack.callback(database.db_engine.dispose)
            server.start()
            def request(method,path,body=None,status=200):
                response=server.request(method,'/api/factory'+path,body)
                self.assertEqual(response.status_code,status,response.text)
                return response.json()
            model=request('POST','/personal-models',{'requestId':mode+'-model','provider':'openai-compatible',
                'baseURL':'http://127.0.0.1:1/v1','model':'SCRIPTED-restart'},201)
            session=request('POST','/research/sessions',{'requestId':mode+'-session','title':'Explicit restart QA '+mode,
                'goal':'Write one actual local line once.','boundaries':'No network, dependencies or extra writes.',
                'modelConnectionRef':model['connectionRef'],'limits':{'maxTurns':3,'toolCallsPerTurn':4,'operationSeconds':8}})
            sid=session['id'];workspace=coding/hashlib.sha256(b'alice').hexdigest()/hashlib.sha256(sid.encode()).hexdigest()
            workspace.mkdir(parents=True)
            (workspace/'once.py').write_text('import os\nwith open("effect.jsonl","a",encoding="utf-8") as f:\n f.write("one-effect\\n");f.flush();os.fsync(f.fileno())\nprint("ACTUAL_EFFECT_ONCE")\n',encoding='utf-8')
            body={'requestId':mode+'-turn','text':'Run once.py exactly once.'}
            try:
                admitted=request('POST','/research/sessions/'+sid+'/turns',body)
                save(output/'admission.json',admitted)
            except httpx.TransportError:
                self.assertNotEqual(mode,'completed')  # Lost initial receipt: never retry an unknown write.
            if mode in ('unknown','done'):
                server.process.wait(timeout=30)
                self.assertEqual(server.process.returncode,83 if mode=='done' else 82)
                fault=json.loads((output/'fault.json').read_text())
                task_id=fault['taskId']
            else:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    read=request('GET','/research/sessions/'+sid)
                    if read['turns'][0]['status']=='completed':break
                    time.sleep(.1)
                self.assertEqual(read['turns'][0]['status'],'completed',read)
                task_id=read['turns'][0]['taskId']
                server.process.kill();server.process.wait(5)
            server.log.close()
            before=observe(database,task_id);save(output/'before-restart.json',before)
            self.assertEqual(count(workspace/'effect.jsonl'),1)
            self.assertEqual(len(before['effects']),1)
            self.assertEqual(before['effects'][0]['status'],'UNKNOWN' if mode=='unknown' else 'DONE')
            self.assertEqual(before['job']['attempt'],1)
            calls=count(output/'scripted-calls.jsonl')
            self.assertEqual(calls,2 if mode=='completed' else 1)
            if mode!='completed':self.assertEqual(before['nativeToolResults'],0)
            server.configuration['phase']='restart';server.start()
            if mode!='completed':
                deadline=time.monotonic()+45
                while time.monotonic()<deadline:
                    current=request('GET','/research/sessions/'+sid)
                    after=observe(database,task_id)
                    if after['turns'][0]['body'].get('blockReason'):break
                    time.sleep(.15)
                self.assertEqual(after['job']['attempt'],2,after)
                self.assertEqual(after['turns'][0]['body'].get('blockReason'),'RESEARCH_RESTART_REQUIRES_RECONCILIATION')
                denied=server.request('POST','/api/factory/research/sessions/'+sid+'/turns',{'requestId':mode+'-unsafe-new','text':'Try new turn'})
                self.assertEqual(denied.status_code,409,denied.text)
            for _ in range(3):
                current=request('GET','/research/sessions/'+sid)
                self.assertEqual(current['id'],sid)
                self.assertEqual(current['assistantId'],session['assistantId'])
                self.assertEqual(current['turns'][0]['id'],before['turns'][0]['id'])
                self.assertEqual(current['turns'][0]['taskId'],before['task']['id'])
                self.assertEqual(current['turns'][0]['runId'],before['task']['run_id'])
            original=request('GET','/research/sessions/requests/'+body['requestId'])
            self.assertFalse(original['automaticReplay']);self.assertFalse(original['createsExecution'])
            repeated=request('POST','/research/sessions/'+sid+'/turns',body)
            self.assertEqual(len(repeated['turns']),1)
            self.assertEqual(repeated['turns'][0]['id'],before['turns'][0]['id'])
            after=observe(database,task_id);save(output/'after-restart.json',after)
            self.assertEqual(after['task'],before['task']);self.assertEqual(after['effects'],before['effects'])
            self.assertEqual(after['ownerTaskCount'],1)
            self.assertEqual(count(workspace/'effect.jsonl'),1);self.assertEqual(count(output/'scripted-calls.jsonl'),calls)
            if mode=='completed':
                continued=request('POST','/research/sessions/'+sid+'/turns',{'requestId':'explicit-next','text':'Explicitly continue; report context without running any command.'})
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    continued=request('GET','/research/sessions/'+sid)
                    if len(continued['turns'])==2 and continued['turns'][-1]['status']=='completed':break
                    time.sleep(.1)
                self.assertEqual(continued['turns'][-1]['status'],'completed',continued)
                self.assertEqual(len(continued['turns']),2)
                self.assertEqual(continued['assistantId'],session['assistantId'])
                self.assertNotEqual(continued['turns'][-1]['taskId'],task_id)
                self.assertNotEqual(continued['turns'][-1]['runId'],before['task']['run_id'])
                self.assertEqual(continued['turns'][0]['id'],before['turns'][0]['id'])
                self.assertEqual(continued['turns'][0]['runId'],before['task']['run_id'])
                self.assertEqual(conn_count(database),2)
                self.assertEqual(continued['turns'][0]['taskId'],task_id)
                self.assertEqual(count(output/'scripted-calls.jsonl'),calls+1)
                self.assertEqual(count(workspace/'effect.jsonl'),1)
                save(output/'explicit-next-turn.json',continued)
            save(output/'result.json',{'status':'PASS','case':mode,'os':os.name,'platform':sys.platform,'python':sys.version,
                'sessionId':sid,'taskId':task_id,'runId':before['task']['run_id'],'pids':server.pids,
                'effectStatus':after['effects'][0]['status'],'effectCount':1,'actualWriteCount':1,
                'scriptedProviderCalls':count(output/'scripted-calls.jsonl'),'externalModelCalls':0,
                'scope':'Actual OS service exit/restart, PostgreSQL and local CLI; fixture internal identity, no browser password/TLS proof.'})

    def test_unknown_original_operation_is_not_replayed_after_hard_exit(self):self.case('unknown')
    def test_done_receipt_survives_hard_exit_without_reexecuting(self):self.case('done')
    def test_completed_session_requires_explicit_next_turn_after_hard_exit(self):self.case('completed')


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--serve':serve(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')))
    else:unittest.main()
