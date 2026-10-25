"""Real PostgreSQL source authority and bounded artifact/withdrawal ordering."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Event
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from agent_factory.application_content import ContentPublication
import test_applications_composition as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL')
class ApplicationContentSourcesPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApplicationCompositionPostgresTests('runTest')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.service = self.fixture.state['application_content']
        self.app = self.fixture.publish_http()

    def artifact(self, owner):
        fixture = self.fixture
        fixture.login(owner)
        started = fixture.client.post('/api/factory/application-interface/v1/starts', json={
            'application': self.app['id'], 'applicationRef': fixtures.pin(self.app), 'mode': 'literature',
            'goal': 'Perform a text audit for original synthetic evidence', 'requestId': 'source-test-' + owner})
        self.assertEqual(started.status_code, 202, started.text)
        detail = fixture.wait_job(started.json()['job']['id'])
        self.assertEqual(detail['job']['status'], 'completed', detail)
        artifact = detail['artifacts'][0]
        reference = {'taskId': detail['job']['id'], 'artifactId': artifact['id'], 'sha256': artifact['sha256']}
        return reference, fixture.store.artifact(reference['taskId'], reference['artifactId'])[1]

    def chain(self):
        alice_ref, _ = self.artifact('alice')
        bob_ref, raw = self.artifact('bob')
        def body(record, reference, sources=()):
            return ContentPublication(source={'application': 'fixture', 'record': record, 'revision': '1'},
                content={'record': record}, artifacts=[reference], visibility='team', sourceContentIds=list(sources))
        source = self.service.publish('alice', body('source', alice_ref), 'source-publication')
        derived_body = body('derived', bob_ref, [source['id']])
        derived = self.service.publish('bob', derived_body, 'derived-publication')
        nested_body = body('nested', bob_ref, [derived['id']])
        nested = self.service.publish('bob', nested_body, 'nested-publication')
        return source, derived, nested, derived_body, nested_body, bob_ref, raw

    def test_source_withdrawal_blocks_generic_body_list_bytes_and_original_replay(self):
        source, derived, nested, derived_body, nested_body, reference, raw = self.chain()
        self.assertEqual(set(nested['sourceContentIds']), {source['id'], derived['id']})
        fixture = self.fixture
        prefix = '/api/factory/application-content/'
        fixture.login('alice')
        for publication in (derived, nested):
            url = prefix + publication['id']
            self.assertEqual(fixture.client.get(url).status_code, 200)
            response = fixture.client.get(url + '/artifacts/' + reference['artifactId'])
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.content, raw)
        self.assertEqual(fixture.client.get('/api/factory/jobs/' + reference['taskId']).status_code, 404)
        self.service.set_visibility('alice', source['id'], 'personal', 'withdraw-original-source')
        fixture.login('bob')
        for publication, body, request_id in ((derived, derived_body, 'derived-publication'),
                                             (nested, nested_body, 'nested-publication')):
            url = prefix + publication['id']
            self.assertEqual(fixture.client.get(url).status_code, 404)
            self.assertEqual(fixture.client.get(url + '/artifacts/' + reference['artifactId']).status_code, 404)
            response = fixture.client.post(prefix.rstrip('/'), json={**body.model_dump(), 'requestId': request_id})
            self.assertEqual(response.status_code, 404, response.text)
        listing = fixture.client.get(prefix.rstrip('/')).json()['items']
        self.assertFalse({source['id'], derived['id'], nested['id']} & {item['id'] for item in listing})
        receipt = self.service.set_visibility('bob', derived['id'], 'personal', 'withdraw-unreadable-derived')
        self.assertEqual(receipt['contentState'], 'source_unavailable')
        self.assertEqual(receipt['visibility'], 'personal')
        self.assertNotIn('content', receipt)
        self.assertNotIn('artifacts', receipt)
        replay = self.service.set_visibility('bob', derived['id'], 'personal', 'withdraw-unreadable-derived')
        self.assertEqual(replay, receipt)
        self.service.set_visibility('alice', source['id'], 'team', 'restore-original-source')
        with self.assertRaises(HTTPException):
            self.service.read('alice', nested['id'])
        self.assertEqual(self.service.read('bob', nested['id'])['id'], nested['id'])

    def test_withdrawal_commits_before_waiting_read_admission_denies_bytes(self):
        source, _, nested, _, _, reference, _ = self.chain()
        changed, release, read_started = Event(), Event(), Event()
        original = self.service.sharing.set
        def held_set(conn, owner, ref, visibility):
            result = original(conn, owner, ref, visibility)
            if ref == 'content:' + source['id'] and visibility == 'personal':
                changed.set()
                if not release.wait(10):
                    raise AssertionError('Withdrawal barrier was not released')
            return result
        def read():
            read_started.set()
            return self.service.artifact('bob', nested['id'], reference['artifactId'])
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(self.service.sharing, 'set', held_set):
            withdrawal = pool.submit(self.service.set_visibility, 'alice', source['id'], 'personal', 'barrier-withdraw-first')
            try:
                self.assertTrue(changed.wait(10))
                reader = pool.submit(read)
                self.assertTrue(read_started.wait(10))
            finally:
                release.set()
            self.assertEqual(withdrawal.result(timeout=10)['visibility'], 'personal')
            with self.assertRaises(HTTPException) as error:
                reader.result(timeout=10)
            self.assertEqual(error.exception.status_code, 404)

    def test_admitted_bounded_artifact_snapshot_finishes_before_withdrawal(self):
        source, _, nested, _, _, reference, raw = self.chain()
        admitted, release, withdrawal_started = Event(), Event(), Event()
        original = self.service._artifact
        def held_artifact(owner, value):
            admitted.set()
            if not release.wait(10):
                raise AssertionError('Admitted read barrier was not released')
            return original(owner, value)
        def withdraw():
            withdrawal_started.set()
            return self.service.set_visibility('alice', source['id'], 'personal', 'barrier-read-first')
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(self.service, '_artifact', held_artifact):
            reader = pool.submit(self.service.artifact, 'bob', nested['id'], reference['artifactId'])
            try:
                self.assertTrue(admitted.wait(10))
                withdrawal = pool.submit(withdraw)
                self.assertTrue(withdrawal_started.wait(10))
                self.assertFalse(withdrawal.done())
            finally:
                release.set()
            self.assertEqual(reader.result(timeout=10)[1], raw)
            self.assertEqual(withdrawal.result(timeout=10)['visibility'], 'personal')
        with self.assertRaises(HTTPException) as error:
            self.service.artifact('bob', nested['id'], reference['artifactId'])
        self.assertEqual(error.exception.status_code, 404)
