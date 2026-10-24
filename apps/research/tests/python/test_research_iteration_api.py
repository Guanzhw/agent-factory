"""HTTP activity lifecycle over the real service and portable budget/driver seams.

No native runtime, provider, subprocess, PostgreSQL, or coordinator is started.
The existing state-machine fixture supplies only budget and execution evidence.
"""
from copy import deepcopy
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from agent_factory_research.research_iteration_api import iteration_router
from agent_factory_research.research_iterations import IterationPreset, ResearchIterations
from agent_factory_research.services import ResearchServices
from test_research_iterations import BASELINE, CAPS, Driver, MemoryStore, Scopes


class HTTPStore(MemoryStore):
    def __init__(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.connection = None
        self.local_budget_scopes = Scopes(self)


class ResearchIterationAPITests(unittest.TestCase):
    base = '/api/factory/research-iterations'

    def setUp(self):
        self.store = HTTPStore()
        self.addCleanup(self.store.engine.dispose)
        self.driver = Driver(self.store)
        self.auth = SimpleNamespace(user=Mock(return_value={'id': 'alice'}), require_member=Mock())
        self.preset = IterationPreset('toy', 'alice', 'preset-v1', {'dataset': 'b' * 64}, BASELINE,
                                      {**CAPS, 'rounds': 1, 'toolCalls': 4}, 10)
        self.service = ResearchIterations(self.store, self.auth,
            research=ResearchServices(factory_store=self.store, installed=True),
            presets={'toy': self.preset}, round_driver=self.driver)
        self.client = self.client_for(self.service)
        self.body = {'presetId': 'toy', 'goal': 'Improve the local toy', 'requestId': 'original-start-1',
                     'caps': deepcopy(CAPS), 'deadline': time.time() + 300}
        self.sql = []
        event.listen(self.store.engine, 'before_cursor_execute', self.record_sql)

    def record_sql(self, _conn, _cursor, statement, _params, _context, _many):
        self.sql.append(statement)

    def client_for(self, service):
        app = FastAPI()
        app.include_router(iteration_router(self.auth, service))
        client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(client.close)
        return client

    def start(self):
        response = self.client.post(self.base, json=self.body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def assert_no_writes(self):
        mutations = [sql for sql in self.sql if sql.lstrip().split()[0].upper() in
                     {'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'CREATE', 'DROP', 'ALTER'}]
        self.assertEqual(mutations, [])

    def test_disabled_presets_are_empty_and_cannot_start_an_activity(self):
        client = self.client_for(None)
        self.assertEqual(client.get(self.base + '/presets').json(), [])
        self.assertEqual(client.get(self.base).json(), {'items': []})
        response = client.post(self.base, json=self.body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail'], 'ITERATION_PRESET_UNAVAILABLE')
        self.assertEqual(self.driver.reserved, [])
        self.assert_no_writes()

    def test_catalog_lists_only_the_authenticated_owner_and_membership_is_required(self):
        preset = self.client.get(self.base + '/presets').json()[0]
        self.assertEqual(preset['baseline'], {'metric': 'mean_squared_error', 'value': 16, 'kind': 'reviewedSeed'})
        self.assertEqual(preset['roundCaps'], {**CAPS, 'rounds': 1, 'toolCalls': 4})
        first = self.start()
        self.auth.user.return_value = {'id': 'bob'}
        self.sql.clear()
        self.assertEqual(self.client.get(self.base + '/presets').json(), [])
        self.assertEqual(self.client.get(self.base).json(), {'items': []})
        for path in ['/' + first['activity']['id'], '/requests/' + self.body['requestId']]:
            self.assertEqual(self.client.get(self.base + path).status_code, 404)
        for suffix, body in [('/cancel', {}), ('/reconcile', {}),
                             ('/advance', {'previousRoundId': first['rounds'][0]['id'], 'requestId': 'foreign-advance'})]:
            self.assertEqual(self.client.post(self.base + '/' + first['activity']['id'] + suffix,
                                             json=body).status_code, 404)
        self.assert_no_writes()
        self.assertEqual(self.driver.cancelled, [])
        self.auth.require_member.side_effect = HTTPException(403, 'MEMBER_DISABLED')
        self.assertEqual(self.client.get(self.base + '/presets').status_code, 403)
        self.assertEqual(self.client.post(self.base, json=self.body).status_code, 403)
        self.assertEqual(len(self.driver.dispatched), 1)

    def test_all_gets_preserve_the_original_deadline_and_never_dispatch_or_settle(self):
        first = self.start()
        self.sql.clear()
        for path in ['', '/presets', '/' + first['activity']['id'], '/requests/' + self.body['requestId']]:
            self.assertEqual(self.client.get(self.base + path).status_code, 200)
        recovered = self.client.get(self.base + '/requests/' + self.body['requestId']).json()
        self.assertEqual(recovered, first)
        self.assertEqual(recovered['activity']['deadline'], self.body['deadline'])
        self.assertEqual(recovered['activity']['caps'], self.body['caps'])
        self.assertEqual(len(self.driver.dispatched), 1)
        self.assertEqual(self.driver.cancelled, [])
        self.assert_no_writes()

    def test_strict_caps_reject_missing_unknown_boolean_fractional_and_oversized_values(self):
        invalid = []
        for name in ('rounds', 'toolCalls'):
            value = deepcopy(CAPS)
            del value[name]
            invalid.append(value)
        for name, value in [('rounds', 3), ('rounds', True), ('toolCalls', '8'), ('toolCalls', 0),
                            ('toolCalls', 1001), ('tokenLimit', 1.5), ('amountMicros', -1)]:
            invalid.append({**CAPS, name: value})
        invalid.append({**CAPS, 'extra': 1})
        invalid.append({**CAPS, 'tokenLimit': 20})
        for caps in invalid:
            with self.subTest(caps=caps):
                response = self.client.post(self.base, json={**self.body, 'caps': caps})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.driver.reserved, [])
        self.assert_no_writes()

    def test_omitted_metering_fields_normalize_to_unavailable_not_zero(self):
        response = self.client.post(self.base, json={**self.body, 'caps': {'rounds': 2, 'toolCalls': 8}})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['activity']['caps'], CAPS)
        self.assertIsNone(response.json()['activity']['caps']['tokenLimit'])
        self.assertIsNone(response.json()['activity']['caps']['amountMicros'])
        self.assertIsNone(response.json()['activity']['caps']['currency'])

    def test_deadline_validation_happens_before_dispatch(self):
        for deadline in [time.time() - 1, time.time() + 3700, 'NaN', 'Infinity']:
            with self.subTest(deadline=deadline):
                response = self.client.post(self.base, json={**self.body, 'deadline': deadline})
                self.assertIn(response.status_code, (409, 422), response.text)
        self.assertEqual(self.driver.dispatched, [])
        self.assertEqual(self.client.get(self.base).json(), {'items': []})

    def test_lost_dispatch_ack_is_recovered_by_original_request_without_replay(self):
        self.driver.fail_dispatch = True
        response = self.client.post(self.base, json=self.body)
        self.assertEqual(response.status_code, 500)
        first = self.client.get(self.base + '/requests/' + self.body['requestId']).json()
        self.assertEqual(first['activity']['status'], 'unknown')
        self.assertEqual(first['activity']['deadline'], self.body['deadline'])
        self.sql.clear()
        for _ in range(2):
            response = self.client.get(self.base + '/requests/' + self.body['requestId'])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), first)
        self.assertEqual(self.client.get(self.base + '/requests/not-submitted').status_code, 404)
        self.assertEqual(len(self.driver.dispatched), 1)
        self.assert_no_writes()

    def test_explicit_advance_receipt_and_cancel_preserve_round_lineage(self):
        first = self.start()
        activity, round1 = first['activity']['id'], first['rounds'][0]
        self.driver.stopped(round1)
        settled = self.client.post(self.base + '/' + activity + '/reconcile', json={})
        self.assertEqual(settled.status_code, 200)
        self.assertEqual(settled.json()['activity']['status'], 'ready')
        original = {'previousRoundId': round1['id'], 'requestId': 'original-advance-1'}
        response = self.client.post(self.base + '/' + activity + '/advance', json=original)
        self.assertEqual(response.status_code, 200, response.text)
        self.sql.clear()
        recovered = self.client.get(self.base + '/' + activity).json()
        self.assertEqual(recovered['activity']['advanceRequests'][original['requestId']], round1['id'])
        self.assertEqual(recovered['rounds'][1]['previousRoundId'], round1['id'])
        self.assertEqual(recovered['rounds'][1]['baselineSource']['taskId'], round1['taskId'])
        self.assertEqual(recovered['rounds'][1]['deadline'], self.body['deadline'])
        self.assertEqual(len(self.driver.dispatched), 2)
        self.assert_no_writes()
        response = self.client.post(self.base + '/' + activity + '/cancel', json={})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['activity']['cancelRequested'])
        self.assertEqual(self.driver.cancelled, [recovered['rounds'][1]['taskId']])


if __name__ == '__main__':
    unittest.main()
