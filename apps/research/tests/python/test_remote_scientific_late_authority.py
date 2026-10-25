"""Deterministic late authority boundary; no database or provider execution."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from agent_factory.store import digest
from agent_factory_research.remote_scientific_receiver import RemoteScientificReceiver
from agent_factory_research.services import ResearchServices
import test_remote_scientific_evidence as evidence


class LateAuthorityTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, error):
        receipt = evidence.shell('evaluation')
        lease = evidence.lease('evaluation', released=True)
        task = dict(id=receipt['remoteTaskId'], owner_id=receipt['remoteOwnerId'],
                    plan_id=receipt['remotePlanId'], run_id=receipt['remoteRunId'], cancel_requested=False)
        body = dict(binding={'ownerId': task['owner_id'], 'projectId': 'project',
                            'receiptId': receipt['id'], 'scope': evidence.scope('evaluation')},
                    receiver={'taskId': task['id']}, nativeRunId=task['run_id'], state='COMPLETED',
                    targetFingerprint=lease['targetFingerprint'], config={'targetRef': 'target'},
                    receipt={'execution': evidence.contract()['evaluatorExecution']})
        body['bindingSha256'] = digest(body['binding'])
        retained = {'scope': body['binding']['scope'], 'basis': 'previously-verified-original-claims',
                    'bindingSha256': body['bindingSha256'], 'receiver': body['receiver'],
                    'nativeRunId': body['nativeRunId'], 'claims': {k: deepcopy(v) for k, v in
                    evidence.receipt('evaluation', released=True, result=True)['scientificEvidence'].items()
                    if k in ('launchProof', 'checkpoint', 'evaluation', 'preparation')}}
        rows = []
        store = SimpleNamespace(plan=Mock(return_value={'fingerprint': lease['planFingerprint']}),
            sql=Mock(side_effect=lambda *a, **kw: deepcopy(rows)),
            handoff_receiver=SimpleNamespace(authorize=Mock(side_effect=[None, error])))
        research = ResearchServices(store, installed=True)
        self.addCleanup(research.release)
        provider = Mock(); provider.read_launch_proof.return_value = evidence.launch('evaluation')
        resources = Mock(); resources._provider.return_value = provider
        research.research_runtime = SimpleNamespace(resources=resources, submit=AsyncMock())
        verifier = AsyncMock()
        assembler = Mock(); assembler.evaluation_service.return_value.verify = verifier
        checkpoint = evidence.contract()['training']['checkpoint']
        checkpoints = Mock(); checkpoints.identity.return_value = ({'id': checkpoint['artifactId']},
            {k: v for k, v in checkpoint.items() if k != 'artifactId'})
        project = SimpleNamespace(assembler=assembler, checkpoints=checkpoints, manifest=evidence.contract()['comparisonManifest'])
        service = object.__new__(RemoteScientificReceiver)
        service.store, service.projects = store, {'project': project}
        service.research = research
        service._context = Mock(return_value=SimpleNamespace(run_context=object()))
        service._bound = Mock(side_effect=lambda *a, **kw: (deepcopy(body), deepcopy(task), project))
        service._read = Mock(side_effect=lambda *a: deepcopy(body))
        service._prior = Mock(return_value={'training': {'receipt': {
            'execution': {k: v for k, v in evidence.contract()['training'].items() if k not in ('checkpoint', 'variantSha256')},
            'artifact': {'id': checkpoint['artifactId']}}}})
        service.inspect_phase = AsyncMock(side_effect=lambda *a, **kw: {'lease': deepcopy(lease)})
        def retain():
            rows[:] = [{'owner_id': task['owner_id'], 'scope_hash': digest(retained['scope']),
                       'fingerprint': digest(retained), 'body': deepcopy(retained)}]
        return SimpleNamespace(service=service, store=store, research=research, receipt=receipt, body=body, lease=lease,
            retained=retained, rows=rows, retain=retain, verifier=verifier)

    async def exercise(self, error, mutation=None):
        f = self.fixture(error)
        entered, release = asyncio.Event(), asyncio.Event()
        async def verify(*args):
            entered.set()
            await release.wait()
            raise error
        f.verifier.side_effect = verify
        pending = asyncio.create_task(f.service.project_evidence(f.receipt))
        await asyncio.wait_for(entered.wait(), 2)
        f.retain()  # Concurrent original observation verified and persisted claims.
        if mutation:
            mutation(f)
        release.set()
        return f, pending

    async def test_inprocess_and_transport_denial_use_only_retained_claims(self):
        for status, detail in ((409, 'REMOTE_SCIENTIFIC_ORIGIN_DENIED'),
                (403, 'ORIGIN_AUTHORITY_DENIED: origin did not return current verified authority')):
            with self.subTest(status=status):
                f, pending = await self.exercise(HTTPException(status, detail))
                saved = deepcopy(f.rows)
                result = await pending
                self.assertEqual(result['evaluation'], f.retained['claims']['evaluation'])
                self.assertEqual(result['lease'], f.lease)
                self.assertTrue(f.receipt['scientificClaimsRetained'])
                self.assertEqual(f.rows, saved)
                f.verifier.assert_awaited_once()
                f.service.inspect_phase.assert_awaited_with(f.receipt['remoteOwnerId'], f.receipt['remoteTaskId'], persist=False)
                self.assertTrue(all(c.args[0].startswith('SELECT') for c in f.store.sql.call_args_list))
                f.research.research_runtime.submit.assert_not_awaited()

    async def test_missing_claim_identity_drift_or_current_grant_preserves_original_error(self):
        def incomplete(f):
            f.rows[0]['body']['claims']['evaluation'] = None
            f.rows[0]['fingerprint'] = digest(f.rows[0]['body'])
        mutations = (lambda f: f.rows.clear(),
                     lambda f: f.body.update(nativeRunId='replacement'),
                     lambda f: setattr(f.store.handoff_receiver.authorize, 'side_effect', None),
                     lambda f: f.lease.update(providerJobId='replacement'),
                     incomplete,
                     lambda f: f.rows[0]['body']['claims'].update(evaluation=None),
                     lambda f: f.lease.update(state='UNKNOWN', capacityHeld=True))
        for mutate in mutations:
            error = HTTPException(409, 'REMOTE_SCIENTIFIC_ORIGIN_DENIED')
            f, pending = await self.exercise(error, mutate)
            with self.assertRaises(HTTPException) as caught:
                await pending
            self.assertIs(caught.exception, error)
            self.assertNotIn('scientificClaimsRetained', f.receipt)

    async def test_unrelated_evaluator_errors_do_not_use_retained_claims(self):
        for error in (HTTPException(409, 'EVALUATION_CHANGED'), HTTPException(403, 'revoked'),
                      PermissionError('evaluator revoked'), ValueError('corrupt evaluator')):
            f, pending = await self.exercise(error)
            with self.assertRaises(type(error)) as caught:
                await pending
            self.assertIs(caught.exception, error)
            self.assertNotIn('scientificClaimsRetained', f.receipt)
