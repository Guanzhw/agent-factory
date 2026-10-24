"""Portable actual binding-proof metadata checks, not PostgreSQL lock evidence."""
import copy
from dataclasses import replace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import event

from agent_factory.remote_bindings import RemoteBindingService
from agent_factory.remote_handoff import TrustedOrigin
from agent_factory.store import digest
from test_remote_v2_manifest import V2ManifestFixture, rehash


class RemoteV2BindingTests(V2ManifestFixture):
    def setUp(self):
        super().setUp()
        # Only PG advisory-lock functions are inert on this owned SQLite DB.
        # Proof rows, uniqueness constraints and source comparisons are real.
        def functions(conn, *_):
            conn.create_function('hashtext', 1, lambda _: 0)
            conn.create_function('pg_advisory_xact_lock', 1, lambda _: 0)
        event.listen(self.store.engine, 'checkout', functions)
        self.addCleanup(event.remove, self.store.engine, 'checkout', functions)
        self.service = RemoteBindingService(self.store, self.auth, self.bindings, None)
        self.store.remote_bindings = self.service
        self.plan = self.make_plan()
        self.origin = TrustedOrigin('source', {'alice': 'alice'}, lambda *args: None,
            supported_application_contracts=(1, 2),
            v2_budget={key: value for key, value in self.plan['budget'].items() if key != 'depth'})
        self.task, self.receipt, self.receiver_plan = (str(uuid4()) for _ in range(3))
        self.configuration = {'revision': '1', 'sha256': 'a' * 64}

    def prepare(self, *, envelope=None, origin=None):
        return self.service.prepare(origin or self.origin, 'alice', self.task, self.receipt,
            envelope or self.envelope(self.plan), receiver_plan_id=self.receiver_plan,
            source_configuration=self.configuration)

    def imported(self, proof):
        return rehash({**copy.deepcopy(self.plan), 'id': self.receiver_plan, 'createdAt': 'receiver-time',
            'remoteHandoff': {'receiptId': self.receipt, 'originRef': self.origin.reference,
                'originTaskId': self.task, 'manifestHash': digest(self.plan), 'bindingProofSha256': proof['sha256']}})

    def test_prepare_replay_and_effective_binding_preserve_exact_source(self):
        proof = self.prepare()
        self.assertEqual(self.prepare(), proof)
        self.assertEqual(proof['manifestHash'], digest(self.plan))
        self.assertEqual(proof['sourcePlan'], self.plan)
        root = self.imported(proof)
        with self.service._read() as conn:
            saved = self.service._proof(conn, root)
        self.assertEqual(saved['sourcePlan']['inputValues'], {'format': 'hex'})
        self.assertEqual(saved['sourcePlan']['config']['applicationConfig'], {'format': 'hex'})
        self.assertEqual(self.service.effective(root, root['executionBindings']), root['executionBindings'])
        with self.assertRaisesRegex(HTTPException, 'delegation is unsupported'):
            self.service.build_inherited(root['materials'], 'alice', root)

    def test_imported_plan_cannot_rewrite_version_inputs_config_or_budget(self):
        proof = self.prepare()
        original = self.imported(proof)
        edits = [lambda p: p.pop('contractVersion'), lambda p: p.update(contractVersion=1),
                 lambda p: p['inputValues'].update(format='other'),
                 lambda p: p['inputSchema']['properties']['format'].update(enum=['other']),
                 lambda p: p['config']['applicationConfig'].update(format='other'),
                 lambda p: p['budget'].update(operationSeconds=600)]
        for edit in edits:
            root = copy.deepcopy(original)
            edit(root)
            rehash(root)
            with self.subTest(edit=edit), self.service._read() as conn, self.assertRaisesRegex(HTTPException, 'REMOTE_BINDING_SOURCE'):
                self.service._proof(conn, root)

    def test_binding_prepare_rejects_optout_and_definition_substitution(self):
        legacy = replace(self.origin, supported_application_contracts=(1,), v2_budget=None)
        with self.assertRaises(HTTPException): self.prepare(origin=legacy)
        envelope = self.envelope(self.plan)
        envelope['applicationDefinition']['modes']['execute']['config']['format'] = 'other'
        with self.assertRaises(HTTPException): self.prepare(envelope=envelope)
        envelope = self.envelope(self.plan)
        envelope['wireVersion'] = True
        with self.assertRaises(HTTPException): self.prepare(envelope=envelope)
        self.assertEqual(self.service.inspect(self.prepare()['receiptId'], 'alice')['manifestHash'], digest(self.plan))
