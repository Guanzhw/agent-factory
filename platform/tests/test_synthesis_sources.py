# pyright: reportMissingImports=false
"""Actual SQLite journal and bounded verified ZIP fixtures, no models/network."""
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, select

from agent_factory.synthesis_sources import SynthesisSourceService
from agent_factory.orx_literature_tools import evidence_record
from test_literature_projection import EvidenceStore


class Auth:
    denied = False

    def require(self, owner, action):
        if self.denied:
            raise HTTPException(403, 'revoked')


class Store(EvidenceStore):
    def __init__(self, directory):
        super().__init__()
        self.engine = create_engine('sqlite:///' + str(Path(directory) / 'journal.sqlite'))
        self._connection = ContextVar('synthesis-test-connection', default=None)
        self.task_body = {'id': 'task', 'plan_id': 'plan', 'owner_id': 'alice', 'run_id': 'native-run',
                          'terminal': True, 'cancel_requested': False, 'body': {'lastStatus': 'completed'}}

    def task(self, task, owner):
        super().task(task, owner)
        return deepcopy(self.task_body)


class SynthesisSourceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        self.store = Store(directory.name); self.addCleanup(self.store.engine.dispose)
        self.auth = Auth(); self.service = SynthesisSourceService(self.store, self.auth)
        self.preview = self.service.preview('alice', 'task')

    def create(self, **changes):
        return self.service.create('alice', **{'source_task_id': 'task', 'source_ids': ['123'],
            'question': 'What does the excerpt support?', 'expected_fingerprint': self.preview['fingerprint'],
            'request_id': 'original-command', **changes})

    def test_exact_server_evidence_pins_question_context_and_restart_replay(self):
        value = self.create()
        self.assertEqual(value['projection'], self.preview['projection'])
        self.assertEqual(value['sourceRunId'], 'native-run')
        self.assertEqual(value['artifacts'], self.preview['artifacts'])
        self.assertEqual(value['requestId'], 'original-command')
        service = SynthesisSourceService(self.store, self.auth)
        self.assertEqual(service.read('alice', value['id']), value)
        self.assertEqual(self.create(), value)
        self.assertEqual(service.revalidate('alice', value['id'], expected_fingerprint=value['fingerprint']), value)
        value['projection']['sources'].clear()
        self.assertEqual(service.read('alice', value['id'])['projection']['sourceCount'], 1)
        with self.store.engine.connect() as conn:
            self.assertEqual(len(conn.execute(select(service.snapshots)).all()), 1)

    def test_cross_owner_denied_before_artifact_reads_and_no_list_leak(self):
        value = self.create(); before = self.store.reads
        for operation in (lambda: self.service.preview('bob', 'task'), lambda: self.service.read('bob', value['id']),
                          lambda: self.service.revalidate('bob', value['id'])):
            with self.assertRaises(HTTPException) as error: operation()
            self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(self.store.reads, before)
        self.assertEqual(self.service.list('bob')['items'], [])

    def test_lost_reply_list_filter_pagination_and_conflicting_command(self):
        first = self.create()
        second = self.create(request_id='second-command', question='Other synthetic question')
        page = self.service.list('alice', source_task_id='task', limit=1)
        self.assertEqual(page['items'][0], second)
        self.assertEqual(self.service.list('alice', source_task_id='task', after_id=page['nextCursor'], limit=1)['items'], [first])
        with self.assertRaises(HTTPException) as error: self.create(question='Changed command intent')
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException): self.service.list('bob', after_id=first['id'])

    def test_artifact_tamper_missing_and_changed_metadata_are_not_replayed(self):
        value = self.create()
        self.store.content['bundle'] += b'tampered'
        with self.assertRaises(HTTPException): self.service.revalidate('alice', value['id'])
        with self.assertRaises(HTTPException): self.create()
        # Historical snapshot remains readable; it cannot authorize fresh use.
        self.assertEqual(self.service.read('alice', value['id']), value)
        self.store.rebuild(); self.store.rows[0]['provenance']['newFact'] = 'changed'
        with self.assertRaises(HTTPException): self.service.revalidate('alice', value['id'])
        self.store.rows.clear()
        with self.assertRaises(HTTPException): self.service.preview('alice', 'task')

    def test_changed_run_plan_and_snapshot_hash_rejected(self):
        value = self.create()
        self.store.task_body['run_id'] = 'another-run'
        with self.assertRaises(HTTPException): self.service.revalidate('alice', value['id'])
        self.store.task_body['run_id'] = 'native-run'
        self.store.plan_body['newField'] = 'changed'
        with self.assertRaises(HTTPException): self.service.revalidate('alice', value['id'])
        body = deepcopy(value); body['question'] = 'tamper'
        with self.store.engine.begin() as conn:
            conn.execute(self.service.snapshots.update().values(body=body))
        with self.assertRaises(HTTPException): self.service.read('alice', value['id'])

    def test_incomplete_empty_and_invalid_selections_do_not_create(self):
        for ids in ([], ['123', '123'], ['unknown']):
            with self.assertRaises(HTTPException): self.create(source_ids=ids)
        for question in (' ', 'x' * 1001):
            with self.assertRaises(HTTPException): self.create(question=question)
        with self.assertRaises(HTTPException): self.create(expected_fingerprint='f' * 64)
        for status in ('running', 'failed', 'canceled', 'unknown'):
            self.store.task_body['body']['lastStatus'] = status
            with self.assertRaises(HTTPException): self.service.preview('alice', 'task')
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(self.service.snapshots)).all(), [])

    def test_current_authority_rechecked_on_read_replay_and_consumption(self):
        value = self.create(); self.auth.denied = True
        for call in (lambda: self.create(), lambda: self.service.read('alice', value['id']),
                     lambda: self.service.list('alice'), lambda: self.service.revalidate('alice', value['id'])):
            with self.assertRaises(HTTPException) as error: call()
            self.assertEqual(error.exception.status_code, 403)

    def test_selection_subset_keeps_original_conservative_provenance_and_errors(self):
        self.store.sources.append({**evidence_record('456', 'Second public excerpt', status='abstract_only', field='abstract'),
                                   'evidenceKind': 'public_literature_excerpt'})
        self.store.provenance['retrievalErrors'] = ['TIMEOUT']; self.store.rebuild()
        self.preview = self.service.preview('alice', 'task')
        value = self.create(source_ids=['456'])
        self.assertEqual(value['sourceIds'], ['456'])
        self.assertEqual(value['projection']['evidenceKind'], 'controlled_literature_fixture')
        self.assertEqual(value['projection']['retrievalErrors'], ['TIMEOUT'])
        self.assertEqual(value['projection']['sourceCount'], 1)

    def test_stale_between_initial_read_and_commit_rolls_back(self):
        original = self.service.preview; calls = 0
        def preview(owner, source_task_id):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.store.task_body['run_id'] = 'replacement'
            return original(owner, source_task_id)
        self.service.preview = preview
        with self.assertRaises(HTTPException): self.create()
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(self.service.snapshots)).all(), [])
            self.assertEqual(conn.execute(select(self.service.commands)).all(), [])


if __name__ == '__main__':
    unittest.main()
