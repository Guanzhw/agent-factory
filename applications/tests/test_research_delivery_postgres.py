"""Real native Workflow/MemberCliAdapter and PG; model choices are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from sqlalchemy import select

from agent_factory.personal_tools import OperationAccountRequest
from agent_factory.application_content import ContentPublication
import test_research_workflow_postgres as native

PROGRAM = '''import json, pathlib, sys
metrics = {"value": sum([1, 2]), "target": 4}
if "--evidence" in sys.argv:
    print(json.dumps({"metrics": metrics, "source": pathlib.Path(__file__).read_text(),
        "recipe": {"command": ["python", "source.py"], "dependencies": "Python standard library", "data": [1, 2],
                   "expected": metrics}, "privateCanary": pathlib.Path("private.txt").read_text()}))
else:
    print(json.dumps(metrics))
'''


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL') and os.name == 'posix', 'Requires isolated PostgreSQL and CLI process support')
class ResearchDeliveryPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = native.ResearchNativeWorkflowTests('runTest')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.state, self.client = self.base.state, self.base.client
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        script = Path(directory.name) / 'experiment.py'
        script.write_text(PROGRAM)
        Path(directory.name, "private.txt").write_text("UNSELECTED_PRIVATE_CANARY")
        service = self.state['store'].personal_tools
        operation = service.operations.create('alice', {'transport': 'cli', 'toolName': 'research_fixture_compute',
            'executable': sys.executable, 'arguments': [str(script), '--evidence'], 'workingDirectory': directory.name,
            'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}, 'evidence-operation')
        self.resource = service.configure_operation('alice', operation['operationRef']['id'], OperationAccountRequest(
            requestId='evidence-account', **{key: operation['operationRef'][key] for key in ('version', 'sha256')}))
        self.connection = self.state['connections'].bind('alice', self.resource['registrationRef'], 'evidence-binding')
        self.operation_ref = operation['operationRef']
        descriptor = operation['descriptor']
        governance = self.state['material_governance']
        material = governance.create_draft('alice', {'id': 'selected-cli-evidence', 'kind': 'tool',
            'name': 'Selected actual CLI', 'content': 'research_fixture_compute', 'permissions': [descriptor['permission']],
            'runtimeBinding': {**operation['runtimeBinding'], 'config': {**operation['runtimeBinding']['config'],
                'connectionName': 'experiment_cli'}}}, 'evidence-material-draft')
        governance.publish('alice', material['id'], material['version'], 'evidence-material-publish')
        self.material = {key: material[key] for key in ('id', 'version', 'sha256')}
        apps = self.state['applications']
        original = apps.require_current(self.base.ref)
        modes = deepcopy(original['modes'])
        for mode in modes.values():
            mode['materialRefs'] = [ref for ref in mode['materialRefs'] if ref['id'] != 'research-fixture-research-fixture-compute'] + [self.material]
            mode['capabilities'] = list(dict.fromkeys(mode['capabilities'] + descriptor['capabilities'] + [descriptor['permission']]))
            mode['connectionRequirements'] = [{'name': 'experiment_cli', 'kind': 'tool', 'requiredCapabilities': descriptor['capabilities']}]
        application = apps.create_draft('alice', {'id': 'selected-cli-research', 'name': 'Actual CLI evidence',
            'defaultMode': 'research', 'modes': modes}, 'evidence-app-draft')
        apps.publish('alice', application['id'], application['version'], 'evidence-app-publish')
        self.ref = {key: application[key] for key in ('id', 'version', 'sha256')}

    def start(self):
        project = self.client.post('/api/factory/research/projects', json={'requestId': 'evidence-project', 'title': 'Actual negative evidence'})
        self.assertEqual(project.status_code, 201, project.text)
        self.project = project.json()['id']
        self.url = '/api/factory/research/projects/' + self.project
        agreement = {'objective': 'Measure sum against target four', 'evaluation': 'Actual value compared with four',
            'stopConditions': 'Stop after one measured attempt', 'budget': {'rounds': 1, 'toolCalls': 32},
            'execution': {'applicationRef': self.ref, 'mode': 'research', 'deadline': time.time() + 180,
                'perRoundCaps': {'rounds': 1, 'toolCalls': 32},
                'connectionRefs': {'experiment_cli': self.connection['ref']}},
            'evidence': {'toolMaterial': self.material, 'fields': {'metrics': 'metrics', 'source': 'source', 'run_recipe': 'recipe'}}}
        for path, body in (('/goals', {'requestId': 'evidence-goal', 'expectedVersion': 0, 'agreement': agreement}),
                           ('/confirm', {'requestId': 'evidence-confirm', 'expectedVersion': 1})):
            result = self.client.post(self.url + path, json=body)
            self.assertEqual(result.status_code, 200, result.text)
        result = self.client.post(self.url + '/start', json={'requestId': 'evidence-start', 'expectedVersion': 1})
        self.assertEqual(result.status_code, 202, result.text)
        self.base.completed(result.json()['execution']['taskId'])
        return result.json()['execution']['taskId']

    def test_real_cli_selected_evidence_and_other_member_reproduction(self):
        task_id = self.start()
        delivery = self.client.post(self.url + '/deliveries', json={'requestId': 'evidence-delivery', 'expectedVersion': 1})
        self.assertEqual(delivery.status_code, 201, delivery.text)
        manifest = delivery.json()
        self.assertEqual(manifest['missingEvidence'], [])
        self.assertNotIn('UNSELECTED_PRIVATE_CANARY', delivery.text)
        self.assertNotIn(self.resource['registrationRef'], delivery.text)
        rounds = self.state['research_rounds']
        with self.state['store'].engine.connect() as conn:
            attempt = dict(conn.execute(select(rounds.legacy.attempts)).mappings().one())
        selection = attempt['selection']
        child_id = selection['provenance']['taskId']
        self.assertNotEqual(child_id, task_id)
        self.assertEqual(selection['provenance']['materialRef'], self.material)
        self.assertEqual(len(selection['artifacts']), 3)
        self.assertIn('UNSELECTED_PRIVATE_CANARY', json.dumps(self.state['store'].effects(child_id)))
        self.client.post('/api/factory/demo/login', json={'persona': 'bob'})
        self.assertEqual(self.client.get('/api/factory/jobs/' + child_id).status_code, 404)
        path = '/api/factory/research/deliveries/' + manifest['id']
        response = self.client.get(path + '/download')
        self.assertEqual(response.status_code, 200, response.text if response.status_code != 200 else '')
        self.assertNotIn(b'UNSELECTED_PRIVATE_CANARY', response.content)
        with ZipFile(BytesIO(response.content)) as bundle:
            evidence = [json.loads(bundle.read(name)) for name in bundle.namelist() if name.startswith('evidence/')]
        values = {item['role']: item['value'] for item in evidence}
        self.assertEqual(values['source'], PROGRAM)
        self.assertEqual(values['metrics'], {'value': 3, 'target': 4})
        with TemporaryDirectory() as clean:
            Path(clean, 'source.py').write_text(values['source'])
            completed = subprocess.run([sys.executable, 'source.py'], cwd=clean, capture_output=True, text=True, timeout=5, check=True)
            self.assertEqual(json.loads(completed.stdout), values['run_recipe']['expected'])
        # Bob continues from the reproducible recipe under a new owner allocation, not Alice's receipt.
        service = self.state['store'].personal_tools
        resource = service.configure_operation('bob', self.operation_ref['id'], OperationAccountRequest(
            requestId='evidence-account', **{key: self.operation_ref[key] for key in ('version', 'sha256')}))
        self.connection = self.state['connections'].bind('bob', resource['registrationRef'], 'evidence-binding')
        continued = self.start()
        self.assertNotEqual(continued, task_id)
        self.assertEqual(self.state['store'].task(continued, 'bob')['owner_id'], 'bob')
        with self.state['store'].engine.connect() as conn:
            original_allocation = conn.execute(select(rounds.rounds.c.allocation_id).where(rounds.rounds.c.task_id == task_id)).scalar_one()
            continued_allocation = conn.execute(select(rounds.rounds.c.allocation_id).where(rounds.rounds.c.task_id == continued)).scalar_one()
        self.assertNotEqual(original_allocation, continued_allocation)
        # Source withdrawal must deny the derived export, not merely remove its link.
        self.state['application_content'].set_visibility('alice', manifest['sourceIds'][0], 'personal', 'withdraw-evidence')
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get(path + '/download').status_code, 404)
        self.assertEqual(self.client.get('/api/factory/research/deliveries').json()['items'], [])
        # No generic content manifest exists to bypass the application check.
        self.assertNotIn('research.delivery', json.dumps(self.state['application_content'].list('bob')))

    def test_manifest_source_withdrawal_is_serial_with_authorized_snapshots(self):
        service = self.state['research_delivery']
        content = self.state['application_content']
        source = content.publish('alice', ContentPublication(source={
            'application': 'research', 'record': 'barrier-source', 'revision': '1'},
            content={'observation': 'shared original'}, visibility='team'), 'barrier-source')
        identifier = str(uuid4())
        with self.state['store'].transaction() as conn:
            conn.execute(service.deliveries.insert().values(id=identifier, owner_id='alice',
                project_id='domain-barrier-fixture', created_at='fixture',
                body={'sourceIds': [source['id']], 'records': [{'summary': 'derived original'}]}))
        held, release, attempted = Event(), Event(), Event()
        original_read = content.read
        def paused_read(*args):
            value = original_read(*args)
            held.set()
            if not release.wait(5): raise AssertionError('read barrier not released')
            return value
        def withdraw():
            attempted.set()
            return content.set_visibility('alice', source['id'], 'personal', 'barrier-withdraw')
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(content, 'read', paused_read):
            snapshot = pool.submit(service.read, 'bob', identifier)
            try:
                self.assertTrue(held.wait(5))
                revoked = pool.submit(withdraw)
                self.assertTrue(attempted.wait(5))
                self.assertFalse(revoked.done())
                release.set()
                self.assertEqual(snapshot.result(5)['records'][0]['summary'], 'derived original')
                revoked.result(5)
            finally:
                release.set()
        from fastapi import HTTPException
        with self.assertRaises(HTTPException): service.read('bob', identifier)
        content.set_visibility('alice', source['id'], 'team', 'barrier-restore')
        held.clear(); release.clear(); attempted.clear()
        original_set = content.sharing.set
        original_lock = service.rounds.scopes.admission_lock
        def paused_set(*args):
            held.set()
            if not release.wait(5): raise AssertionError('withdraw barrier not released')
            return original_set(*args)
        def attempted_lock(conn):
            attempted.set()
            return original_lock(conn)
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(content.sharing, 'set', paused_set):
            revoked = pool.submit(content.set_visibility, 'alice', source['id'], 'personal', 'barrier-withdraw-again')
            try:
                self.assertTrue(held.wait(5))
                with patch.object(service.rounds.scopes, 'admission_lock', attempted_lock):
                    snapshot = pool.submit(service.download, 'bob', identifier)
                    self.assertTrue(attempted.wait(5))
                    self.assertFalse(snapshot.done())
                    release.set()
                    revoked.result(5)
                    with self.assertRaises(HTTPException): snapshot.result(5)
            finally:
                release.set()
