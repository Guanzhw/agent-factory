from uuid import uuid4
from unittest.mock import patch

from fastapi import HTTPException

from agent_factory.application_content import ApplicationContent, ContentPublication
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import digest
from test_applications_composition import ApplicationCompositionFixture


class ContentSourceAuthorityTests(ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.service = ApplicationContent(self.store, self.auth, ResourceSharing(self.store, self.auth))
        self.body = ContentPublication(source={'application': 'research', 'record': 'experiment-1', 'revision': '1'},
            content={'state': 'negative-result', 'analysis': 'Agent interpretation'}, visibility='team')

    def publish(self, key='publication-1'):
        return self.service.publish('alice', self.body, key)

    def derived(self, owner, sources, key):
        body = ContentPublication(source={'application': 'research', 'record': key, 'revision': '1'},
            content={'analysis': 'derived-source-canary'}, visibility='team', sourceContentIds=sources)
        return body, self.service.publish(owner, body, key)

    def test_all_original_sources_follow_nested_derivation_and_replay(self):
        source = self.publish()
        body, derived = self.derived('bob', [source['id']], 'derived-first')
        _, nested = self.derived('bob', [derived['id']], 'derived-second')
        self.assertEqual(set(nested['sourceContentIds']), {source['id'], derived['id']})
        self.service.set_visibility('alice', source['id'], 'personal', 'withdraw-source')
        for identifier in (derived['id'], nested['id']):
            with self.subTest(identifier=identifier), self.assertRaises(HTTPException):
                self.service.read('bob', identifier)
            with self.assertRaises(HTTPException), patch.object(self.service, '_artifact') as artifact:
                self.service.artifact('bob', identifier, str(uuid4()))
            artifact.assert_not_called()
        self.assertEqual(self.service.list('bob')['items'], [])
        with self.assertRaises(HTTPException):
            self.service.publish('bob', body, 'derived-first')
        receipt = self.service.set_visibility('bob', derived['id'], 'personal', 'withdraw-derived')
        self.assertEqual(receipt['contentState'], 'source_unavailable')
        self.assertEqual(receipt['visibility'], 'personal')
        self.assertTrue(receipt['isOwner'])
        self.assertFalse({'content', 'artifacts', 'sourceContentIds', 'source'} & receipt.keys())

    def test_owner_and_disabled_source_author_are_checked(self):
        source = self.publish()
        _, derived = self.derived('bob', [source['id']], 'member-derived')
        self.auth.directory.set_disabled('alice', True)
        with self.assertRaises(HTTPException) as error:
            self.service.read('bob', derived['id'])
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(self.service.list('bob')['items'], [])

    def test_private_or_missing_sources_do_not_create_a_publication(self):
        source = self.publish()
        self.service.set_visibility('alice', source['id'], 'personal', 'private-source')
        for identifier in (source['id'], str(uuid4())):
            with self.subTest(identifier=identifier), self.assertRaises(HTTPException):
                self.derived('bob', [identifier], 'unavailable-' + identifier)
        self.assertEqual(self.service.list('bob')['items'], [])

    def test_legacy_command_fingerprint_survives_new_empty_default(self):
        original = self.publish()
        legacy = {'source': {'application': 'research', 'record': 'experiment-1', 'revision': '1'},
                  'content': {'state': 'negative-result', 'analysis': 'Agent interpretation'},
                  'artifacts': [], 'visibility': 'team'}
        with self.service.db.write() as conn:
            conn.execute(self.service.commands.update().values(fingerprint=digest({'action': 'publish', **legacy})))
        replay = self.service.publish('alice', ContentPublication(**legacy, sourceContentIds=[]), 'publication-1')
        self.assertEqual(replay['id'], original['id'])
        self.assertNotIn('sourceContentIds', replay)

    def test_dependency_input_change_conflicts_and_storage_errors_are_not_redacted(self):
        first = self.publish()
        second = self.publish('publication-2')
        body, derived = self.derived('bob', [first['id']], 'exact-input')
        with self.assertRaises(HTTPException) as error:
            self.service.publish('bob', body.model_copy(update={'sourceContentIds': [second['id']]}), 'exact-input')
        self.assertEqual(error.exception.status_code, 409)
        with patch.object(self.service, '_readable', side_effect=RuntimeError('storage fault')):
            with self.assertRaisesRegex(RuntimeError, 'storage fault'):
                self.service.set_visibility('bob', derived['id'], 'personal', 'storage-fault-sharing')
        self.assertEqual(self.service.read('bob', derived['id'])['visibility'], 'team')
