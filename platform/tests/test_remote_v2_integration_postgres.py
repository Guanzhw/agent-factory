"""Neutral v2 over actual TCP peers, independent PG and original native queue.

Controlled local checksum execution only; no external model/remote provider
compatibility is established. Existing v1 fixtures retain their own coverage.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import time
import unittest
from uuid import uuid4

from agent_factory.store import digest
from controlled_remote_worker import ORIGIN_OWNER, ORIGIN_REF, TARGET_REF
from remote_v2_fixture import APP_ID, PLAN_BUDGET, CONFIG, CONFIG_SCHEMA, INPUT_SCHEMA, V2Pair


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires owned loopback PostgreSQL')
class RemoteV2IntegrationPostgresTests(unittest.TestCase):
    def setUp(self):
        self.pair = V2Pair(os.environ['FACTORY_TEST_DATABASE_URL']).start()
        self.addCleanup(self.pair.close)
        self.origin, self.receiver = self.pair.origin, self.pair.receiver

    def call(self, server, method, path, expected=200, **kwargs):
        response = server.request(method, '/api/factory' + path, **kwargs)
        self.assertEqual(response.status_code, expected,
            response.text + '\nReceiver diagnostics: ' + self.receiver.log_tail())
        return response

    def wait_for(self, predicate, *, seconds=25):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = predicate()
            if value:
                return value
            time.sleep(.04)
        self.fail('Original v2 operation did not reach expected state\n' + self.receiver.log_tail())

    def plan(self, text):
        proposal = self.call(self.origin, 'POST', '/compositions/proposals', 201, json={
            'goal': text, 'mode': 'execute', 'applicationRef': self.origin.facts()['applicationRef'],
            'inputValues': {'payload': text}, 'requestId': uuid4().hex}).json()
        self.assertEqual(proposal['candidate']['status'], 'ready', proposal)
        return self.call(self.origin, 'POST', '/compositions/proposals/' + proposal['id'] + '/accept',
                         201, json={'requestId': uuid4().hex}).json()

    def request_body(self, plan):
        return {'planId': plan['id'], 'requestId': uuid4().hex, 'executionTargetRef': TARGET_REF}

    def placement(self, task):
        return next(row for row in self.origin.facts()['placements'] if row['task_id'] == task)

    def receipt(self, task):
        row = self.placement(task)
        return self.call(self.receiver, 'GET', '/remote-handoffs/receipts/by-request', params={
            'originRef': ORIGIN_REF, 'originOwnerId': ORIGIN_OWNER, 'requestId': row['request_id']}).json()

    def settled_without_job_get(self, task):
        # These authenticated fixture queries read PG only. Positive receiver
        # stop proof can settle the origin before the receiver's local lifecycle
        # commits terminal; its GET correctly remains finalizing in that gap.
        # Wait for both original tasks within one existing 25s window, without
        # GET/reconcile doing the background observer's settlement work.
        def both_terminal():
            facts = self.origin.facts(task)
            if not facts['task']['terminal']:
                return False
            placement = next(row for row in facts['placements'] if row['task_id'] == task)
            receipt = placement['body']['receipt']
            self.assertEqual(receipt['originTaskId'], task)
            return self.receiver.facts(receipt['remoteTaskId'])['task']['terminal']

        self.wait_for(both_terminal)
        return self.call(self.origin, 'GET', '/jobs/' + task).json()

    def assert_original_once(self, task, receipt):
        facts = self.receiver.facts(receipt['remoteTaskId'])
        self.assertEqual(facts['nativeTickets'], 1)
        self.assertEqual(self.origin.facts(task)['nativeTickets'], 0)
        inputs = [event['data'] for event in facts['events'] if event['type'] == 'v2_adapter_input']
        self.assertEqual(len(inputs), 1, 'Original tool dispatch must not replay after recovery')
        self.assertEqual(inputs[0]['runId'], receipt['remoteRunId'])
        self.assertEqual(inputs[0]['taskId'], receipt['remoteTaskId'])
        return inputs[0]

    def test_v2_values_budget_and_exact_artifact_survive_real_remote_execution(self):
        text = 'Original neutral v2 input: café / 研究 / 123'
        plan = self.plan(text)
        self.assertEqual(plan['contractVersion'], 2)
        self.assertEqual(plan['budget'], PLAN_BUDGET)
        self.assertNotIn('experimentSeconds', plan['budget'])
        self.origin.control('dispatch-hold')
        body = self.request_body(plan)
        task = self.call(self.origin, 'POST', '/instances', 202, json=body).json()['id']
        pending = self.receipt(task)
        self.assertEqual(pending['state'], 'PREPARED')
        self.assertIsNone(pending['remoteRunId'])
        self.assertEqual(self.receiver.facts(pending['remoteTaskId'])['nativeTickets'], 0)
        manifest = self.placement(task)['body']['manifest']
        self.assertEqual(set(manifest), {'wireVersion', 'plan', 'applicationDefinition', 'sha256'})
        self.assertEqual(manifest['wireVersion'], 2)
        self.assertEqual(manifest['sha256'], digest(plan))
        mode = manifest['applicationDefinition']['modes']['execute']
        self.assertEqual(mode['configSchema'], CONFIG_SCHEMA)
        self.assertEqual(mode['config'], CONFIG)
        self.assertEqual(mode['inputSchema'], INPUT_SCHEMA)
        imported = self.receiver.facts(pending['remoteTaskId'])['plan']
        for field in ('contractVersion', 'config', 'inputSchema', 'inputValues', 'budget'):
            self.assertEqual(imported[field], plan[field])
        self.origin.control('dispatch-release')
        self.assertEqual(self.call(self.origin, 'POST', '/instances', 202, json=body).json()['id'], task)
        completed = self.settled_without_job_get(task)
        self.assertEqual(completed['job']['status'], 'completed')
        receipt = completed['snapshot']['remoteHandoff']
        for field in ('id', 'remoteTaskId', 'remotePlanId', 'manifestHash', 'receiverBindingProof'):
            self.assertEqual(receipt[field], pending[field])
        values = self.assert_original_once(task, receipt)
        self.assertEqual(values['contractVersion'], 2)
        self.assertEqual(values['applicationConfig'], CONFIG)
        self.assertEqual(values['inputSchema'], INPUT_SCHEMA)
        self.assertEqual(values['inputValues'], {'payload': text})
        self.assertEqual(values['text'], text)
        self.assertEqual(values['budget'], PLAN_BUDGET)
        artifact = next(value for value in completed['artifacts'] if value['name'] == 'checksum.json')
        raw = self.call(self.origin, 'GET', f'/jobs/{task}/artifacts/{artifact["id"]}')
        expected = json.dumps({'algorithm': 'sha256', 'sha256': hashlib.sha256(text.encode()).hexdigest(),
            'inputBytes': len(text.encode()), 'evidenceKind': 'synthetic-input-real-computation'}, sort_keys=True).encode()
        self.assertEqual(raw.content, expected)
        self.assertEqual(artifact['sha256'], hashlib.sha256(expected).hexdigest())
        self.assertEqual(raw.headers['x-content-sha256'], artifact['sha256'])
        self.assertEqual(self.origin.facts()['applicationRef']['id'], APP_ID)

    def test_lost_prepare_and_dispatch_replies_restart_original_receipt_without_redispatch(self):
        for phase in ('prepare', 'dispatch'):
            with self.subTest(lost_reply=phase):
                plan = self.plan('Original v2 lost ' + phase + ' reply')
                body = self.request_body(plan)
                self.origin.control('origin-observation-hold')
                self.origin.control('dispatch-hold')
                if phase == 'prepare':
                    self.receiver.control('fault', fault='prepare')
                    task = self.call(self.origin, 'POST', '/instances', 202, json=body).json()['id']
                else:
                    task = self.call(self.origin, 'POST', '/instances', 202, json=body).json()['id']
                    self.receiver.control('fault', fault='dispatch')
                    self.origin.control('dispatch-release')
                    self.call(self.origin, 'POST', '/instances', 202, json=body)
                self.assertEqual(self.receiver.process.wait(timeout=5), 41)
                marker = json.loads((self.pair.path / 'receiver-fault.json').read_text())
                self.assertEqual(marker['phase'], phase)
                unknown = self.placement(task)
                self.assertEqual(unknown['manifest_hash'], digest(plan))
                self.assertFalse(self.origin.facts(task)['task']['terminal'])
                old_pid = self.receiver.process.pid
                self.receiver.start()
                self.assertNotEqual(self.receiver.process.pid, old_pid)
                original = self.receipt(task)
                self.origin.control('dispatch-release')
                with ThreadPoolExecutor(max_workers=2) as pool:
                    requests = [pool.submit(self.call, self.origin, 'POST', '/instances', 202, json=body)
                                for _ in range(2)]
                    self.assertEqual([request.result().json()['id'] for request in requests], [task, task])
                self.call(self.origin, 'POST', '/jobs/' + task + '/reconcile')
                self.origin.control('origin-observation-release')
                complete = self.settled_without_job_get(task)
                self.assertEqual(complete['job']['status'], 'completed')
                current = complete['snapshot']['remoteHandoff']
                for field in ('id', 'remoteTaskId', 'remotePlanId', 'manifestHash', 'receiverBindingProof'):
                    self.assertEqual(current[field], original[field])
                if original['remoteRunId'] is not None:
                    self.assertEqual(current['remoteRunId'], original['remoteRunId'])
                self.assert_original_once(task, current)

    def test_cancel_keeps_unknown_until_actual_stop_and_get_never_controls_original(self):
        self.receiver.control('work-hold')
        plan = self.plan('Original v2 cancellation with unresolved stop proof')
        body = self.request_body(plan)
        task = self.call(self.origin, 'POST', '/instances', 202, json=body).json()['id']
        original = self.receipt(task)
        remote_id = original['remoteTaskId']
        self.wait_for(lambda: any(event['type'] == 'v2_adapter_input'
                                 for event in self.receiver.facts(remote_id)['events']))
        self.call(self.origin, 'POST', '/jobs/' + task + '/cancel',
                  json={'commandId': 'v2-original-cancel'})
        self.wait_for(lambda: self.receiver.facts(remote_id)['task']['cancel_requested'])
        self.wait_for(lambda: self.receiver.facts(remote_id)['nativeStatus'] in {'cancelled', 'failed', 'completed'})
        held = self.receiver.facts(remote_id)
        self.assertFalse(held['task']['terminal'])
        self.assertEqual([effect['status'] for effect in held['effects']], ['UNKNOWN'])
        self.assertFalse(self.origin.facts(task)['task']['terminal'])
        self.origin.control('origin-observation-hold')
        self.receiver.control('observer-stop')
        before = self.placement(task)
        remote_before = self.receiver.facts(remote_id)
        for _ in range(3):
            self.call(self.origin, 'GET', '/jobs/' + task)
            self.call(self.origin, 'GET', '/jobs')
            self.call(self.receiver, 'GET', '/remote-handoffs/' + original['id'])
        self.assertEqual(self.placement(task), before)
        remote_after = self.receiver.facts(remote_id)
        for field in ('task', 'effects', 'handoffs', 'events'):
            self.assertEqual(remote_after[field], remote_before[field])
        self.receiver.control('work-release')
        self.receiver.control('observer-start')
        self.origin.control('origin-observation-release')
        completed = self.settled_without_job_get(task)
        self.assertEqual(completed['job']['status'], 'canceled')
        final = self.receiver.facts(remote_id)
        self.assertEqual(final['effects'][0]['effect_key'], held['effects'][0]['effect_key'])
        self.assertEqual(final['effects'][0]['status'], 'CANCELLED')
        self.assertEqual(final['effects'][0]['result'], {'cancelled': True, 'allStopped': True})
        self.assert_original_once(task, completed['snapshot']['remoteHandoff'])


if __name__ == '__main__':
    unittest.main()
