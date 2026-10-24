"""Real SQLite/services/HTTP operation accounts; no tool or remote dispatch."""
from copy import deepcopy
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from sqlalchemy import select

from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.execution_bindings import ExecutionBindings
from agent_factory.personal_cli import cli_destination
from agent_factory.personal_tools import PersonalTools, OperationAccountRequest
import test_personal_tools as fixtures

ROOT = '/api/factory/personal-tools'


class CliCredentialPolicy:
    normalize_destination = staticmethod(cli_destination)
    __call__ = staticmethod(cli_destination)


class ReusableToolAccountTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PersonalToolTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service = self.fixture.service
        self.client = self.fixture.client
        self.service.vault = EncryptedCredentialVault(self.fixture.engine, b't' * 32,
                                                       {'member-cli': CliCredentialPolicy()})
        self.service.vault.bind_read_context(self.fixture.store._connection)
        self.configuration = {'transport': 'cli', 'toolName': 'public_echo', 'executable': sys.executable,
                              'credentialEnvironmentVariable': 'SYNTHETIC_ACCOUNT_TOKEN'}

    def headers(self, owner='alice'):
        return {'x-fixture-owner': owner}

    def operation(self, **changes):
        return self.service.operations.create('alice', self.configuration | changes, 'publish')

    def account_request(self, operation, request_id='account', credential=None):
        return {'version': operation['operationRef']['version'], 'sha256': operation['operationRef']['sha256'],
                'requestId': request_id, **(credential or {})}

    def account(self, operation, owner='alice', request_id='account'):
        credential = self.service.vault.create(owner=owner, provider_id='member-cli',
            destination=sys.executable, username=owner, password='synthetic-only-' + owner)
        return self.service.configure_operation(owner, operation['operationRef']['id'], OperationAccountRequest(
            **self.account_request(operation, request_id,
                {key: credential[key] for key in ('credentialRef', 'credentialRevision')})))

    def handle(self, account, owner):
        with self.fixture.connections._read() as conn:
            return self.service.binding(conn, owner, account['registrationRef']).opaque_handle

    def test_independent_accounts_share_exact_adapter_and_revoke_independently(self):
        operation = self.operation()
        alice, bob = self.account(operation), self.account(operation, 'bob')
        bob_second = self.account(operation, 'bob', 'second-account')
        self.assertEqual(alice['runtimeBinding'], bob['runtimeBinding'])
        self.assertEqual(bob['runtimeBinding'], bob_second['runtimeBinding'])
        self.assertEqual(len({row['registrationRef'] for row in (alice, bob, bob_second)}), 3)
        first, second = self.handle(alice, 'alice'), self.handle(bob, 'bob')
        self.assertIs(first.adapter, second.adapter)
        self.assertEqual(first.resolve_credential().username, 'alice')
        self.assertEqual(second.resolve_credential().username, 'bob')
        self.service.share('alice', alice['registrationRef'], 'team', 'share')
        shared = self.handle(alice, 'bob')
        self.assertEqual((shared.requesting_actor, shared.owner), ('bob', 'alice'))
        self.assertEqual(shared.resolve_credential().username, 'alice')
        projection = self.service.inspect('bob', alice['registrationRef'])
        self.assertNotIn('credentialRef', projection)
        self.assertNotIn('credentialRevision', projection)
        self.service.revoke('alice', alice['registrationRef'], 'revoke')
        with self.assertRaises(HTTPException):
            shared.check_authorized()
        second.check_authorized()
        self.assertEqual(self.service.inspect('bob', bob['registrationRef'])['status'], 'configured')

    def test_http_operation_and_account_receipts_are_idempotent(self):
        payload = {'configuration': self.configuration, 'requestId': 'publish'}
        created = self.client.post(ROOT + '/operations', headers=self.headers(), json=payload)
        self.assertEqual(created.status_code, 201)
        operation = created.json()
        self.assertEqual(self.client.post(ROOT + '/operations', headers=self.headers(), json=payload).json(), operation)
        receipt = self.client.get(ROOT + '/requests/publish', headers=self.headers()).json()
        self.assertEqual(receipt['operation'], operation)
        path = ROOT + '/operations/' + operation['operationRef']['id'] + '/accounts'
        account = self.account_request(operation)
        response = self.client.post(path, headers=self.headers('bob'), json=account)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.post(path, headers=self.headers('bob'), json=account).json(), response.json())
        receipt = self.client.get(ROOT + '/requests/account', headers=self.headers('bob')).json()
        self.assertEqual(receipt['tool'], response.json())
        conflict = self.client.post(ROOT + '/operations', headers=self.headers(),
            json=payload | {'configuration': self.configuration | {'arguments': ['different']}})
        self.assertEqual(conflict.status_code, 409)

    def test_http_hash_mismatch_and_malformed_accounts_do_not_create_resources(self):
        operation = self.operation()
        path = ROOT + '/operations/' + operation['operationRef']['id'] + '/accounts'
        request = self.account_request(operation)
        wrong = self.client.post(path, headers=self.headers('bob'), json=request | {'sha256': '0' * 64})
        self.assertEqual(wrong.status_code, 409)
        for change in ({'version': True}, {'version': '1'}, {'version': 0}, {'sha256': 'bad'},
                       {'credentialRef': 'synthetic-private'}, {'credentialRevision': 'synthetic-private'},
                       {'configuration': {'arguments': ['synthetic-private']}}):
            with self.subTest(change=change):
                response = self.client.post(path, headers=self.headers('bob'), json=request | change)
                self.assertEqual(response.status_code, 422)
                self.assertNotIn('synthetic-private', response.text)
        self.assertEqual(self.service.list('bob'), [])

    def test_unavailable_saved_operation_does_not_block_healthy_restore(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        missing = Path(directory.name).resolve() / 'synthetic-only-cli'
        self.assertFalse(missing.exists())
        unavailable = self.service.operations.create('alice', self.configuration |
            {'executable': str(missing)}, 'unavailable')
        healthy = self.operation()
        alice, bob = self.account(healthy), self.account(healthy, 'bob')
        restarted = PersonalTools(self.fixture.connections, self.service.vault, ())
        bindings = ExecutionBindings(SimpleNamespace(), self.fixture.store)
        restarted.register(bindings)
        adapter_id = healthy['runtimeBinding']['adapterId']
        self.assertIn(('tool', adapter_id, '1'), bindings._adapters)
        self.assertNotIn(unavailable['runtimeBinding']['adapterId'], restarted.adapters)
        handles = []
        with self.fixture.connections._read() as conn:
            for owner, account in (('alice', alice), ('bob', bob)):
                handles.append(restarted.binding(conn, owner, account['registrationRef']).opaque_handle)
        self.assertIs(handles[0].adapter, handles[1].adapter)
        self.assertIs(handles[0].adapter, restarted.adapters[adapter_id])

    def test_operation_tampering_rejects_existing_handle_and_restoration(self):
        operation = self.operation()
        account = self.account(operation)
        handle = self.handle(account, 'alice')
        table = self.service.operations.operations
        with self.fixture.connections._write() as conn:
            body = deepcopy(conn.execute(select(table.c.body).where(
                table.c.operation_id == operation['operationRef']['id'])).scalar_one())
            body['arguments'] = ['changed-after-binding']
            conn.execute(table.update().where(table.c.operation_id == operation['operationRef']['id']).values(body=body))
        with self.assertRaises(HTTPException) as caught:
            handle.check_authorized()
        self.assertEqual(caught.exception.detail, 'TOOL_OPERATION_INTEGRITY_FAILED')
        restarted = PersonalTools(self.fixture.connections, self.service.vault, ())
        with self.assertRaises(HTTPException) as caught:
            restarted.register(ExecutionBindings(SimpleNamespace(), self.fixture.store))
        self.assertEqual(caught.exception.detail, 'TOOL_OPERATION_INTEGRITY_FAILED')
