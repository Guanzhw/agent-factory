"""Real native completion/settlement; synthetic decisions and seeded historical pin."""
import json
import os
from threading import Event
import unittest
from unittest.mock import patch

from agno.models.response import ModelResponse
from fastapi import HTTPException
from sqlalchemy import select

from agent_factory.store import canonical, digest
import test_research_workflow_postgres as native

OLD_PIN = {'kind': 'workflow', 'id': 'research-round', 'revision': '1',
    'sha256': '2c1fcb5650d8473d2171f6d374035b8d4db452b53603337e2b13f3b43f661c54'}


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class ResearchPublicationPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = native.ResearchNativeWorkflowTests('runTest')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.state, self.client = self.base.state, self.base.client

    def rollback(self, phase, *, historical=False):
        store, rounds = self.state['store'], self.state['research_rounds']
        target, method = (store, 'artifact_write') if phase == 'artifact' else (self.state['application_content'], 'publish')
        original = getattr(target, method)
        failed, release = Event(), Event()
        decision = {'action': 'stop', 'outcome': 'not_met', 'reason': '分析' * 950}
        def response(model, messages):
            return ModelResponse(role='assistant', content=json.dumps(decision))
        def fail_after_write(*args, **kwargs):
            value = original(*args, **kwargs)
            if not release.is_set():
                failed.set()
                raise RuntimeError('Controlled post-' + phase + ' failure')
            return value
        with patch.object(native.ResearchModel, '_response', response), patch.object(target, method, fail_after_write):
            receipt = self.base.start('目标' * 750)
            self.assertTrue(failed.wait(15), 'Original long-body finalization was not reached')
            task = store.task(receipt['execution']['taskId'], 'alice')
            self.assertFalse(task['terminal'])
            self.assertEqual(task['body']['stoppedStatus'], 'completed')
            self.assertEqual(store.artifacts(task['id']), [])
            self.assertFalse(any(event['type'] == 'artifact' for event in store.events(task['id'])))
            self.assertEqual(self.state['application_content'].list('alice')['items'], [])
            self.assertEqual(store.local_budget_scopes.inspect('alice', receipt['scopeId'])['allocations'][0]['state'], 'BOUND')
            with store.transaction(read_only=True) as conn:
                row = conn.execute(select(rounds.rounds).where(rounds.rounds.c.id == receipt['roundId'])).mappings().one()
                self.assertIsNone(row['terminal'])
                self.assertEqual(row['decision']['reason'], decision['reason'])
            if historical:
                # Seed the immutable pre-upgrade identity after the actual native run stopped.
                plan = store.plan(task['plan_id'], 'alice')
                plan['nativeComponent'] = OLD_PIN
                store.sql('UPDATE af_plans SET body=CAST(:body AS JSONB), hash=:hash WHERE id=:id',
                          body=canonical(plan), hash=digest(plan), id=plan['id'])
                owners = store.application_runtime.owners(task)
                self.assertEqual(len(owners), 1)
                self.assertIsNotNone(store.application_runtime.finalization_context(task))
                self.assertIsNone(store.application_runtime.callback(owners[0], 'observe_waits'))
                self.assertIsNone(store.application_runtime.callback(owners[0], 'reconcile'))
                with self.assertRaises(HTTPException) as no_new_executor:
                    store.native_workflows.require_plan_current('alice', plan)
                self.assertEqual(no_new_executor.exception.detail, 'NATIVE_WORKFLOW_CHANGED')
                with patch.object(store, 'plan', return_value={**plan, 'nativeComponent': {**OLD_PIN, 'revision': '2'}}):
                    self.assertIsNone(store.application_runtime.finalization_context(task))
            release.set()
            self.base.completed(task['id'])
        self.assertEqual(len(store.tasks('alice')), 1)
        self.assertEqual(len(store.artifacts(task['id'])), 1)
        self.assertEqual(store.local_budget_scopes.inspect('alice', receipt['scopeId'])['allocations'][0]['state'], 'SETTLED')
        records = self.client.get(self.base.url + '/experiments').json()['rounds']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['decision']['reason'], decision['reason'])
        identifier = records[0]['terminalRecordId']
        content = self.client.get('/api/factory/application-content/' + identifier)
        self.assertEqual(content.status_code, 200, content.text)
        self.assertEqual(content.json()['content']['decision']['reason'], decision['reason'])
        self.assertEqual(content.json()['content']['agreement']['objective'], '目标' * 750)
        self.assertEqual(content.json()['artifacts'], [])

    def test_artifact_write_failure_rolls_back_real_terminal_and_settlement(self):
        self.rollback('artifact')

    def test_old_exact_pin_publication_failure_recovers_only_original_completion(self):
        self.rollback('publication', historical=True)
