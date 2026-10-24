"""SQLite operation persistence using the existing connection custody fixture."""
from contextlib import nullcontext
from unittest.mock import patch
from copy import deepcopy
import sys
import unittest

from fastapi import HTTPException
from sqlalchemy import select

from agent_factory.member_tool_operations import MemberToolOperations
import test_personal_tools as fixtures


class MemberToolOperationsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PersonalToolTests('runTest')
        # Reuse the real SQLite connection/vault fixture without starting its
        # unrelated HTTP client's async thread: these are synchronous service tests.
        with patch.object(fixtures, 'TestClient', return_value=nullcontext()):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service = self.fixture.service
        self.operations = MemberToolOperations(self.service)
        self.configuration = {'transport': 'cli', 'toolName': 'public_echo', 'executable': sys.executable}

    def test_public_reads_independent_of_private_resources(self):
        self.fixture.configure()
        self.assertEqual(self.operations.list('bob'), [])
        value = self.operations.create('alice', self.configuration, 'publish')
        ref = value['operationRef']
        self.assertEqual(self.operations.get('bob', ref['id'], ref['version'], ref['sha256']), value)
        self.assertEqual(self.operations.list('bob'), [value])
        self.assertEqual(value['ownerId'], 'alice')
        self.assertNotIn('credentialRef', str(value))
        self.assertEqual(value['runtimeBinding']['config'], {'operationSha256': ref['sha256']})

    def test_replay_conflict_and_result_resolution(self):
        first = self.operations.create('alice', self.configuration, 'publish')
        self.assertEqual(self.operations.create('alice', self.configuration, 'publish'), first)
        with self.assertRaises(HTTPException) as caught:
            self.operations.create('alice', self.configuration | {'arguments': ['changed']}, 'publish')
        self.assertEqual(caught.exception.status_code, 409)
        with self.fixture.connections._read() as conn:
            command = conn.execute(select(self.fixture.connections.commands).where(
                self.fixture.connections.commands.c.request_id == 'publish')).mappings().one()
        self.assertEqual(command['action'], 'tool.operation.create')
        self.assertEqual(self.operations.result('alice', command['result_ref']), first)
        with self.assertRaises(HTTPException):
            self.operations.result('alice', 'not-json')

    def test_replay_keeps_write_connection_and_public_result_reads_once(self):
        first = self.operations.create('alice', self.configuration, 'publish')
        connections = self.fixture.connections
        with patch.object(connections, '_read', side_effect=AssertionError('nested read connection')):
            self.assertEqual(self.operations.create('alice', self.configuration, 'publish'), first)
        with connections._read() as conn:
            result_ref = conn.execute(select(connections.commands.c.result_ref).where(
                connections.commands.c.request_id == 'publish')).scalar_one()
        with patch.object(connections, '_read', wraps=connections._read) as read:
            self.assertEqual(self.operations.result('bob', result_ref), first)
        read.assert_called_once_with()

    def test_invalid_metadata_rejected_even_with_recomputed_fingerprint(self):
        from agent_factory.store import digest
        for field, bad in (('owner_id', ''), ('operation_id', 'bad id'), ('created_at', 'x' * 65)):
            with self.subTest(field=field):
                value = self.operations.create('alice', self.configuration, 'metadata-' + field)
                adapter_id = value['runtimeBinding']['adapterId']
                with self.fixture.connections._write() as conn:
                    data = dict(conn.execute(select(self.operations.operations).where(
                        self.operations.operations.c.adapter_id == adapter_id)).mappings().one())
                    data.pop('fingerprint')
                    data[field] = bad
                    # A plain fingerprint detects corruption, not a privileged
                    # writer; validate the stored field contract independently.
                    conn.execute(self.operations.operations.update().where(
                        self.operations.operations.c.adapter_id == adapter_id).values(
                            **data, fingerprint=digest(data)))
                with self.assertRaises(HTTPException) as caught:
                    self.operations.by_adapter(adapter_id)
                self.assertEqual(caught.exception.detail, 'TOOL_OPERATION_INTEGRITY_FAILED')

    def test_versions_are_immutable_and_owner_scoped(self):
        first = self.operations.create('alice', self.configuration, 'publish')
        ref = first['operationRef']
        second = self.operations.create('alice', self.configuration | {'arguments': ['changed']}, 'update', ref['id'])
        self.assertEqual(second['operationRef']['version'], 2)
        self.assertNotEqual(first['runtimeBinding']['adapterId'], second['runtimeBinding']['adapterId'])
        self.assertEqual(self.operations.get('bob', ref['id'], 1), first)
        with self.assertRaises(HTTPException) as caught:
            self.operations.create('bob', self.configuration, 'take-over', ref['id'])
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException) as caught:
            self.operations.get('bob', ref['id'], 1, 'wrong-hash')
        self.assertEqual(caught.exception.status_code, 409)

    def test_restart_restores_operation_without_any_account(self):
        first = self.operations.create('alice', self.configuration, 'publish')
        restarted = MemberToolOperations(self.service)
        adapter_id = first['runtimeBinding']['adapterId']
        self.assertEqual(restarted.by_adapter(adapter_id), first)
        restored = restarted.restore_adapter(adapter_id)
        self.assertEqual(restored.descriptor.adapter_id, adapter_id)
        self.assertEqual(restored.configuration, first['configuration'])
        self.assertNotIn(adapter_id, self.service.adapters)
        self.assertIsNone(restarted.by_adapter('not-installed'))
        self.assertIsNone(restarted.restore_adapter('not-installed'))

    def test_equal_recipe_hash_does_not_include_generated_identity(self):
        alice = self.operations.create('alice', self.configuration, 'publish')
        bob = self.operations.create('bob', self.configuration, 'publish')
        self.assertEqual(alice['operationRef']['sha256'], bob['operationRef']['sha256'])
        self.assertNotEqual(alice['operationRef']['id'], bob['operationRef']['id'])
        self.assertNotEqual(alice['runtimeBinding']['adapterId'], bob['runtimeBinding']['adapterId'])

    def test_tampered_body_or_metadata_fails_closed(self):
        for field in ('body', 'hash', 'owner_id', 'fingerprint'):
            with self.subTest(field=field):
                value = self.operations.create('alice', self.configuration, 'publish-' + field)
                ref = value['operationRef']
                changed = deepcopy(value['configuration']) if field == 'body' else 'tampered'
                if field == 'body':
                    changed['arguments'] = ['untrusted-change']
                with self.fixture.connections._write() as conn:
                    conn.execute(self.operations.operations.update().where(
                        self.operations.operations.c.operation_id == ref['id']).values(**{field: changed}))
                with self.assertRaises(HTTPException) as caught:
                    self.operations.get('alice', ref['id'], 1)
                self.assertEqual(caught.exception.detail, 'TOOL_OPERATION_INTEGRITY_FAILED')
                with self.assertRaises(HTTPException):
                    self.operations.restore_adapter(value['runtimeBinding']['adapterId'])

    def test_auth_and_invalid_configuration_have_no_write(self):
        from unittest.mock import patch
        with patch.object(self.fixture.auth, 'require_member', side_effect=HTTPException(403, 'disabled')):
            for call in (lambda: self.operations.create('alice', self.configuration, 'x'),
                         lambda: self.operations.list('alice'),
                         lambda: self.operations.get('alice', 'x', 1)):
                with self.assertRaises(HTTPException):
                    call()
        with self.assertRaises(HTTPException) as caught:
            self.operations.create('alice', self.configuration | {'credentialRef': 'SYNTHETIC'}, 'bad')
        self.assertEqual(caught.exception.detail, 'TOOL_OPERATION_CONFIGURATION_INVALID')
        self.assertEqual(self.operations.list('alice'), [])
