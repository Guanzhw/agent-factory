"""Pinned upstream wire fixtures only. No ORX daemon, harness or paid model."""
import json
import unittest
from unittest.mock import Mock

import httpx

from agent_factory.orx_research_session import OpenResearchSessionHTTP, OrxSessionError, OrxSessionUnknown, UPSTREAM_COMMIT
from agent_factory.orx_workspace_adapter import OpenResearchWorkspaceAdapter, SessionProfile


def project(**changes):
    return {'id': 'native-project', 'name': 'Fixture project', 'slug': 'fixture',
            'repoPath': '/owned/source', 'path': '/owned/source', **changes}


def session(**changes):
    return {'id': 'chat-original', 'projectId': 'native-project', 'harness': 'opencode',
            'model': 'fixture/model', 'permissionMode': 'default', 'busy': False, 'archived': False,
            'serviceTier': 'default', 'planMode': False, 'reasoningLevel': 'medium', **changes}


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.requests = []
        self.authorize = Mock(return_value=True)
        self.rows = [project()]
        self.single = project()
        self.session = session()
        self.handler = None

    def wire(self, request):
        self.requests.append(request)
        self.assertEqual(request.url.host, '127.0.0.1')
        self.assertNotIn('authorization', request.headers)
        self.assertNotIn('cookie', request.headers)
        if self.handler:
            return self.handler(request)
        if request.url.path == '/api/projects':
            return httpx.Response(200, json={'projects': self.rows})
        if request.url.path == '/api/projects/native-project':
            return httpx.Response(200, json={'project': self.single})
        if request.url.path == '/api/chat/sessions':
            return httpx.Response(200, json={'session': self.session} if request.method == 'POST'
                                  else {'sessions': [self.session]})
        self.fail('Unexpected upstream path')

    def adapter(self, **changes):
        return OpenResearchWorkspaceAdapter(**{
            'owner_id': 'alice', 'port': 38123, 'project_paths': {'native-project': '/owned/source'},
            'session_profiles': {'reviewed': SessionProfile('opencode', 'fixture/model', 'default', 'default', 'medium', False)},
            'authorize': self.authorize, 'upstream_revision': UPSTREAM_COMMIT, 'owner_exclusive': True,
            'transport': httpx.MockTransport(self.wire), **changes})

    async def test_real_native_ids_are_returned_without_shadow_create_or_project_mutation(self):
        adapter = self.adapter()
        listed = await adapter.list_projects('alice')
        inspected = await adapter.inspect_project('alice', 'native-project')
        self.assertEqual(listed, [inspected])
        self.assertEqual(inspected['id'], 'native-project')
        self.assertEqual(len(inspected['projectIdentityHash']), 64)
        self.assertNotIn('sourceSha256', inspected)
        self.assertNotIn('repoPath', inspected)
        self.assertEqual([r.method for r in self.requests], ['GET', 'GET'])
        self.assertEqual(self.authorize.call_count, 4)

    async def test_foreign_owner_and_unconfigured_project_fail_before_network(self):
        adapter = self.adapter()
        for owner, identifier in [('bob', 'native-project'), ('alice', 'unconfigured'), ('alice', '../native-project')]:
            with self.assertRaises(OrxSessionError):
                await adapter.inspect_project(owner, identifier)
        with self.assertRaises(OrxSessionError):
            await adapter.list_projects('bob')
        self.assertEqual(self.requests, [])

    async def test_list_filters_out_unapproved_sources_and_rejects_duplicate_identity(self):
        self.rows = [project(), project(id='not-approved', path='/foreign', repoPath='/foreign')]
        self.assertEqual(len(await self.adapter().list_projects('alice')), 1)
        self.rows = [project(), project()]
        with self.assertRaises(OrxSessionError):
            await self.adapter().list_projects('alice')

    async def test_changed_native_id_or_source_never_adopted(self):
        for change in ({'id': 'different'}, {'repoPath': '/owned/other'}, {'path': '/owned/../foreign'},
                       {'repoPath': '/owned/source-link', 'path': '/owned/source-link'}):
            self.single = project(**change)
            with self.assertRaises(OrxSessionError):
                await self.adapter().inspect_project('alice', 'native-project')

    async def test_revocation_during_read_discards_result(self):
        self.authorize.side_effect = [True, False]
        with self.assertRaises(OrxSessionError):
            await self.adapter().inspect_project('alice', 'native-project')
        self.assertEqual(len(self.requests), 1)

    async def test_project_create_cannot_bypass_model_budget_with_flags(self):
        adapter = self.adapter()
        with self.assertRaisesRegex(OrxSessionError, 'ORX_PROJECT_CREATE_MODEL_BUDGET_REQUIRED'):
            await adapter.create_project('alice', approved=True, githubSyncEnabled=False,
                                         path='/owned/new', cloneUrl='http://169.254.169.254/')
        self.assertEqual(self.requests, [])
        self.assertFalse(adapter.describe('alice')['projectCreationAvailable'])

    def test_attachment_metadata_cannot_claim_governed_session_admission(self):
        adapter = self.adapter()
        description = adapter.describe('alice')
        self.assertFalse(description['sessionAdmissionAvailable'])
        self.assertEqual(description['sessionAdmissionBlockers'], [
            'NATIVE_PROJECT_APPROVED_PLAN_BINDING_REQUIRED',
            'NATIVE_SESSION_BROKER_ACCOUNTING_REQUIRED',
            'NATIVE_SESSION_ORIGINAL_CUSTODY_REQUIRED'])
        self.assertEqual(adapter.capabilities, ('project:read',))
        self.assertFalse(description['liveIntegrationVerified'])
        # A consumer cannot remove the actual requirements by changing a copy.
        description['sessionAdmissionBlockers'].clear()
        self.assertEqual(len(adapter.describe('alice')['sessionAdmissionBlockers']), 3)
        self.assertEqual(self.requests, [])

    async def test_original_project_profile_client_requires_durable_intent(self):
        client = await self.adapter().session_client('alice', 'native-project', 'reviewed')
        intents = []
        result = await client.create_session(key='create-original', commit_intent=lambda *, intent: intents.append(dict(intent)))
        self.assertEqual(result['id'], 'chat-original')
        self.assertEqual(len(intents), 1)
        sent = next(r for r in self.requests if r.method == 'POST')
        self.assertEqual(json.loads(sent.content), {
            'projectId': 'native-project', 'harness': 'opencode', 'model': 'fixture/model',
            'permissionMode': 'default', 'serviceTier': 'default', 'reasoningLevel': 'medium', 'planMode': False})
        self.assertNotIn('/message', sent.url.path)

    async def test_profile_expansion_or_missing_session_permission_denied(self):
        adapter = self.adapter()
        with self.assertRaises(OrxSessionError):
            await adapter.session_client('alice', 'native-project', 'unreviewed')
        self.authorize.side_effect = lambda owner, operation: operation == 'project:read'
        with self.assertRaises(OrxSessionError):
            await adapter.session_client('alice', 'native-project', 'reviewed')
        self.assertTrue(all(r.method == 'GET' for r in self.requests))

    async def test_optional_session_pin_drift_keeps_create_unknown_not_retried(self):
        for changes in ({'serviceTier': 'fast'}, {'reasoningLevel': 'high'}, {'planMode': True}, {'planMode': 0}):
            self.session = session(**changes)
            client = await self.adapter().session_client('alice', 'native-project', 'reviewed')
            count = sum(r.method == 'POST' for r in self.requests)
            with self.assertRaises(OrxSessionUnknown):
                await client.create_session(key='create-original', commit_intent=lambda **_: None)
            self.assertEqual(sum(r.method == 'POST' for r in self.requests), count + 1)

    async def test_retained_session_client_rechecks_permission_and_source_before_dispatch(self):
        client = await self.adapter().session_client('alice', 'native-project', 'reviewed')
        self.authorize.return_value = False
        with self.assertRaises(OrxSessionUnknown):
            await client.create_session(key='original-key', commit_intent=lambda **_: None)
        self.assertFalse(any(r.method == 'POST' for r in self.requests))
        self.authorize.return_value = True
        self.single = project(path='/changed', repoPath='/changed')
        with self.assertRaises(OrxSessionUnknown):
            await client.create_session(key='original-key-2', commit_intent=lambda **_: None)
        self.assertFalse(any(r.method == 'POST' for r in self.requests))

    async def test_optional_session_pins_are_part_of_effect_identity(self):
        hashes = []
        for reasoning in ('medium', 'high'):
            self.session = session(reasoningLevel=reasoning)
            client = OpenResearchSessionHTTP(38123, project_id='native-project', harness='opencode',
                model='fixture/model', reasoning_level=reasoning, transport=httpx.MockTransport(self.wire))
            await client.create_session(key='same-key', commit_intent=lambda *, intent: hashes.append(intent['requestHash']))
        self.assertNotEqual(*hashes)

    def test_untrusted_scope_configuration_rejected(self):
        for changes in ({'owner_exclusive': False}, {'upstream_revision': 'other'},
                        {'project_paths': {'native-project': '../source'}},
                        {'project_paths': {'native-project': '/owned/../source'}},
                        {'project_paths': {'native-project': 'https://example.com'}},
                        {'project_paths': {'native-project': '/'}},
                        {'port': True}):
            with self.subTest(changes=changes), self.assertRaises(OrxSessionError):
                self.adapter(**changes)

    async def test_http_redirect_is_not_followed_and_private_errors_not_exposed(self):
        self.handler = lambda _: httpx.Response(302, headers={'location': 'http://169.254.169.254/'},
                                               json={'secret': 'must-not-leak'})
        with self.assertRaises(OrxSessionError) as raised:
            await self.adapter().list_projects('alice')
        self.assertNotIn('must-not-leak', str(raised.exception))
        self.assertEqual(len(self.requests), 1)


if __name__ == '__main__':
    unittest.main()
