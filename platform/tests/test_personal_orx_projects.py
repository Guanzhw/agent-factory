"""Synthetic pinned ORX creation wire; no clone, provider call or real material."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, parse_qs

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from agent_factory.personal_command_api import PersonalCommandAPI
from agent_factory.personal_command_profile import command_from_plan, validate_intent, PROJECT_APPLICATION_ID, TOOL_NAME
from agent_factory.personal_orx_projects import PersonalOrxProjects, native_request, valid_native_request, ProjectInput, project_review_summary
from agent_factory.personal_orx_transport import PERSONAL_ORX_PROVIDER_ID, PersonalOrxHTTPS
from agent_factory.personal_remote_provider import RemoteConnectionError
from agent_factory.store import canonical
import test_personal_orx_transport as native


class CreationWire(native.NativeOrxWire):
    def __init__(self):
        super().__init__()
        self.projects = {'native-project': {'id': 'native-project', 'name': 'Original native project', 'path': '/native/repo'}}
        self.creation_posts = 0

    def request(self, destination, address, method, path, lease, payload=None):
        route = urlsplit(path).path
        if lease is None or route == '/api/health':
            return super().request(destination, address, method, path, lease, payload)
        if route == '/api/projects' or route.startswith('/api/projects/'):
            assert self.allows(method, path, payload)
            self.calls.append((method, path, deepcopy(payload), True))
            if method == 'POST':
                # Faithful serde camelCase contract. snake_case alone would be
                # ignored by upstream and could inherit a true sync default.
                assert payload['githubSyncEnabled'] is False
                assert payload['github_sync_enabled'] is False
                assert 'githubSync' not in payload and 'idempotencyKey' not in payload
                self.creation_posts += 1
                pid = 'native-created-' + str(self.creation_posts)
                self.projects[pid] = {'id': pid, 'name': payload['name'], 'path': payload['path'], 'githubEnabled': False}
                value = {'project': self.projects[pid], 'githubPublicationError': None}
            elif route == '/api/projects': value = {'projects': list(self.projects.values())}
            else: value = {'project': self.projects[route.split('/')[-1]]}
            if self.echo == route: value['echo'] = 'synthetic-test-password'
            if self.drop == path and method == 'POST':
                self.drop = None
                raise RemoteConnectionError('Synthetic lost project response')
            return 200, deepcopy(value)
        if route == '/api/chat/sessions':
            self.calls.append((method, path, deepcopy(payload), True))
            if method == 'GET':
                project = parse_qs(urlsplit(path).query)['projectId'][0]
                return 200, {'sessions': [deepcopy(r) for r in self.rows.values() if r['projectId'] == project]}
            sid = 'chat_created_' + str(len(self.rows))
            self.rows[sid] = {'id': sid, **deepcopy(payload),
                'permissionMode': payload.get('permissionMode') or 'default',
                'serviceTier': payload.get('serviceTier'), 'reasoningLevel': payload.get('reasoningLevel'),
                'busy': False, 'archived': False, 'title': None, 'goal': None, 'activeLeafId': None}
            self.messages[sid] = []
            return 200, {'session': deepcopy(self.rows[sid])}
        return super().request(destination, address, method, path, lease, payload)


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.fx = native.PersonalOrxTests('test_true_native_existing_attach_multiturn_tool_transcript_and_interrupt')
        self.fx.setUp(); self.addCleanup(self.fx.doCleanups)
        self.wire = CreationWire()
        self.fx.provider._transports = {mode: self.wire for mode in self.fx.provider.auth_modes}
        self.config = {k: v for k, v in self.fx.config.items() if k != 'projectId'} | {'projectCreation': True}
        remote = self.fx.connections.personal.configure('alice', PERSONAL_ORX_PROVIDER_ID, self.config, 'configure-create')
        self.remote = remote['registrationRef']
        self.fx.connections.personal.verify('alice', self.remote, 'verify-create')
        self.bound = self.fx.connections.bind('alice', self.remote, 'bind-create')
        self.service = PersonalOrxProjects(self.fx.connections, admission=self.fx.admission)
        self.values = {'name': 'Synthetic research', 'path': '/synthetic/new-project', 'source': 'clone',
            'cloneUrl': 'https://github.com/synthetic-fixture/example'}

    def prepared(self, request='original-project-create'):
        bundle = self.service.bundle('alice', self.bound['ref'], self.values)
        plan = {'id': 'controlled-plan', 'application': PROJECT_APPLICATION_ID, 'mode': 'personal-command',
            'tools': [TOOL_NAME], 'inputValues': {'executionContract': 'personal-external-v1', 'action': 'project_create',
                'requestId': request, 'connectionPin': canonical(bundle['connectionPin']), 'nativeProjectId': '',
                'nativeSessionId': '', 'factorySessionId': '', 'title': self.values['name'], 'text': canonical(bundle), 'agent': ''}}
        self.service.record('alice', request, plan, bundle)
        return command_from_plan(plan)

    def approved(self, request='original-project-create'):
        command = self.prepared(request)
        self.service.decide('alice', request, command['projectBundle']['previewHash'], True)
        return command

    def test_existing_project_selection_reuses_real_native_template_without_remote_writes(self):
        before = self.wire.creation_posts
        projects = self.service.existing_projects('alice', self.bound['ref'])
        self.assertEqual(projects[0]['nativeProjectId'], 'native-project')
        selected = self.service.select_existing('alice', self.bound['ref'], 'native-project', 'select-real-existing')
        self.assertEqual(selected['ownerId'], 'alice')
        handle = self.fx.connections.resolve('alice', selected['ref'], 'orx', required_capabilities=['session:read'])
        self.assertEqual(handle.configuration['sessionTemplateId'], 'chat_original')
        self.assertTrue(handle.project()['sessionCreationSupported'])
        self.assertEqual(self.service.selected_request('alice', 'select-real-existing')['ref'], selected['ref'])
        self.assertEqual(self.wire.creation_posts, before)
        self.assertFalse(any(call[0] != 'GET' for call in self.wire.calls))
        with self.assertRaises(HTTPException): self.service.select_existing('bob', self.bound['ref'], 'native-project', 'foreign-selection')
        with self.assertRaises(HTTPException): self.service.selected_request('bob', 'select-real-existing')
        with self.assertRaises(HTTPException): self.service.select_existing('alice', self.bound['ref'], 'not-listed', 'unknown-project')
        replay = self.service.select_existing('alice', self.bound['ref'], 'native-project', 'select-real-existing')
        self.assertEqual(replay['ref'], selected['ref'])
        self.fx.connections.revoke('alice', self.bound['ref'], 'revoke-setup-source')
        with self.assertRaises(HTTPException): self.service.select_existing('alice', self.bound['ref'], 'native-project', 'revoked-selection')

    def test_selection_rejected_before_setup_survives_refresh_and_never_replays(self):
        key = 'missing-project-selection'
        with self.assertRaises(HTTPException) as error:
            self.service.select_existing('alice', self.bound['ref'], 'missing-project', key)
        self.assertEqual(error.exception.status_code, 404)
        restarted = PersonalOrxProjects(self.fx.connections, admission=self.fx.admission)
        status = restarted.selection_status('alice', key)
        self.assertEqual((status['state'], status['localConfiguration'], status['failureStatus']), ('failed', 'none', 404))
        calls = len(self.wire.calls)
        with self.assertRaises(HTTPException): restarted.select_existing('alice', self.bound['ref'], 'missing-project', key)
        self.assertEqual(len(self.wire.calls), calls)
        with self.assertRaises(HTTPException): restarted.select_existing('alice', self.bound['ref'], 'native-project', key)
        with self.assertRaises(HTTPException) as foreign: restarted.selection_status('bob', key)
        self.assertEqual(foreign.exception.status_code, 404)
        selected = restarted.select_existing('alice', self.bound['ref'], 'native-project', 'explicit-new-selection')
        self.assertEqual(selected['ownerId'], 'alice')

    def test_selection_permission_rejection_has_terminal_read_only_receipt(self):
        require = self.service.auth.require
        def denied(owner, action):
            if action == 'run': raise HTTPException(403, 'Synthetic permission rejected')
            return require(owner, action)
        with patch.object(self.service.auth, 'require', side_effect=denied):
            with self.assertRaises(HTTPException) as error:
                self.service.select_existing('alice', self.bound['ref'], 'native-project', 'denied-selection')
            self.assertEqual(error.exception.status_code, 403)
            status = self.service.selection_status('alice', 'denied-selection')
        self.assertEqual((status['state'], status['localConfiguration'], status['failureStatus']), ('failed', 'none', 403))

    def test_partial_validation_failure_is_terminal_but_retains_local_configuration(self):
        with patch.object(self.fx.connections.personal, 'verify', side_effect=HTTPException(409, 'synthetic-private-secret')):
            with self.assertRaises(HTTPException):
                self.service.select_existing('alice', self.bound['ref'], 'native-project', 'partial-selection')
        status = self.service.selection_status('alice', 'partial-selection')
        self.assertEqual((status['state'], status['localConfiguration']), ('failed', 'partial'))
        self.assertNotIn('synthetic-private-secret', json.dumps(status))
        self.assertIsNone(status['connection'])
        self.assertFalse(any(call[0] != 'GET' for call in self.wire.calls))

    def test_lost_or_interrupted_configuration_is_unknown_not_nonexecution(self):
        with patch.object(self.fx.connections.personal, 'verify', side_effect=RuntimeError('synthetic loss')):
            with self.assertRaises(RuntimeError):
                self.service.select_existing('alice', self.bound['ref'], 'native-project', 'unknown-selection')
        status = self.service.selection_status('alice', 'unknown-selection')
        self.assertEqual((status['state'], status['localConfiguration']), ('unknown', 'partial'))
        calls = len(self.wire.calls)
        with self.assertRaises(HTTPException):
            self.service.select_existing('alice', self.bound['ref'], 'native-project', 'unknown-selection')
        self.assertEqual(len(self.wire.calls), calls)
        with self.assertRaises(HTTPException) as absent: self.service.selection_status('alice', 'absent-selection')
        self.assertEqual(absent.exception.status_code, 404)

    def test_final_binding_recovers_after_process_loss_before_selection_completion(self):
        with patch.object(self.service, '_selection_state', side_effect=RuntimeError('synthetic lost completion')):
            with self.assertRaises(RuntimeError):
                self.service.select_existing('alice', self.bound['ref'], 'native-project', 'final-selection')
        calls = len(self.wire.calls)
        status = self.service.selection_status('alice', 'final-selection')
        self.assertEqual(status['state'], 'complete')
        self.assertEqual(status['connection']['ownerId'], 'alice')
        self.assertEqual(len(self.wire.calls), calls)

    def test_preview_consent_sync_false_and_existing_session_research_chain(self):
        command = self.prepared()
        receipt = self.service.request_result('alice', command['requestId'])
        self.assertEqual(receipt['consentState'], 'awaiting')
        self.assertTrue(receipt['preview']['disclosure']['clone'])
        self.assertEqual(receipt['preview']['disclosure']['remotePath'], self.values['path'])
        self.assertEqual(receipt['preview']['disclosure']['billing'], 'owner-remote-account-possible-cost')
        self.assertFalse(receipt['preview']['disclosure']['automaticExperiment'])
        with self.assertRaises(HTTPException): self.service.create('alice', command)
        self.assertEqual(self.wire.creation_posts, 0)
        self.service.decide('alice', command['requestId'], command['projectBundle']['previewHash'], True)
        result = self.service.create('alice', command)
        self.assertEqual(result['state'], 'acknowledged')
        self.assertEqual(result['result']['nativeProjectId'], 'native-created-1')
        new = self.service.connect('alice', command['requestId'], harness='opencode', model='owner/model')
        project = self.service.sessions.project('alice', new['ref'])
        self.assertTrue(project['sessionCreationSupported'])
        self.assertNotIn('project:create', new['capabilities'])
        session = self.service.sessions.create('alice', new['ref'], 'native-created-1', 'create-new-chat', title='Research')
        self.assertEqual(session['state'], 'acknowledged')
        sid = session['session']['id']
        prompted = self.service.sessions.prompt('alice', sid, 'Synthetic research question', 'send-research')
        self.assertEqual(prompted['state'], 'acknowledged')
        observed = self.service.sessions.inspect('alice', sid, refresh=True)
        self.assertEqual(observed['observation']['messages'][-1]['events'][-1]['text'], 'Native answer 1')
        self.assertFalse(observed['liveEndToEndVerified'])
        self.assertEqual(self.wire.creation_posts, 1)

    def test_cancel_and_changed_disclosure_never_dispatch(self):
        command = self.prepared()
        with self.assertRaises(HTTPException): self.service.decide('alice', command['requestId'], '0'*64, True)
        self.service.decide('alice', command['requestId'], command['projectBundle']['previewHash'], False)
        with self.assertRaises(HTTPException): self.service.decide('alice', command['requestId'], command['projectBundle']['previewHash'], True)
        with self.assertRaises(HTTPException): self.service.create('alice', command)
        self.assertEqual(self.wire.creation_posts, 0)

    def test_lost_response_restart_and_read_only_candidates_never_settle_or_resend(self):
        command = self.approved(); self.wire.drop = '/api/projects'
        original = self.service.create('alice', command)
        self.assertEqual(original['state'], 'ack_unknown')
        restarted = PersonalOrxProjects(self.fx.connections, admission=self.fx.admission)
        recovered = restarted.request_result('alice', command['requestId'], refresh=True)
        self.assertEqual(recovered['state'], 'ack_unknown')
        self.assertEqual(recovered['candidates'][0]['nativeProjectId'], 'native-created-1')
        self.assertEqual(recovered['candidateCorrelation'], 'unproven-does-not-settle-original-request')
        self.assertEqual(restarted.create('alice', command)['state'], 'ack_unknown')
        with self.assertRaises(HTTPException): restarted.connect('alice', command['requestId'], harness='opencode', model='owner/model')
        with self.assertRaises(HTTPException): restarted.decide('alice', command['requestId'], command['projectBundle']['previewHash'], False)
        self.assertEqual(self.wire.creation_posts, 1)
        self.assertEqual(recovered['factoryIdentity'], original['factoryIdentity'])

    def test_double_click_concurrent_reservation_dispatches_once(self):
        # SQLite fixture serializes only metadata. Real PG advisory lock races
        # are required separately by the CI boundary gate.
        command = self.approved()
        entered, release = threading.Event(), threading.Event()
        transport_request = self.wire.request
        def request(*args, **kwargs):
            if args[2:4] == ('POST', '/api/projects'):
                entered.set(); release.wait(5)
            return transport_request(*args, **kwargs)
        self.wire.request = request
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.service.create, 'alice', command)
            self.assertTrue(entered.wait(5))
            second = self.service.create('alice', command)
            self.assertEqual(second['state'], 'ack_unknown')
            release.set(); self.assertEqual(first.result()['state'], 'acknowledged')
        self.assertEqual(self.wire.creation_posts, 1)

    def test_owner_revocation_expiry_and_cancellation_after_blocking_dns_fail_closed(self):
        command = self.approved()
        with self.assertRaises(HTTPException): self.service.request_result('bob', command['requestId'])
        with self.assertRaises(HTTPException): self.service.decide('bob', command['requestId'], command['projectBundle']['previewHash'], True)
        at = self.fx.connections._at(); self.fx.connections.clock = lambda: at + timedelta(minutes=16)
        with self.assertRaises(HTTPException): self.service.create('alice', command)
        self.fx.connections.clock = lambda: at
        addresses = []
        def cancel_before_post():
            addresses.append(True)
            if len(addresses) == 2:
                self.service.decide('alice', command['requestId'], command['projectBundle']['previewHash'], False)
        self.wire.before_address = cancel_before_post
        self.service.create('alice', command)
        self.assertEqual(self.wire.creation_posts, 0)

    def test_secret_echo_is_not_persisted_or_accepted(self):
        command = self.approved(); self.wire.echo = '/api/projects'
        # Echo during the pre-send list must not reach durable metadata.
        with self.assertRaises(RemoteConnectionError): self.service.create('alice', command)
        self.assertEqual(self.wire.creation_posts, 0)
        self.assertNotIn('synthetic-test-password', json.dumps(self.service.request_result('alice', command['requestId'])))

    def test_post_secret_echo_preserves_unknown_original_instead_of_accepting_or_replaying(self):
        command = self.approved(); original = self.wire.request
        def echo(*args, **kwargs):
            status, value = original(*args, **kwargs)
            if args[2:4] == ('POST', '/api/projects'): value['echo'] = 'synthetic-test-password'
            return status, value
        self.wire.request = echo
        result = self.service.create('alice', command)
        self.assertEqual(result['state'], 'ack_unknown')
        self.assertIsNone(result['result'])
        self.assertNotIn('synthetic-test-password', json.dumps(result))
        self.service.create('alice', command)
        self.assertEqual(self.wire.creation_posts, 1)

    def test_configuration_revision_and_secret_revocation_during_post_dns_prevent_send(self):
        for scenario in ('configuration', 'secret'):
            fixture = ProjectTests('test_cancel_and_changed_disclosure_never_dispatch')
            fixture.setUp()
            try:
                command = fixture.approved(); addresses = []
                def revoke():
                    addresses.append(True)
                    if len(addresses) != 2: return
                    if scenario == 'configuration':
                        fixture.fx.connections.personal.configure('alice', PERSONAL_ORX_PROVIDER_ID,
                            fixture.config, 'replace-creation-config', reference=fixture.remote)
                    else:
                        fixture.fx.secrets.authorize = lambda **_: False
                fixture.wire.before_address = revoke
                result = fixture.service.create('alice', command)
                self.assertEqual(result['state'], 'ack_unknown')
                self.assertEqual(fixture.wire.creation_posts, 0)
            finally:
                fixture.doCleanups()

    def test_strict_sources_side_effect_flags_and_original_project_binding(self):
        for source, fields in [('empty', {}), ('existing', {}), ('paper', {'paperId': '2601.12345'})]:
            request = native_request({'name': 'Synthetic', 'path': '/synthetic/project', 'source': source, **fields})
            self.assertTrue(valid_native_request(request))
            for changed in ({'githubSyncEnabled': True}, {'github_sync_enabled': True}, {'githubSyncEnabled': 0}, {'runCommand': 'unapproved'}, {'idempotencyKey': 'fake'}):
                self.assertFalse(PersonalOrxHTTPS.allows('POST', '/api/projects', {**request, **changed}))
        for value in ({**self.values, 'path': 'relative'}, {**self.values, 'cloneUrl': 'https://token@github.com/a/b'},
                {**self.values, 'paperId': '2601.12345'}, {**self.values, 'runCommand': 'execute'}):
            with self.assertRaises(ValueError): ProjectInput.model_validate(value)
        original = self.fx.handle()
        with self.assertRaises(RemoteConnectionError): original.create_project(native_request(self.values), before_send=lambda: None)
        self.assertNotIn('project:create', self.fx.bound['capabilities'])
        bundle = self.prepared()['projectBundle']
        intent = {'executionContract': 'personal-external-v1', 'action': 'project_create', 'requestId': 'original-project-create',
            'connectionPin': bundle['connectionPin'], 'projectBundle': bundle, 'baselineProjectIds': []}
        command = self.prepared(); validate_intent(command, intent)
        with self.assertRaises(HTTPException): validate_intent(command, {**intent, 'projectBundle': {**bundle, 'request': {'githubSyncEnabled': True}}})

    def test_clone_existing_empty_directory_discloses_actual_write_scope(self):
        # Controlled peer mirrors the upstream clone branch using a marker,
        # never a Git subprocess, remote repository or project material.
        with TemporaryDirectory() as folder:
            target = Path(folder) / 'already-empty'
            target.mkdir()
            self.values = {**self.values, 'path': str(target)}
            command = self.prepared()
            d = command['projectBundle']['disclosure']
            self.assertEqual(d['version'], 'native-orx-create-consent-v2')
            self.assertEqual(d['remotePath'], str(target))
            self.assertEqual(d['remoteWrites'], 'clone-into-new-or-existing-empty-folder-and-project')
            self.assertEqual(d['pathResolution'], 'upstream-clone-target-symlinks-followed-no-new-folder-guarantee')
            self.assertTrue(target.is_dir()); self.assertEqual(list(target.iterdir()), [])
            original = self.wire.request
            def clone_into_empty(*args, **kwargs):
                if args[2:4] == ('POST', '/api/projects'):
                    payload = args[5]
                    self.assertEqual(payload['path'], str(target))
                    self.assertTrue(payload['requireNewFolder'])  # Ignored by upstream clone branch.
                    self.assertEqual(list(target.iterdir()), [])
                    (target / 'synthetic-clone-marker').write_text('Controlled clone fixture')
                return original(*args, **kwargs)
            self.wire.request = clone_into_empty
            self.service.decide('alice', command['requestId'], command['projectBundle']['previewHash'], True)
            self.assertEqual(self.service.create('alice', command)['state'], 'acknowledged')
            self.assertTrue((target / 'synthetic-clone-marker').is_file())
            self.assertEqual(self.wire.creation_posts, 1)

    def test_review_summary_uses_immutable_inputs_without_credential_projection_or_remote_io(self):
        for source, extra in [('empty', {}), ('existing', {}), ('clone', {'cloneUrl': 'https://github.com/synthetic-fixture/example'}),
                ('paper', {'paperId': '2601.12345'})]:
            self.values = {'name': 'Synthetic ' + source, 'path': '/synthetic/' + source, 'source': source, **extra}
            command = self.prepared('review-' + source)
            values = {k: v for k, v in command.items() if k != 'projectBundle'}
            values.update(connectionPin=canonical({**command['connectionPin'], 'credentialRef': 'synthetic-private-reference'}),
                nativeSessionId='', agent='')
            bundle = deepcopy(command['projectBundle'])
            bundle['connectionPin']['credentialRef'] = 'synthetic-private-reference'
            from agent_factory.store import digest
            bundle['previewHash'] = digest({k: v for k, v in bundle.items() if k != 'previewHash'})
            values['text'] = canonical(bundle)
            plan = {'id': 'controlled-plan', 'application': PROJECT_APPLICATION_ID, 'mode': 'personal-command',
                'tools': [TOOL_NAME], 'inputValues': values}
            before = deepcopy(plan); calls = len(self.wire.calls)
            summary = project_review_summary(plan)
            self.assertEqual(summary['project'], {'name': self.values['name'], 'path': self.values['path'], 'source': source,
                'cloneUrl': extra.get('cloneUrl'), 'paperId': extra.get('paperId')})
            self.assertEqual(summary['effects'], bundle['disclosure'])
            self.assertEqual(summary['previewHash'], bundle['previewHash'])
            self.assertEqual(summary['billing']['controllerLedgerScope'], 'local-controller-only')
            self.assertEqual(summary['billing']['remoteCostStatus'], 'unknown')
            self.assertEqual(summary['billing']['remoteUsageStatus'], 'unknown')
            self.assertFalse(summary['billing']['remoteCostIncludedInUsageBudget'])
            self.assertTrue(summary['ownerConsentSeparate'])
            self.assertNotIn('synthetic-private-reference', json.dumps(summary))
            self.assertNotIn('connectionPin', summary)
            self.assertEqual(plan, before); self.assertEqual(len(self.wire.calls), calls)
            changed = deepcopy(plan)
            changed['inputValues']['text'] = canonical({**bundle, 'disclosure': {**bundle['disclosure'], 'hardBudgetEnforced': True}})
            with self.assertRaises(HTTPException): project_review_summary(changed)


class ProjectAPITests(unittest.TestCase):
    setUp = ProjectTests.setUp
    prepared = ProjectTests.prepared
    def test_owner_ingress_strict_decision_and_no_direct_dispatch(self):
        command = self.prepared()
        api = PersonalCommandAPI.__new__(PersonalCommandAPI)
        api.auth = Mock(); api.auth.user.return_value = {'id': 'alice'}
        api.projects = self.service; api.store = Mock(); api.factory = Mock(); api.sessions = Mock()
        api.router = APIRouter(prefix='/api/factory/personal-agent'); api.routes()
        app = FastAPI(); app.include_router(api.router)
        with TestClient(app) as client:
            base = '/api/factory/personal-agent/project-commands/' + command['requestId']
            response = client.get(base)
            self.assertEqual(response.status_code, 200, response.text)
            for extra in ({'ownerId': 'bob'}, {'approved': 'true'}):
                result = client.post(base + '/decision', json={'previewHash': command['projectBundle']['previewHash'], 'approved': True, **extra})
                self.assertEqual(result.status_code, 422)
            result = client.post(base + '/decision', json={'previewHash': command['projectBundle']['previewHash'], 'approved': True})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(self.wire.creation_posts, 0)
            self.assertEqual(api.factory.mock_calls, [])
            api.auth.user.return_value = {'id': 'bob'}
            self.assertEqual(client.get(base).status_code, 404)
