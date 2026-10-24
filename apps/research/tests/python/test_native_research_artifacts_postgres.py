"""Actual native Agno task, owner ingress, SQL bytes and protected download.

Only synthetic native responses and local fixture files; no provider/model IO.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from agent_factory_research.config import ResearchSettings as Settings
from agent_factory_server.main import create_app
from agent_factory_research.personal_command_profile import publish_application
from pg_fixture import IsolatedPostgres
from test_native_research_artifacts import ArtifactFixtureProvider, ArtifactWire
from test_personal_agent_sessions import Secrets


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Required isolated native PostgreSQL fixture')
class NativeArtifactPostgresTests(unittest.TestCase):
    def test_real_native_task_registers_general_files_once_and_protects_owner_bytes_and_stale_turns(self):
        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database, TemporaryDirectory() as folder:
            root = Path(folder); files = root/'fixture-native-files'; files.mkdir()
            (files/'reports').mkdir(); (files/'reports/summary.tsv').write_text('item\tvalue\nA\t7\n')
            (files/'empty.txt').write_bytes(b'')
            wire = ArtifactWire(files)
            provider = ArtifactFixtureProvider(Secrets(), transport=wire)
            app = create_app(Settings(db_url=database.url, workspace=root/'factory', max_workers=1,
                temporary_policy='member-self-service',
                personal_agent_commands_enabled=True, personal_connection_providers={provider.provider_id: provider}))
            state = app.app.state.factory; store, auth = state['store'], state['auth']
            self.addCleanup(store.engine.dispose); self.addCleanup(store.native_db.db_engine.dispose)
            publish_application(state, author='manager')
            remote = store.connections.personal.configure('alice',provider.provider_id,
                {'origin':'https://runtime.example.com','credentialRef':'synthetic-reference','credentialRevision':'r1',
                    'projectId':'native-project','authMode':'basic-proxy'},'artifact-configure')
            store.connections.personal.verify('alice',remote['registrationRef'],'artifact-verify')
            bound = store.connections.bind('alice',remote['registrationRef'],'artifact-bind')
            with TestClient(app) as client:
                def request(method,path,body=None,owner='alice',expected=200):
                    response=client.request(method,'/api/factory'+path,json=body,
                        headers={'Authorization':'Bearer '+auth._issue_native_token(owner)})
                    self.assertEqual(response.status_code,expected,response.text)
                    return response
                attached=request('POST','/personal-agent/sessions/attach',{'connectionRef':bound['ref'],
                    'nativeProjectId':'native-project','nativeSessionId':'chat_original','requestId':'artifact-attach'}).json()
                sid=attached['session']['id']
                key='artifact-prompt-'+uuid4().hex
                submitted=request('POST','/personal-agent/commands/submit',{'requestId':key,'action':'prompt',
                    'sessionId':sid,'text':'Produce arbitrary native outputs; no filename is mentioned in the chat.'},expected=202).json()
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    detail=request('GET','/jobs/'+submitted['id']).json()
                    if detail['job']['status']=='completed' and store.task(submitted['id'])['terminal']: break
                    if detail['job']['status']=='failed': self.fail(str(detail))
                    time.sleep(.05)
                self.assertTrue(store.task(submitted['id'])['terminal'])
                observed=request('GET','/personal-agent/sessions/'+sid+'?refresh=true').json()
                self.assertIsNone(observed['activeRequestId'])
                path='/personal-agent/tasks/'+submitted['id']+'/artifacts'
                body={'commandRequestId':key,'expectedFingerprint':observed['connectionPin']['fingerprint']}
                request('POST',path,body,owner='bob',expected=404)
                request('POST',path,{**body,'hostPath':str(files)},expected=422)
                request('POST',path,{**body,'expectedFingerprint':'0'*64},expected=409)
                calls=wire.prompts
                with ThreadPoolExecutor(max_workers=2) as pool:
                    captures=list(pool.map(lambda _:request('POST',path,body).json(),range(2)))
                self.assertEqual([a['id'] for a in captures[0]['artifacts']],[a['id'] for a in captures[1]['artifacts']])
                self.assertEqual(len(store.artifacts(submitted['id'])),2)
                self.assertEqual(wire.prompts,calls)
                for artifact in captures[0]['artifacts']:
                    source=files/artifact['provenance']['sourcePath']
                    self.assertEqual(artifact['sha256'],hashlib.sha256(source.read_bytes()).hexdigest())
                    self.assertFalse(artifact['provenance']['scientificConclusionVerified'])
                    url='/jobs/'+submitted['id']+'/artifacts/'+artifact['id']
                    downloaded=request('GET',url)
                    self.assertEqual(downloaded.content,source.read_bytes())
                    self.assertEqual(downloaded.headers['X-Content-SHA256'],artifact['sha256'])
                    request('GET',url,owner='bob',expected=404)
                # The task's existing total-byte budget applies across repeated captures.
                (files/'huge.txt').write_bytes(b'x'*(store.settings.experiment_output_bytes+1))
                limited=request('POST',path,body).json()
                self.assertTrue(any(x['reason']=='OUTPUT_BYTE_LIMIT' for x in limited['skipped']))
                self.assertEqual(len(store.artifacts(submitted['id'])),2)
                # Unknown custody cannot become a file import or a prompt replay.
                store.sql('UPDATE af_personal_agent_commands SET state=:state WHERE request_id=:id',state='ack_unknown',id=key)
                before=len(wire.file_calls)
                request('POST',path,body,expected=409)
                self.assertEqual(len(wire.file_calls),before); self.assertEqual(wire.prompts,calls)
                store.sql('UPDATE af_personal_agent_commands SET state=:state WHERE request_id=:id',state='result_observed',id=key)
                # Current connection revocation blocks capture but retained bytes remain downloadable.
                store.connections.revoke('alice',bound['ref'],'artifact-revoke')
                response=client.post('/api/factory'+path,json=body,headers={'Authorization':'Bearer '+auth._issue_native_token('alice')})
                self.assertIn(response.status_code,(403,409))
                self.assertEqual(len(store.artifacts(submitted['id'])),2); self.assertEqual(wire.prompts,calls)
                artifact=captures[0]['artifacts'][0]
                request('GET','/jobs/'+submitted['id']+'/artifacts/'+artifact['id'])
