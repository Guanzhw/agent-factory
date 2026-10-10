"""Controlled custody tests; no runtime, paid model or external service."""
from contextlib import contextmanager
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine

from agent_factory.application_environments import ApplicationEnvironments, PrepareEnvironment


@unittest.skipUnless(sys.platform == 'linux', 'Installed platform package requires Linux custody fences')
class ApplicationEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.engine = create_engine('sqlite:///' + self.folder.name + '/custody.db')
        self.addCleanup(self.engine.dispose)
        self.revoked = False
        self.model_revision = 'fixture-model-revision'
        self.allocations, self.prepares, self.research, self.remotes = [], [], [], {}
        self.failed = False
        @contextmanager
        def read(): yield None
        def check():
            if self.revoked: raise HTTPException(403, 'OWNER_REVOKED')
        handle = SimpleNamespace(check=check)
        models = SimpleNamespace(db=SimpleNamespace(read=read),
            default=lambda owner: {'reference': 'fixture-model-' + owner, 'revision': self.model_revision},
            binding=lambda conn, owner, reference: SimpleNamespace(revision=self.model_revision, opaque_handle=handle))
        auth = SimpleNamespace(require=lambda owner, permission: check())
        def prepare(body, model):
            self.prepares.append(body['id']); model.check()
            if body['id'] not in self.allocations: self.allocations.append(body['id'])
            if self.failed: raise TimeoutError('synthetic-private-diagnostic')
        def configure(owner, provider, config, request, reference=None):
            ref = reference or 'remote-' + owner
            self.remotes[ref] = owner
            return {'registrationRef': ref}
        connections = SimpleNamespace(_key=lambda value: None,
            personal=SimpleNamespace(configure=configure, verify=lambda *_: None),
            bind=lambda owner, reference, request: {'ref': 'binding-' + owner, 'available': True},
            inspect=lambda owner, ref: {'ref': ref, 'available': True})
        package = SimpleNamespace(version='fixture-package-1', provider_id='fixture-provider', prepare=prepare,
            check=lambda body: body['id'] in self.allocations,
            connection_configuration=lambda body: {'projectId': body['projectId']},
            stop=lambda body: self.allocations.remove(body['id']) is None, close=lambda: None)
        self.package = package
        self.service = ApplicationEnvironments(SimpleNamespace(engine=self.engine,
            settings=SimpleNamespace(workspace=Path(self.folder.name))), auth, models, connections,
            {'openresearch': package})

    def test_prepare_reuse_replay_and_owner_scope_never_submits_work(self):
        first = self.service.prepare('alice', 'openresearch', 'request-first')
        self.assertEqual(first['state'], 'ready')
        identifier, project = first['environment']['id'], first['environment']['projectId']
        self.assertFalse(first['environment']['researchSubmitted'])
        self.assertEqual(self.service.prepare('alice', 'openresearch', 'request-first'), first)
        self.assertEqual(len(self.prepares), 1)
        again = self.service.prepare('alice', 'openresearch', 'request-explicit-reuse')
        self.assertEqual(again['environment']['id'], identifier)
        self.assertEqual(again['environment']['projectId'], project)
        self.assertEqual(len(self.allocations), 1)
        for method, args in ((self.service.inspect, ('bob', identifier)),
                (self.service.request, ('bob', 'request-first')),
                (self.service.stop, ('bob', identifier, 'foreign-stop'))):
            with self.assertRaises(HTTPException) as rejected: method(*args)
            self.assertEqual(rejected.exception.status_code, 404)
        self.assertEqual(self.research, [])
        with self.assertRaises(ValidationError):
            PrepareEnvironment(requestId='prepare-goal', goal='Do not dispatch from prepare')

    def test_unknown_recovery_requires_new_explicit_prepare_preserves_project(self):
        self.failed = True
        first = self.service.prepare('alice', 'openresearch', 'request-unknown')
        self.assertEqual(first['state'], 'unknown')
        self.assertNotIn('synthetic-private-diagnostic', str(first))
        recovered = self.service.request('alice', 'request-unknown')
        self.assertEqual(recovered, first)
        self.service.prepare('alice', 'openresearch', 'request-unknown')
        self.assertEqual(len(self.prepares), 1)
        self.failed = False
        ready = self.service.prepare('alice', 'openresearch', 'request-recovery')
        self.assertEqual(ready['state'], 'ready')
        self.assertEqual(ready['environment']['projectId'], first['environment']['projectId'])
        self.assertEqual(len(self.allocations), 1)
        self.assertEqual(self.research, [])

    def test_stop_restart_preserves_identity_and_refuses_implicit_update_or_model_change(self):
        first = self.service.prepare('alice', 'openresearch', 'request-first')
        env = first['environment']
        stopped = self.service.stop('alice', env['id'], 'request-stop')
        self.assertEqual(stopped['state'], 'stopped')
        ready = self.service.prepare('alice', 'openresearch', 'request-restart')
        self.assertEqual(ready['environment']['projectId'], env['projectId'])
        self.model_revision = 'fixture-rotated'
        with self.assertRaises(HTTPException) as changed:
            self.service.prepare('alice', 'openresearch', 'request-rotate')
        self.assertTrue(str(changed.exception.detail).startswith('ENVIRONMENT_MODEL_CHANGED'))
        self.model_revision = 'fixture-model-revision'; self.package.version = 'fixture-package-2'
        with self.assertRaises(HTTPException) as update:
            self.service.prepare('alice', 'openresearch', 'request-update')
        self.assertEqual(update.exception.detail, 'ENVIRONMENT_UPDATE_REQUIRES_MIGRATION')
        self.revoked = True
        with self.assertRaises(HTTPException): self.service.prepare('alice', 'openresearch', 'request-revoked')
