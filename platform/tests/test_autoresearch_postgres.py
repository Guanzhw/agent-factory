# pyright: reportMissingImports=false
"""Actual PG/HTTP/native admission with an inert controlled runtime.

No ORX container, network provider, model inference, GPU or scientific result is
claimed. The real ORXResearchModel.aresponse delegates into the service once.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any
import unittest
from types import SimpleNamespace

import httpx
from unittest.mock import patch
from uuid import uuid4

from agent_factory.autoresearch import ResearchPreset
from agent_factory.autoresearch_profile import ORXResearchModel
from agent_factory.autoresearch_runtime import AutoResearchRuntime
from pg_fixture import IsolatedPostgres
import test_go_product_postgres as native_fixture

_SOURCE = Path(__file__).resolve().parents[2] / 'scripts' / 'bootstrap_autoresearch.py'
_SPEC = importlib.util.spec_from_file_location('autoresearch_pg_bootstrap', _SOURCE)
assert _SPEC and _SPEC.loader
bootstrap = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bootstrap)


class InertRuntime:
    """Synthetic runtime lifecycle only; never claims a real model/tool decision."""
    def __init__(self, *, wait=False, stopped=True):
        self.wait, self.stopped = wait, stopped
        self.started = threading.Event()
        self.finish = threading.Event()
        self.run_calls = self.stop_calls = self.cancel_calls = 0

    async def run(self):
        self.run_calls += 1
        self.started.set()
        while self.wait and not self.finish.is_set():
            await asyncio.sleep(.01)
        return {'evidenceMode': 'controlled-fixture', 'modelExecuted': False}

    async def stop(self):
        self.stop_calls += 1
        return self.stopped

    async def cancel(self):
        self.cancel_calls += 1
        self.finish.set()


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class AutoResearchPostgresTests(unittest.TestCase):
    state: dict[str, Any]
    store: Any
    client: Any
    open_application = native_fixture.GoProductPostgresTests.open_application
    login = native_fixture.GoProductPostgresTests.login
    post = native_fixture.GoProductPostgresTests.post

    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        directory = tempfile.TemporaryDirectory(prefix='autoresearch-inert-pg-')
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        self.runtime = InertRuntime()
        self.factory_calls: list[tuple[str, str, str]] = []
        self.outer_calls: list[str] = []
        async def unavailable_experiment(*_args):
            raise AssertionError('No experiment/model requested by this inert runtime fixture')
        def runtime_factory(ctx, _service):
            run = ctx.run_context
            self.factory_calls.append((run.user_id, run.session_id, run.run_id))
            return self.runtime
        self.preset = ResearchPreset(id='synthetic-native-test', name='受控原生研究测试',
            default_goal='核对受控公开研究记录，不进行真实模型推理。', owner_id='alice',
            instructions='Synthetic native lifecycle only; never claim live research.', manifest={'schema': 1, 'evidenceMode': 'controlled-fixture'},
            limits={'totalSeconds': 60, 'experimentSeconds': 5, 'maxExperiments': 1, 'toolCalls': 8, 'outputBytes': 65536},
            runtime_factory=runtime_factory, context_reader=lambda: {'evidenceMode': 'controlled-fixture'},
            candidate_validator=lambda _value: {'accepted': False}, experiment=unavailable_experiment,
            review_owner='manager')
        self.settings = bootstrap.settings(db_url=self.database.url, workspace=self.workspace, preset=self.preset)
        # Explicit legacy accounting fixture; all model/provider IO remains controlled.
        self.settings.fee_management_enabled = self.settings.platform_paid_models_enabled = True
        original = ORXResearchModel.aresponse
        async def observed_outer(model, *args, **kwargs):
            self.outer_calls.append(model.id)
            return await original(model, *args, **kwargs)
        self.enterContext(patch.object(ORXResearchModel, 'aresponse', new=observed_outer))
        self.open_application()
        auth = self.state['auth']
        auth.authorization.unassign('bob', 'factory-user')
        auth.authorization.assign('bob', 'factory-manager')
        self.preset = bootstrap.publish_application(self.state, self.preset, author='manager', reviewer='bob')
        self.settings.autoresearch_presets[self.preset.id] = self.preset
        self.store.autoresearch.presets[self.preset.id] = self.preset
        self.login('alice')
        self.assertEqual(self.factory_calls, [])
        self.assertEqual(self.outer_calls, [])
        self.addCleanup(self.runtime.finish.set)

    def read(self, identifier):
        response = self.client.get('/api/factory/autoresearch/runs/' + identifier)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait_for(self, predicate, *, seconds=25):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.025)
        self.fail('Controlled native research state did not settle')

    def start(self, request_id=None):
        request_id = request_id or str(uuid4())
        return self.post('/api/factory/autoresearch/runs', {'presetId': self.preset.id, 'requestId': request_id}, 202)

    def test_default_goal_native_outer_delegation_and_original_request_recovery(self):
        response = self.client.get('/api/factory/autoresearch/presets')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['defaultGoal'], self.preset.default_goal)
        self.assertTrue(response.json()[0]['ready'])
        request = str(uuid4())
        initial = self.start(request)
        self.assertEqual(initial['goal'], self.preset.default_goal)
        self.wait_for(lambda: self.read(initial['id'])['status'] == 'completed')
        saved = self.read(initial['id'])
        self.assertFalse(any(saved['acceptance'].values()))
        original = self.store.task(saved['id'], 'alice')
        self.assertTrue(original['run_id'])
        self.assertEqual(self.factory_calls, [('alice', saved['id'], original['run_id'])])
        self.assertEqual(len(self.outer_calls), 1)
        native = self.store.native_db.get_job(original['run_id'], strict=True)
        self.assertEqual(native['attempt'], 1)
        self.assertEqual(native['max_attempts'], 1)
        self.assertEqual(self.start(request)['id'], saved['id'])
        recovered = self.client.get('/api/factory/autoresearch/requests/' + request)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()['id'], saved['id'])
        self.assertEqual(self.runtime.run_calls, 1)
        self.assertEqual(self.runtime.stop_calls, 1)
        self.login('bob')
        self.assertEqual(self.client.get('/api/factory/autoresearch/runs/' + saved['id']).status_code, 404)
        foreign = self.client.get('/api/factory/autoresearch/requests/' + request)
        self.assertEqual(foreign.status_code, 200)
        self.assertIsNone(foreign.json())

    def test_changed_goal_conflict_and_unavailable_preset_no_new_dispatch(self):
        request = str(uuid4())
        run = self.start(request)
        self.wait_for(lambda: self.read(run['id'])['status'] == 'completed')
        self.post('/api/factory/autoresearch/runs', {'presetId': self.preset.id, 'requestId': request, 'goal': '另一个不同目标'}, 409)
        blocked = replace(self.preset, blockers=('Synthetic operator prerequisite unavailable',))
        self.settings.autoresearch_presets[self.preset.id] = blocked
        self.store.autoresearch.presets[self.preset.id] = blocked
        self.post('/api/factory/autoresearch/runs', {'presetId': self.preset.id, 'requestId': str(uuid4())}, 409)
        self.assertEqual(self.runtime.run_calls, 1)
        self.assertEqual(len(self.store.sql('SELECT task_id FROM af_autoresearch_runs')), 1)
        self.assertEqual(len(self.outer_calls), 1)

    def test_cancel_uses_native_command_and_requires_original_positive_stop(self):
        self.runtime.wait = True
        run = self.start()
        self.wait_for(self.runtime.started.is_set)
        original = self.store.task(run['id'], 'alice')
        command = str(uuid4())
        self.post('/api/factory/autoresearch/runs/' + run['id'] + '/cancel', {'requestId': command}, 200)
        self.wait_for(lambda: self.runtime.stop_calls == 1 and self.read(run['id'])['status'] == 'failed')
        task = self.store.task(run['id'], 'alice')
        self.assertEqual(task['run_id'], original['run_id'])
        self.assertTrue(task['cancel_requested'])
        commands = self.store.sql('SELECT * FROM af_control_commands WHERE owner_id=:owner AND command_id=:command', owner='alice', command=command)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]['action'], 'cancel')
        effect = self.store.sql('SELECT status,result FROM af_effects WHERE effect_key=:key', key=original['run_id'] + ':autoresearch-session-v1')[0]
        self.assertEqual(effect['status'], 'CANCELLED')
        self.assertTrue(effect['result']['allStopped'])
        self.assertTrue(effect['result']['cancelled'])
        self.assertFalse(effect['result']['scientificConclusionVerified'])
        self.assertEqual(self.runtime.run_calls, 1)

    def test_missing_stop_proof_holds_original_effect_and_replay_never_dispatches(self):
        self.runtime.stopped = False
        request = str(uuid4())
        run = self.start(request)
        self.wait_for(lambda: self.read(run['id'])['status'] == 'unknown')
        original = self.store.task(run['id'], 'alice')
        effect: dict[str, Any] = self.store.sql('SELECT status,result FROM af_effects WHERE effect_key=:key', key=original['run_id'] + ':autoresearch-session-v1')[0]
        self.assertEqual(effect['status'], 'UNKNOWN')
        self.assertIsNone(effect['result'])
        self.assertEqual(self.start(request)['id'], run['id'])
        self.assertEqual(self.store.task(run['id'], 'alice')['run_id'], original['run_id'])
        self.assertEqual(self.runtime.run_calls, 1)
        self.assertEqual(self.runtime.stop_calls, 1)
        self.assertFalse(self.read(run['id'])['acceptance']['scientificConclusionVerified'])

    def test_mock_stream_requests_equal_real_ledger_attempts_without_outer_attempt(self):
        provider_requests = []
        observed_states = []
        completed = threading.Event()
        def provider(request):
            body = json.loads(request.content)
            provider_requests.append(body)
            self.assertTrue(body['stream'])
            event = {'model': 'deepseek-flash', 'choices': [{'index': 0,
                'delta': {'content': 'Synthetic controlled response'}, 'finish_reason': 'stop'}]}
            events = [event]
            if len(provider_requests) <= 2:
                events.append({'model': 'deepseek-flash', 'choices': [],
                    'usage': {'prompt_tokens': 12, 'completion_tokens': 7, 'total_tokens': 19}})
            raw = b''.join(b'data: ' + json.dumps(value).encode() + b'\n\n' for value in events) + b'data: [DONE]\n\n'
            return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, content=raw)
        def runtime_factory(ctx, service):
            run = ctx.run_context
            self.factory_calls.append((run.user_id, run.session_id, run.run_id))
            # Construct only; never start the launcher, listener, ORX or a model.
            broker_runtime = AutoResearchRuntime(ctx, service,
                launcher=SimpleNamespace(start=lambda *_: self.fail('NO_LAUNCH'),
                    config=SimpleNamespace(cpus=1, memory_mb=1024, pids=64, max_output_tokens=16)),
                project_id='synthetic-public-project', credential=lambda: 'synthetic-not-a-credential',
                billing_authorized=lambda: True, max_requests=4, max_output_tokens=16,
                broker_transport=httpx.MockTransport(provider))
            async def broker_run():
                self.runtime.run_calls += 1
                self.runtime.started.set()
                body = {'model': 'deepseek-flash', 'stream': True, 'max_tokens': 16,
                    'messages': [{'role': 'user', 'content': 'Return a synthetic fixture response.'}]}
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=broker_runtime),
                    base_url='http://controlled.invalid') as client:
                    for _ in range(2):
                        response = await client.post('/v1/chat/completions', json=body,
                            headers={'Authorization': 'Bearer ' + broker_runtime.capability})
                        self.assertEqual(response.status_code, 200)
                    attempts = self.store.usage_ledger.inspect('alice', run.session_id)['attempts']
                    self.assertEqual([row['state'] for row in attempts], ['SETTLED', 'SETTLED'])
                    observed_states.append([row['state'] for row in attempts])
                    third = await client.post('/v1/chat/completions', json=body,
                        headers={'Authorization': 'Bearer ' + broker_runtime.capability})
                    self.assertNotEqual(third.status_code, 200)
                    self.assertIsNotNone(broker_runtime.broker.stopped_reason)
                    after_unknown = self.store.usage_ledger.inspect('alice', run.session_id)['attempts']
                    self.assertEqual(sorted(row['state'] for row in after_unknown), ['SETTLED', 'SETTLED', 'UNKNOWN'])
                    fourth = await client.post('/v1/chat/completions', json=body,
                        headers={'Authorization': 'Bearer ' + broker_runtime.capability})
                    self.assertNotEqual(fourth.status_code, 200)
                    self.assertEqual(len(provider_requests), 3)
                    final_attempts = self.store.usage_ledger.inspect('alice', run.session_id)['attempts']
                    self.assertEqual({row['id'] for row in final_attempts}, {row['id'] for row in after_unknown})
                completed.set()
                return {'evidenceMode': 'controlled-fixture', 'providerRequests': 3}
            self.runtime.run = broker_run
            return self.runtime
        preset = replace(self.preset, runtime_factory=runtime_factory,
            limits={**self.preset.limits, 'modelRequests': 4, 'modelOutputTokens': 16})
        self.settings.autoresearch_presets[preset.id] = preset
        self.store.autoresearch.presets[preset.id] = preset
        run = self.start()
        self.wait_for(completed.is_set)
        self.wait_for(lambda: self.runtime.stop_calls == 1)
        self.assertEqual(observed_states, [['SETTLED', 'SETTLED']])
        attempts = self.store.usage_ledger.inspect('alice', run['id'])['attempts']
        self.assertEqual(len(attempts), len(provider_requests))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(len(self.outer_calls), 1)
        self.assertFalse(self.read(run['id'])['acceptance']['modelExecuted'])
        self.assertFalse(self.read(run['id'])['acceptance']['scientificConclusionVerified'])
