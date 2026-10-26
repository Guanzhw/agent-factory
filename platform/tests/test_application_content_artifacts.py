"""Body artifacts keep content authority and the original twenty evidence slots."""
import json
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from agent_factory.application_content import ApplicationContent, ContentPublication
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import digest
from fixture_content_artifacts import artifact_ref, install_artifacts
from test_applications_composition import ApplicationCompositionFixture


class ContentArtifactTests(ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.task, self.run = install_artifacts(self.store)
        self.service = ApplicationContent(self.store, self.auth, ResourceSharing(self.store, self.auth))
        self.source = {'application': 'research', 'record': 'long-original', 'revision': 'terminal'}
        self.content = {'objective': '目标' * 750, 'decision': {'reason': '分析' * 950, 'outcome': 'not_met'}}

    def body(self, content=None, **extra):
        raw = json.dumps(self.content if content is None else content, ensure_ascii=False).encode()
        return ContentPublication(source=self.source, contentArtifact=artifact_ref(self.store, self.run, raw),
                                  visibility='team', **extra)

    def test_full_body_with_twenty_evidence_artifacts_and_pagination(self):
        selected = [artifact_ref(self.store, self.run, b'{"value": 1}', name=f'evidence-{i}.json') for i in range(20)]
        body = self.body(artifacts=selected)
        first = self.service.publish('alice', body, 'body-publication')
        second = self.service.publish('alice', body, 'body-publication-two')
        self.assertEqual(self.service.publish('alice', body, 'body-publication')['id'], first['id'])
        self.assertEqual(self.service.read('bob', first['id'])['content'], self.content)
        self.assertEqual(first['artifacts'], selected)
        self.assertNotIn(first['contentArtifact'], first['artifacts'])
        page = self.service.list('bob', limit=1)
        self.assertEqual(page['items'][0]['content'], self.content)
        tail = self.service.list('bob', after=page['nextCursor'], limit=1)
        self.assertEqual({page['items'][0]['id'], tail['items'][0]['id']}, {first['id'], second['id']})
        ref = body.contentArtifact
        self.assertEqual(json.loads(self.service.artifact('bob', first['id'], ref.artifactId)[1]), self.content)

    def test_source_withdrawal_precedes_body_reads_and_damage_never_uses_copy(self):
        source = self.service.publish('alice', ContentPublication(source=self.source,
            content={'condition': 'original'}, visibility='team'), 'original-source')
        body = self.body(sourceContentIds=[source['id']])
        published = self.service.publish('alice', body, 'derived-long-body')
        self.service.set_visibility('alice', source['id'], 'personal', 'withdraw-body-source')
        with patch.object(self.service, '_artifact', side_effect=AssertionError('read before authorization')):
            with self.assertRaises(HTTPException):
                self.service.read('bob', published['id'])
            self.assertEqual(self.service.list('bob')['items'], [])
        self.service.set_visibility('alice', source['id'], 'team', 'restore-body-source')
        self.store.sql('UPDATE af_artifacts SET content=:raw WHERE id=:id',
            raw=b'corrupt', id=body.contentArtifact.artifactId)
        with self.assertRaises(HTTPException) as broken:
            self.service.read('bob', published['id'])
        self.assertEqual(broken.exception.status_code, 409)
        self.store.sql('DELETE FROM af_artifacts WHERE id=:id', id=body.contentArtifact.artifactId)
        with self.assertRaises(HTTPException) as missing:
            self.service.read('bob', published['id'])
        self.assertEqual(missing.exception.status_code, 404)

    def test_body_reference_cannot_bypass_json_shape_safety_or_owner(self):
        for content in ([], {'password': 'synthetic-secret'}, {'text': 'x' * 17000}, {'n': float('nan')}):
            with self.subTest(content_type=type(content).__name__):
                body = self.body(content)
                with self.assertRaises(HTTPException) as invalid:
                    self.service.publish('alice', body, 'invalid-body')
                self.assertEqual(invalid.exception.status_code, 422)
        body = self.body()
        with self.assertRaises(HTTPException) as stolen:
            self.service.publish('bob', body, 'not-my-body')
        self.assertEqual(stolen.exception.status_code, 404)
        with self.assertRaises(ValidationError):
            ContentPublication(source=self.source, content={}, contentArtifact=body.contentArtifact)
        with self.assertRaises(ValidationError):
            ContentPublication(source=self.source)

    def test_old_inline_fingerprint_is_unchanged_and_replay_remains_readable(self):
        original = {'source': self.source, 'content': {'text': 'original inline'},
                    'artifacts': [], 'visibility': 'team'}
        published = self.service.publish('alice', ContentPublication(**original), 'old-inline-request')
        with self.service.db.read() as conn:
            fingerprint = conn.execute(select(self.service.commands.c.fingerprint)).scalar_one()
        self.assertEqual(fingerprint, digest({'action': 'publish', **original}))
        self.assertNotIn('contentArtifact', published)
        self.assertEqual(self.service.publish('alice', ContentPublication(**original), 'old-inline-request'), published)
