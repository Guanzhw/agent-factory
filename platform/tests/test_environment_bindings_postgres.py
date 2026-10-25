"""Credential journal on disposable PostgreSQL; no runtime or model effects."""
from copy import deepcopy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from agent_factory.application_environments import ApplicationEnvironments, environment_router
from pg_fixture import IsolatedPostgres
import test_application_environments as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL') and sys.platform == 'linux',
    'Requires disposable PostgreSQL and Linux custody fences')
class EnvironmentBindingPostgresTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApplicationEnvironmentTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL'])
        self.database.__enter__(); self.addCleanup(self.database.__exit__, None, None, None)
        self.engine = create_engine(self.database.url); self.addCleanup(self.engine.dispose)
        self.service = self.reopen()

    def reopen(self):
        original = self.fixture.service
        return ApplicationEnvironments(SimpleNamespace(engine=self.engine,
            settings=SimpleNamespace(workspace=Path(self.fixture.folder.name))),
            original.auth, original.models, original.connections, {'fixture-runtime': self.fixture.package})

    def stopped(self):
        env = self.service.prepare('alice', 'fixture-runtime', 'pg-original-prepare')['environment']
        self.service.stop('alice', env['id'], 'pg-original-stop')
        self.fixture.model_revision = 'verified-rotated-model'
        return env, self.service.bindings.preview('alice', env['id'])

    def test_restart_original_journal_and_explicit_restore_keep_original_body_and_identity(self):
        env, preview = self.stopped()
        with self.service.db.read() as conn: before = deepcopy(self.service._row(conn, 'alice', env['id']))
        first = self.service.bindings.rebind('alice', env['id'], 'pg-original-binding', preview['previewHash'])
        self.assertFalse(first['runtimePrepared']); self.assertEqual(len(self.fixture.prepares), 1)
        self.service = self.reopen()
        self.assertEqual(self.service.bindings.request('alice', 'pg-original-binding'), first)
        self.assertEqual(self.service.bindings.rebind('alice', env['id'], 'pg-original-binding', preview['previewHash']), first)
        self.assertEqual(len(self.service.bindings.history('alice', env['id'])), 1)
        with self.service.db.read() as conn: after = self.service._row(conn, 'alice', env['id'])
        self.assertEqual(after['body'], before['body']); self.assertEqual(after['body_hash'], before['body_hash'])
        restored = self.service.prepare('alice', 'fixture-runtime', 'pg-explicit-restore')['environment']
        self.assertEqual(restored['id'], env['id']); self.assertEqual(restored['projectId'], env['projectId'])
        self.assertEqual(restored['originalModelRevision'], env['modelRevision'])
        self.assertEqual(restored['modelRevision'], 'verified-rotated-model'); self.assertEqual(self.fixture.research, [])

    def test_actual_http_owner_and_consent_guards_precede_journal_and_unknown_get_never_rebinds(self):
        env, preview = self.stopped(); actor = ['alice']
        app = FastAPI(); app.include_router(environment_router(SimpleNamespace(user=lambda _: {'id': actor[0]}), self.service))
        with TestClient(app, base_url="https://testserver") as client:
            path = '/api/factory/application-environments/' + env['id'] + '/rebind'
            body = {'requestId': 'pg-original-confirm', 'previewHash': preview['previewHash'], 'approved': True}
            actor[0] = 'bob'
            self.assertEqual(client.post(path, json=body, headers={'X-Factory-Expected-Owner': 'alice'}).status_code, 409)
            actor[0] = 'alice'
            self.assertEqual(client.post(path, json={**body, 'approved': False}, headers={'X-Factory-Expected-Owner': 'alice'}).status_code, 403)
            self.assertEqual(client.post(path, json={**body, 'approved': 'true'}, headers={'X-Factory-Expected-Owner': 'alice'}).status_code, 422)
            self.assertEqual(self.service.bindings.history('alice', env['id']), [])
            missing = client.get('/api/factory/application-environments/binding-requests/pg-original-confirm')
            self.assertEqual(missing.status_code, 404); self.assertEqual(len(self.fixture.prepares), 1)
            accepted = client.post(path, json=body, headers={'X-Factory-Expected-Owner': 'alice'})
            self.assertEqual(accepted.status_code, 200, accepted.text)
            actor[0] = 'bob'
            self.assertEqual(client.get('/api/factory/application-environments/binding-requests/pg-original-confirm').status_code, 404)
            self.assertEqual(client.get('/api/factory/application-environments').json(), [])
        self.assertEqual(len(self.service.bindings.history('alice', env['id'])), 1)
        self.assertEqual(self.fixture.research, [])

    def test_stale_preview_revocation_and_tampered_history_or_current_binding_fail_closed(self):
        env, preview = self.stopped()
        self.fixture.model_revision = 'changed-again'
        with self.assertRaises(HTTPException): self.service.bindings.rebind('alice', env['id'], 'pg-stale-preview', preview['previewHash'])
        self.assertEqual(self.service.bindings.history('alice', env['id']), [])
        preview = self.service.bindings.preview('alice', env['id']); self.fixture.revoked = True
        with self.assertRaises(HTTPException): self.service.bindings.rebind('alice', env['id'], 'pg-revoked-confirm', preview['previewHash'])
        self.fixture.revoked = False
        self.service.bindings.rebind('alice', env['id'], 'pg-integrity-confirm', preview['previewHash'])
        with self.service.db.write() as conn:
            history = conn.execute(select(self.service.bindings.changes)).mappings().first()
            conn.execute(self.service.bindings.changes.update().values(new_binding={**history['new_binding'], 'modelRevision': 'corrupt'}))
        with self.assertRaises(HTTPException) as corrupt: self.service.bindings.request('alice', 'pg-integrity-confirm')
        self.assertEqual(corrupt.exception.detail, 'ENVIRONMENT_BINDING_HISTORY_INTEGRITY')
        with self.service.db.write() as conn:
            conn.execute(self.service.bindings.current_table.update().values(body_hash='0' * 64))
        with self.assertRaises(HTTPException) as corrupt: self.service.inspect('alice', env['id'])
        self.assertEqual(corrupt.exception.detail, 'ENVIRONMENT_BINDING_INTEGRITY'); self.assertEqual(self.fixture.research, [])

    def test_unknown_original_remains_results_only_after_rotation_and_package_update_creates_distinct_generation(self):
        self.fixture.failed = True
        original = self.service.prepare('alice', 'fixture-runtime', 'pg-unknown-original')['environment']
        self.assertEqual(self.service.list('alice')[0]['lastOperation'],
            {'requestId': 'pg-unknown-original', 'action': 'prepare', 'state': 'unknown'})
        self.fixture.model_revision = 'rotated-after-unknown'; self.service = self.reopen()
        preview = self.service.bindings.preview('alice', original['id'])
        self.assertEqual(preview['classification'], 'results-only'); self.assertEqual(preview['nextAction'], 'read-original-request')
        self.assertFalse(preview['canRebind']); self.assertEqual(len(self.fixture.prepares), 1)
        self.fixture.package.version = 'new-fixed-fixture'; self.fixture.failed = False
        self.assertEqual(self.service.bindings.preview('alice', original['id'])['nextAction'], 'new-environment')
        created = self.service.prepare('alice', 'fixture-runtime', 'pg-new-generation', new_environment=True)['environment']
        self.assertNotEqual(created['id'], original['id']); self.assertNotEqual(created['projectId'], original['projectId'])
        self.service = self.reopen()
        self.assertEqual(self.service.inspect('alice', original['id'])['projectId'], original['projectId'])
        repeated = self.service.prepare('alice', 'fixture-runtime', 'pg-new-generation', new_environment=True)
        self.assertEqual(repeated['environment']['id'], created['id'])
        self.assertEqual(len(self.fixture.prepares), 2); self.assertEqual(self.fixture.research, [])

    def test_explicit_generation_restore_after_restart_rotation_and_lost_ack_never_selects_default(self):
        default = self.service.prepare('alice', 'fixture-runtime', 'pg-default-before-update')['environment']
        self.fixture.package.version = 'new-fixed-fixture'
        created = self.service.prepare('alice', 'fixture-runtime', 'pg-new-explicit-generation', new_environment=True)['environment']
        with self.service.db.read() as conn: original = deepcopy(self.service._row(conn, 'alice', created['id']))
        self.service.stop('alice', created['id'], 'pg-stop-generation')
        self.fixture.model_revision = 'rotated-generation-model'
        preview = self.service.bindings.preview('alice', created['id'])
        self.service.bindings.rebind('alice', created['id'], 'pg-rebind-generation', preview['previewHash'])
        self.service = self.reopen()
        actor = ['alice']
        app = FastAPI(); app.include_router(environment_router(SimpleNamespace(user=lambda _: {'id': actor[0]}), self.service))
        body = {'requestId': 'pg-restore-generation', 'applicationId': 'fixture-runtime', 'environmentId': created['id']}
        with TestClient(app, base_url="https://testserver") as client:
            path = '/api/factory/application-environments/prepare'
            actor[0] = 'bob'
            self.assertEqual(client.post(path, json=body, headers={'X-Factory-Expected-Owner':'alice'}).status_code, 409)
            self.assertEqual(client.post(path, json=body, headers={'X-Factory-Expected-Owner':'bob'}).status_code, 404)
            actor[0] = 'alice'
            for changed in ({'newEnvironment': True}, {'location': 'other'}, {'applicationId': 'other'}):
                self.assertGreaterEqual(client.post(path, json={**body, **changed}, headers={'X-Factory-Expected-Owner':'alice'}).status_code, 400)
            accepted = client.post(path, json=body, headers={'X-Factory-Expected-Owner':'alice'})
            self.assertEqual(accepted.status_code, 202, accepted.text)
            receipt = accepted.json(); self.assertEqual(receipt['state'], 'ready')
            self.assertEqual(receipt['environment']['id'], created['id'])
            self.assertEqual(receipt['environment']['projectId'], created['projectId'])
            count = len(self.fixture.prepares)
            self.assertEqual(client.get('/api/factory/application-environments/requests/pg-restore-generation').json(), receipt)
            self.assertEqual(client.post(path, json=body, headers={'X-Factory-Expected-Owner':'alice'}).json(), receipt)
            self.assertEqual(len(self.fixture.prepares), count)
        with self.service.db.read() as conn: after = self.service._row(conn, 'alice', created['id'])
        self.assertEqual(after['body'], original['body']); self.assertEqual(after['body_hash'], original['body_hash'])
        self.assertEqual(self.service.inspect('alice', default['id'])['projectId'], default['projectId'])
        self.assertEqual(after['credential_binding']['modelRevision'], 'rotated-generation-model')
        self.assertEqual(self.fixture.research, [])


if __name__ == '__main__': unittest.main()
