"""Actual Linux ORX through reviewed composition and receiver-local mappings.

Two real Factory/native PostgreSQL apps; transport is explicitly ASGI loopback,
not a deployed remote host. No provider, external network or paid computation.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from pg_fixture import IsolatedPostgres
from agent_factory.main import create_app
from agent_factory.local_orx_profile import local_profile_settings, publish_local_orx_application, REGISTRATION_REF
from agent_factory.orx_experiment_tools import TOOL_NAMES, reclaim_orx_experiment
from agent_factory.orx_local import TaskLocalORXProvider
from agent_factory.remote_handoff import HandoffTarget, TrustedHandoffClient, TrustedOrigin, PreparedHandoffService
from agent_factory.remote_bindings import TrustedRemoteBindingMapping, RemoteBindingService


@unittest.skipUnless(os.getenv('FACTORY_ORX_LINUX_CONTAINER') == '1' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires explicit pinned Linux ORX/container and isolated PostgreSQL')
class ActualORXReceiverTests(unittest.TestCase):
    def test_reviewed_receiver_runs_with_disjoint_least_capability_connections(self):
        directory = tempfile.TemporaryDirectory(prefix='factory-orx-receiver-')
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        def clean_containers():
            for marker in root.rglob('factory-linux-container.json'):
                saved = json.loads(marker.read_text())
                value = json.loads(subprocess.check_output(['docker', 'inspect', saved['containerId']], text=True))[0]
                self.assertEqual(value['Config']['Labels']['agent-factory.orx-spec'], saved['specSha256'])
                self.assertIn(str(marker.parent), [item['Source'] for item in value['Mounts'] if item['RW']])
                if value['State']['Running']:
                    subprocess.run(['docker', 'kill', saved['containerId']], capture_output=True, check=True)
                subprocess.run(['docker', 'rm', saved['containerId']], capture_output=True, check=True)
        self.addCleanup(clean_containers)
        provider = TaskLocalORXProvider(binary=Path(os.environ['FACTORY_ORX_BINARY']),
            source_archive=Path(os.environ['FACTORY_ORX_SOURCE_ARCHIVE']), git_binary=Path(os.environ['FACTORY_ORX_GIT_BINARY']), python_binary=Path(sys._base_executable))
        states = []; apps = []; settings_list = []; pins = []
        for role in ('origin', 'receiver'):
            database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
            self.addCleanup(database.__exit__, None, None, None)
            settings = local_profile_settings(db_url=database.url, workspace=root/role, provider=provider, contract_revision='2')
            settings.queue_poll = .2
            app = create_app(settings); state = app.app.state.factory
            self.addCleanup(state['store'].engine.dispose)
            self.addCleanup(state['store'].native_db.db_engine.dispose)
            state['auth'].authorization.unassign('bob', 'factory-user')
            state['auth'].authorization.assign('bob', 'factory-manager')
            current = {}
            for name, cap in (('localExperimentRead', 'research:read'), ('localExperimentRun', 'compute:local')):
                current[name] = state['connections'].bind('alice', REGISTRATION_REF, role + '-' + name, capabilities=[cap])
            states.append(state); apps.append(app); pins.append(current); settings_list.append(settings)
        origin, receiver = states
        application = publish_local_orx_application(origin, author='manager', reviewer='bob', contract_revision='2')
        publish_local_orx_application(receiver, author='manager', reviewer='bob', contract_revision='2', source_application=application)
        target = HandoffTarget('receiver', 'actual-orx-origin', 'http://receiver.factory.invalid', {'alice': 'alice'},
            lambda owner: {'Authorization': 'Bearer ' + receiver['auth']._issue_native_token('alice')},
            transport=httpx.ASGITransport(app=apps[1]))
        handoff = TrustedHandoffClient(origin['store'], origin['auth'], {'receiver': target}); handoff.install_guard()
        trusted = TrustedOrigin('actual-orx-origin', {'alice': 'alice'}, handoff.authority_callback,
            capabilities=frozenset({'research:read', 'compute:local'}), tools=frozenset(TOOL_NAMES),
            budget={'toolCalls': 8, 'maxDepth': 1, 'maxChildren': 1, 'experimentSeconds': 30, 'outputBytes': 65536},
            configuration_revision='actual-orx-contract-v2', tool_contract='orx-evidence-v2')
        service = PreparedHandoffService(receiver['store'], receiver['auth'], receiver['bridge'], {'actual-orx-origin': trusted})
        service.install_guard(); apps[1].app.include_router(service.router)
        clients = [TestClient(app).__enter__() for app in apps]
        for client in clients: self.addCleanup(client.__exit__, None, None, None)
        def request(index, method, path, body=None, owner='alice'):
            token = states[index]['auth']._issue_native_token(owner)
            response = clients[index].request(method, '/api/factory'+path, json=body, headers={'Authorization':'Bearer '+token})
            self.assertTrue(response.is_success, response.text)
            return response.json()
        def post(index, path, body, owner='alice'):
            return request(index, 'POST', path, {'requestId':str(uuid4()), **body}, owner)
        proposal = post(0, '/compositions/proposals', {'goal':'Reviewed receiver-local ORX toy experiment', 'mode':'success',
            'applicationRef':{k:application[k] for k in ('id','version','sha256')},
            'connectionRefs':{name:pin['ref'] for name,pin in pins[0].items()}})
        self.assertEqual(proposal['candidate']['status'], 'ready', proposal)
        plan = post(0, '/compositions/proposals/'+proposal['id']+'/accept', {})
        review = post(0, '/plan-reviews', {'planId':plan['id']})
        post(0, '/plan-reviews/'+review['id']+'/decision', {'approved':True}, 'manager')
        mappings = {}
        for spec in plan['executionBindings']['tools']:
            name = spec['config']['connectionName']
            pin = pins[1][name]
            effective = {**copy.deepcopy(spec), 'connection':{key:copy.deepcopy(pin[key]) for key in spec['connection']}}
            mapping = TrustedRemoteBindingMapping('actual-map-'+spec['toolName'], '2', trusted.reference,
                'alice', 'alice', 'tool', spec, effective)
            mappings[mapping.reference] = mapping
            self.assertEqual(set(effective['connection']['capabilities']), {'compute:local'} if name.endswith('Run') else {'research:read'})
        receiver['store'].remote_bindings = RemoteBindingService(receiver['store'], receiver['auth'], receiver['execution_bindings'], receiver['connections'], mappings)
        row = handoff.reserve('alice', plan['id'], 'receiver', str(uuid4()))
        pending = clients[0].portal.call(handoff.prepare, 'alice', row['task_id'])
        self.assertTrue(pending['receiverReviewRequired'])
        review = post(1, '/plan-reviews', {'planId':pending['remotePlanId']})
        post(1, '/plan-reviews/'+review['id']+'/decision', {'approved':True}, 'manager')
        prepared = clients[0].portal.call(handoff.prepare, 'alice', row['task_id'])
        receipt = clients[0].portal.call(handoff.dispatch, 'alice', row['task_id'])
        task = receipt['remoteTaskId']
        def reclaim():
            clients[1].portal.call(reclaim_orx_experiment, settings_list[1], receiver['store'], task)
        self.addCleanup(reclaim)
        def wait(statuses):
            deadline=time.monotonic()+100
            while time.monotonic()<deadline:
                detail=request(1,'GET','/jobs/'+task)
                if detail['job']['status'] in statuses:return detail
                time.sleep(.1)
            self.fail(str(detail))
        paused=wait({'waiting_approval','failed','unknown'})
        self.assertEqual(paused['job']['status'],'waiting_approval',paused)
        approval=paused['job']['approvalDetail']
        request(1,'POST','/jobs/'+task+'/approve',{'requirementId':approval['id'],'version':approval['version'],'approved':True})
        final=wait({'completed','failed','unknown','canceled'})
        self.assertEqual(final['job']['status'],'completed', {'status':final['job']['status'], 'events':final.get('events', [])[-3:], 'orxStatus':(final.get('orxExperiment') or {}).get('status')})
        result=final['orxExperiment']
        self.assertEqual(result['status'],'done')
        self.assertTrue(result['stopEvidence']['allStopped'])
        self.assertEqual(result['evaluation']['candidate'],{'value':0.0})
        self.assertEqual(len(receiver['store'].sql('SELECT * FROM af_orx_task_experiments WHERE task_id=:task',task=task)),1)
        self.assertEqual(prepared['receiverBindingProof']['sha256'], pending['receiverBindingProof']['sha256'])
        self.assertEqual(origin['store'].task(row['task_id'])['run_id'],None)
        final_reclaim=clients[1].portal.call(reclaim_orx_experiment, settings_list[1], receiver['store'], task)
        self.assertTrue(final_reclaim['stopEvidence']['allStopped'])
