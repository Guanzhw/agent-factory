"""Fixed-time origin read flow with controlled HTTP, not real receiver/PG evidence.

The real HTTP/PG counterpart separately proves positive lease-expiry causality
when its original five-second lease expires during inspection.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from agent_factory.remote_execution import RemoteExecution
from agent_factory.remote_handoff import HandoffTarget, TrustedHandoffClient
from agent_factory.store import digest


class _Bytes(httpx.AsyncByteStream):
    def __init__(self, value):
        self.value = value

    async def __aiter__(self):
        yield self.value


class RemoteDisconnectReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_future_lease_outage_is_unknown_held_and_reconnects_original_without_mutation(self):
        # One fixed point in a synthetic five-second receiver lease. No real
        # deadline is reset, extended or paused by this deterministic unit test.
        now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        ids = {key: str(uuid4()) for key in ('task', 'plan', 'receipt', 'remoteTask', 'remotePlan', 'run', 'lease', 'provider')}
        lease = {'id': ids['lease'], 'localTaskId': ids['remoteTask'], 'nativeRunId': ids['run'],
                 'planId': ids['remotePlan'], 'providerJobId': ids['provider'], 'capacityHeld': True,
                 'deadlineAt': (now + timedelta(seconds=5)).isoformat()}
        receipt = {'id': ids['receipt'], 'remoteTaskId': ids['remoteTask'], 'remotePlanId': ids['remotePlan'],
                   'remoteRunId': ids['run'], 'state': 'RUNNING', 'allStopped': False,
                   'processLeases': {'schema': 1, 'complete': True, 'leases': [lease]}}
        plan = {'id': ids['plan'], 'application': 'controlled-process-fixture',
                'normalizedGoal': 'Read original custody', 'mode': 'controlled-fixture'}
        task = {'id': ids['task'], 'owner_id': 'alice', 'plan_id': ids['plan'], 'run_id': None,
                'terminal': False, 'cancel_requested': False,
                'body': {'createdAt': now.isoformat(), 'updatedAt': now.isoformat()}}
        original_task = deepcopy(task)
        outage, requests = [True], []

        async def transport(request):
            requests.append((request.method, request.url.path))
            self.assertEqual(request.method, 'GET', 'A read outage must never send cancellation or dispatch')
            self.assertEqual(request.url.path, '/api/factory/remote-handoffs/' + ids['receipt'] + '/detail')
            self.assertLess(now, datetime.fromisoformat(lease['deadlineAt']))
            payload = {'detail': 'controlled unavailable'} if outage[0] else {
                'handoff': deepcopy(receipt),
                'job': {'id': ids['remoteTask'], 'planId': ids['remotePlan'], 'status': 'running',
                        'allowedActions': ['inspect', 'cancel']},
                'events': [], 'artifacts': [], 'snapshot': {'capacityHeld': True}}
            return httpx.Response(503 if outage[0] else 200, stream=_Bytes(json.dumps(payload).encode()))

        target = HandoffTarget('receiver', 'origin', 'http://receiver.invalid', {'alice': 'bob'},
                               lambda _: {}, transport=httpx.MockTransport(transport))
        row = {'task_id': task['id'], 'owner_id': 'alice', 'target_ref': 'receiver', 'state': 'RUNNING',
               'configuration_hash': target.fingerprint, 'manifest_hash': digest(plan),
               'body': {'receipt': deepcopy(receipt)}}

        def sql(query, **params):
            self.assertTrue(query.startswith('SELECT * FROM af_remote_placements'), query)
            self.assertEqual(params, {'id': task['id'], 'owner': 'alice'})
            return [deepcopy(row)]

        def owned_task(identifier, owner):
            self.assertEqual((identifier, owner), (task['id'], 'alice'))
            return deepcopy(task)

        def owned_plan(identifier, owner):
            self.assertEqual((identifier, owner), (plan['id'], 'alice'))
            return deepcopy(plan)

        mutation = Mock(side_effect=AssertionError('Read must not mutate task/capacity or dispatch'))
        store = SimpleNamespace(settings=SimpleNamespace(demo=True, experiment_output_bytes=65536),
            sql=sql, task=owned_task, plan=owned_plan, events=lambda _: [], usage_ledger=None,
            request_cancel=mutation, observed=mutation, reserve_task=mutation, release_task=mutation)
        client = TrustedHandoffClient.__new__(TrustedHandoffClient)
        client.store, client.targets = store, {'receiver': target}
        client.auth = SimpleNamespace(require=Mock())
        client.admission_guard = None
        execution = RemoteExecution(store, client)

        # Receipt persistence is an isolated in-memory seam, not a claim of PG
        # receipt-validation coverage. All origin read/transport/projection code
        # above this seam remains real and must preserve the exact known receipt.
        def save(original, bound_target, received):
            self.assertEqual(original, row)
            self.assertIs(bound_target, target)
            self.assertEqual(received, receipt)
            return deepcopy(received)

        with patch.object(client, '_save_receipt', side_effect=save) as saved, \
             patch.object(client, 'cancel', side_effect=AssertionError('No cancel')) as cancel, \
             patch.object(client, 'dispatch', side_effect=AssertionError('No replay')) as dispatch, \
             patch.object(client, 'prepare', side_effect=AssertionError('No new admission')) as prepare:
            for _ in range(2):
                unavailable = await execution.detail(deepcopy(task))
                self.assertEqual(unavailable['job']['status'], 'unknown')
                self.assertEqual(unavailable['snapshot']['remoteReadCode'], 503)
                self.assertTrue(unavailable['snapshot']['remoteUnavailable'])
                self.assertTrue(unavailable['snapshot']['capacityHeld'])
                self.assertFalse(unavailable['snapshot']['cancelRequested'])
            saved.assert_not_called()
            outage[0] = False
            for _ in range(2):
                restored = await execution.detail(deepcopy(task))
                self.assertEqual(restored['job']['id'], task['id'])
                self.assertEqual(restored['snapshot']['remoteHandoff'], receipt)
                self.assertTrue(restored['snapshot']['capacityHeld'])
                self.assertNotIn('remoteUnavailable', restored['snapshot'])
            self.assertEqual(saved.call_count, 2)
            cancel.assert_not_called(); dispatch.assert_not_called(); prepare.assert_not_called()
        mutation.assert_not_called()
        self.assertEqual(task, original_task)
        self.assertEqual(row['body']['receipt'], receipt)
        self.assertEqual(len(requests), 4)
        self.assertTrue(all(method == 'GET' for method, _ in requests))
