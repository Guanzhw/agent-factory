"""Public ports: current authority, original identity, and no write retries."""
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import httpx
from pydantic import ValidationError

from agent_factory._application_context import FactoryApplicationContext
from agent_factory.application_client import ApplicationClient
from agent_factory.application_runs import ApplicationStart


class ApplicationContextTests(unittest.TestCase):
    def setUp(self):
        self.root = SimpleNamespace(user_id='alice', session_id='task', run_id='run')
        self.plan = {'application': 'synthetic-summary', 'applicationRef': {'id': 'synthetic-summary', 'version': 2},
            'inputValues': {'goal': 'Controlled example'}, 'materialRefs': [{'id': 'tool', 'version': 1, 'sha256': 'a' * 64}],
            'bindingManifest': {'connections': {'source': {'ref': 'owned-source', 'version': 1,
                'kind': 'source', 'fingerprint': 'b' * 64, 'configuration': {'secret': 'must-not-be-projected'}}}}}
        self.store = SimpleNamespace(resolve_run=Mock(return_value=self.plan), authorize_tool=Mock(),
            event=Mock(), artifact_write=Mock(return_value={'id': 'artifact', 'sha256': 'c' * 64}))
        self.context = FactoryApplicationContext(self.store, self.root, 'summarize')

    def test_inputs_and_resources_are_independent_inert_snapshots(self):
        inputs = self.context.inputs; inputs['goal'] = 'Changed copy'
        resources = self.context.resources; resources['materials'][0]['version'] = 99
        self.assertEqual(self.context.inputs['goal'], 'Controlled example')
        self.assertEqual(self.context.resources['materials'][0]['version'], 1)
        self.assertNotIn('configuration', self.context.resources['connections']['source'])
        self.assertEqual(self.context.identity.application_version, 2)

    def test_each_write_rechecks_current_authority_and_cannot_claim_verified_result(self):
        self.context.emit_event('ready', 'Application observation')
        self.context.write_artifact('result.json', '{}')
        self.assertEqual(self.store.authorize_tool.call_count, 2)
        self.store.authorize_tool.assert_called_with(self.root, 'summarize')
        self.assertEqual(self.store.event.call_args.args[:2], ('task', 'application_ready'))
        self.assertEqual(self.store.artifact_write.call_args.kwargs['metadata']['verificationStatus'], 'unverified')
        self.store.authorize_tool.side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError): self.context.write_artifact('after-revoke.json', '{}')
        with self.assertRaises(PermissionError): self.context.emit_event('ready', 'After revoke')
        self.assertEqual(self.store.artifact_write.call_count, 1)
        self.assertEqual(self.store.event.call_count, 1)

    def test_mutated_native_identity_and_oversized_event_are_denied_before_writes(self):
        self.root.run_id = 'different-run'
        with self.assertRaises(PermissionError): self.context.write_artifact('result.json', '{}')
        self.assertFalse(self.store.artifact_write.called)
        self.root.run_id = 'run'
        with self.assertRaises(ValueError): self.context.emit_event('ready', 'Observed', {'large': 'x' * 16000, 'more': 'x' * 1000})
        self.assertFalse(self.store.event.called)

    def test_minimal_application_runs_through_only_public_context(self):
        path = Path(__file__).resolve().parents[2] / 'examples/minimal_application.py'
        spec = importlib.util.spec_from_file_location('minimal_application_example', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        result = module.summarize(None, application_context=self.context)
        self.assertTrue(result.content['synthetic'])
        self.assertFalse(result.content['scientificConclusionVerified'])
        self.assertEqual(result.content['artifactId'], 'artifact')
        self.assertEqual(self.store.event.call_args.args[1], 'application_summary_ready')


class ApplicationClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_start_response_reads_original_request_without_retry(self):
        calls = []
        def receive(request):
            calls.append((request.method, request.url.path, request.headers.get('X-Factory-Expected-Owner')))
            if request.method == 'POST': raise httpx.ReadTimeout('synthetic lost acknowledgement', request=request)
            return httpx.Response(200, json={'interfaceVersion': 1, 'requestId': 'original-001',
                'state': 'unknown', 'taskId': 'task', 'automaticReplay': False})
        async with httpx.AsyncClient(base_url='http://local-fixture.invalid', transport=httpx.MockTransport(receive)) as http:
            client = ApplicationClient(http, owner_id='alice')
            with self.assertRaises(httpx.ReadTimeout):
                await client.start({'requestId': 'original-001', 'application': 'synthetic-summary', 'mode': 'summary', 'goal': 'Controlled example'})
            result = await client.request('original-001')
        self.assertEqual([item[0] for item in calls], ['POST', 'GET'])
        self.assertEqual([item[2] for item in calls], ['alice', 'alice'])
        self.assertEqual(result['state'], 'unknown')
        self.assertFalse(result['automaticReplay'])

    async def test_cancel_ack_is_not_converted_to_stop_and_artifacts_require_hash(self):
        calls = []
        def receive(request):
            calls.append(request)
            if request.method == 'POST': return httpx.Response(202, json={'state': 'ACKNOWLEDGED', 'stopConfirmed': False})
            return httpx.Response(200, content=b'controlled output', headers={'X-Content-SHA256': hashlib.sha256(b'other output').hexdigest()})
        async with httpx.AsyncClient(base_url='http://local-fixture.invalid', transport=httpx.MockTransport(receive)) as http:
            client = ApplicationClient(http, owner_id='alice')
            receipt = await client.cancel('task', 'cancel-original')
            self.assertFalse(receipt['stopConfirmed'])
            with self.assertRaises(ValueError): await client.artifact('task', 'artifact')
            with self.assertRaises(ValueError): await client.query('../connections')
        self.assertEqual(len(calls), 2)

    def test_interface_version_is_strict_and_cannot_request_execution_authority(self):
        valid = {'requestId': 'original-001', 'application': 'app', 'mode': 'summary', 'goal': 'Controlled example'}
        for marker in (True, '1', 2):
            with self.subTest(marker=marker), self.assertRaises(ValidationError): ApplicationStart(**valid, interfaceVersion=marker)
        for key in ('executionTargetRef', 'permissions', 'credential', 'automaticReplay'):
            with self.subTest(key=key), self.assertRaises(ValidationError): ApplicationStart(**valid, **{key: 'untrusted'})


if __name__ == '__main__': unittest.main()
