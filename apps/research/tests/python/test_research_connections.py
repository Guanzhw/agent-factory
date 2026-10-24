"""Offline connection custody; native tickets and launch records are synthetic."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine, inspect

from agent_factory.connections import ConnectionService, TrustedConnectionBinding
from agent_factory.store import digest
from agent_factory_research.connections_compatibility import ResearchConnectionService


class ResearchConnectionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        Table('af_audit', metadata, Column('id', Integer, primary_key=True), Column('actor_id', String),
              Column('action', String), Column('target_id', String), Column('body', JSON), Column('created_at', String))
        metadata.create_all(self.engine)
        self.at = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.handle = SimpleNamespace(create_experiment_adapter=Mock())
        self.adapter = 'openresearch-experiment-v1'
        self.registry = {'original': TrustedConnectionBinding('alice', 'orx', self.adapter,
            frozenset({'compute:local'}), 'fixture-v1', expires_at=self.at + timedelta(minutes=1),
            available=True, opaque_handle=self.handle, handle_ref='synthetic-original')}
        self.ticket = {'id': 'run', 'session_id': 'task', 'user_id': 'alice',
                       'component_id': 'factory-executor', 'component_type': 'agent'}
        self.task = {'id': 'task', 'owner_id': 'alice', 'plan_id': 'plan', 'run_id': 'run'}
        self.auth = SimpleNamespace(require_member=Mock())
        self.store = SimpleNamespace(engine=self.engine, task=Mock(return_value=self.task),
            native_db=SimpleNamespace(get_job=Mock(return_value=self.ticket)), sql=Mock())
        self.service = ResearchConnectionService(self.store, self.auth, self.registry, clock=lambda: self.at)
        bound = self.service.bind('alice', 'original', 'bind-original')
        self.pin = {key: bound[key] for key in ('ref', 'version', 'fingerprint', 'revision', 'capabilities', 'taskId')}
        request = {'ownerId': 'alice', 'taskId': 'task', 'planId': 'plan', 'nativeRunId': 'run', 'connection': self.pin}
        binding = {**request, 'projectId': 'synthetic-project', 'experimentId': 'synthetic-experiment'}
        self.binding = {'binding': binding, 'binding_hash': digest(binding), 'plan_id': 'plan', 'run_id': 'run'}
        self.effect = {'effect_key': 'run:orx-experiment-launch-v1', 'fingerprint': digest(request)}
        self.store.sql.side_effect = lambda statement, **params: (
            [self.binding] if 'af_orx_task_experiments' in statement else [self.effect])

    def cleanup(self, *, owner='alice', pin=None):
        return self.service.cleanup_handle(owner, self.pin if pin is None else pin,
            adapter_ref=self.adapter, task_id='task')

    def test_expired_and_revoked_handles_allow_only_original_cleanup(self):
        self.assertIs(self.service.resolve('alice', self.pin['ref'], 'orx'), self.handle)
        self.at += timedelta(minutes=2)
        with self.assertRaisesRegex(HTTPException, 'CONNECTION_EXPIRED'):
            self.service.resolve('alice', self.pin['ref'], 'orx')
        self.assertIs(self.cleanup(), self.handle)
        self.assertEqual(self.service.inspect('alice', self.pin['ref'])['status'], 'expired')
        self.service.revoke('alice', self.pin['ref'], 'revoke-original')
        self.assertIs(self.cleanup(), self.handle)
        self.assertEqual(self.service.inspect('alice', self.pin['ref'])['status'], 'revoked')
        with self.assertRaisesRegex(HTTPException, 'CONNECTION_REVOKED'):
            self.service.resolve('alice', self.pin['ref'], 'orx')
        self.auth.require_member.side_effect = HTTPException(403, 'synthetic member disabled')
        self.assertIs(self.cleanup(), self.handle)
        with self.assertRaisesRegex(HTTPException, 'synthetic member disabled'):
            self.service.resolve('alice', self.pin['ref'], 'orx')
        self.handle.create_experiment_adapter.assert_not_called()

    def test_foreign_owner_or_changed_native_identity_cannot_reclaim(self):
        with self.assertRaisesRegex(HTTPException, 'exact native task identity'):
            self.cleanup(owner='bob')
        self.store.task.assert_called_with('task', 'bob')
        for field in ('id', 'session_id', 'user_id', 'component_id', 'component_type'):
            with self.subTest(field=field):
                self.store.native_db.get_job.return_value = {**self.ticket, field: 'substituted'}
                with self.assertRaisesRegex(HTTPException, 'exact native task identity'):
                    self.cleanup()
        self.store.sql.assert_not_called()

    def test_changed_binding_or_launch_effect_cannot_reclaim(self):
        self.binding['binding_hash'] = '0' * 64
        with self.assertRaisesRegex(HTTPException, 'original experiment identity changed'):
            self.cleanup()
        self.binding['binding_hash'] = digest(self.binding['binding'])
        self.effect['fingerprint'] = '0' * 64
        with self.assertRaisesRegex(HTTPException, 'durable launch intent'):
            self.cleanup()

    def test_changed_requested_pin_or_replaced_opaque_handle_cannot_reclaim(self):
        with self.assertRaisesRegex(HTTPException, 'requested handle differs'):
            self.cleanup(pin={**self.pin, 'fingerprint': '0' * 64})
        self.registry['original'] = replace(self.registry['original'],
            opaque_handle=SimpleNamespace(create_experiment_adapter=Mock()))
        with self.assertRaisesRegex(HTTPException, 'CONNECTION_CHANGED'):
            self.cleanup()

    def test_core_connections_need_no_research_tables_or_reclaim_api(self):
        # Use the real generic registry against a database without app tables.
        core = ConnectionService(self.store, self.auth, self.registry, clock=lambda: self.at)
        self.store.sql.side_effect = AssertionError('Generic connections must not query research records')
        self.assertIs(core.resolve('alice', self.pin['ref'], 'orx'), self.handle)
        core.revoke('alice', self.pin['ref'], 'core-revoke')
        with self.assertRaisesRegex(HTTPException, 'CONNECTION_REVOKED'):
            core.resolve('alice', self.pin['ref'], 'orx')
        self.assertFalse(hasattr(core, 'cleanup_handle'))
        self.assertFalse(any(name.startswith('af_orx') for name in inspect(self.engine).get_table_names()))
        self.store.sql.assert_not_called()


if __name__ == '__main__':
    unittest.main()
