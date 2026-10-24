"""Static research assembly over the existing Factory handoff protocol.

Research owns its phase journal, scientific evidence and legacy HTTP additions.
The public handoff services retain native dispatch, immutable source proofs,
identity checks, budgets, cancellation and custody. These classes add no queue or
discovery mechanism; deployment explicitly selects them and binds one service.
"""
from urllib.parse import quote

from fastapi import HTTPException, Request
from sqlalchemy import text

from agent_factory.remote_handoff import PreparedHandoffService, TrustedHandoffClient
from agent_factory.store import digest

from .remote_scientific_evidence import (
    project_scientific_evidence,
    scientific_native_stopped,
    scientific_stopped,
    validate_scientific_evidence,
)
from .remote_scientific_origin import validate_source


class ResearchPreparedHandoffService(PreparedHandoffService):
    def __init__(self, store, auth, bridge, origins, *, admission_guard=None, scientific_service=None):
        self.scientific_service = scientific_service
        super().__init__(store, auth, bridge, origins, admission_guard=admission_guard)

    def _science(self):
        if self.scientific_service is None:
            raise HTTPException(409, 'Scientific placement service is unavailable')
        return self.scientific_service

    def _validate_placement(self, plan, envelope):
        self._science()
        validate_source(plan, envelope)

    def _prepare_placement(self, identifier, source, envelope, remote_owner):
        self._science().prepare_binding(identifier, source, envelope, remote_owner)

    def _bind_placement(self, row, task):
        if row['body'].get('scientificEnvelope') is not None:
            self._science().bind_task(row['id'], task)

    def _placement_evidence(self, row, result):
        envelope = row['body'].get('scientificEnvelope')
        if envelope is None:
            return {}
        self._science()
        return {'scientificEvidence': project_scientific_evidence(result, scope=envelope['scope'])}

    async def _refresh_placement_evidence(self, row, task, result, *, reconcile=False):
        if row['body'].get('scientificEnvelope') is None:
            return
        service = self._science()
        if reconcile:
            service.bind_task(row['id'], task)
        result['scientificEvidence'] = await service.project_evidence(result, persist=reconcile)
        no_dispatch = service.no_dispatch_proof(result)
        if no_dispatch is not None:
            result['scientificNoDispatch'] = no_dispatch

    def _placement_stopped(self, row, task, result, raw):
        envelope = row['body'].get('scientificEnvelope')
        if envelope is None:
            return True
        service = self._science()
        scope = envelope['scope']
        if row['state'] != 'CANCELLED_NO_DISPATCH' and not scientific_native_stopped(result):
            return False
        if raw == 'completed' and not task['cancel_requested']:
            if service._read(row['id'])['state'] != 'COMPLETED':
                return False
            # Keep original observation authority until successful phase claims
            # are verified. Physical stop alone can precede an artifact fence;
            # closing the origin then would strand the missing result forever.
            evidence = validate_scientific_evidence(result, expected_scope=scope)
            claim = {'preparation': 'preparation', 'training': 'checkpoint',
                     'evaluation': 'evaluation'}[scope['phase']]
            if evidence[claim] is None:
                return False
        if scope['phase'] != 'preparation' and row['state'] != 'CANCELLED_NO_DISPATCH':
            return scientific_stopped(result, expected_scope=scope)
        return True

    def _cancel_placement(self, row, task):
        if row['body'].get('scientificEnvelope') is not None and task.get('run_id'):
            self._science().cancel_before_dispatch(row['remote_owner'], task['id'])

    def validate_delegated_root(self, conn, root, source_plan):
        """Research phase proof for RemoteBindingService's delegated import seam."""
        self._science()
        handoff = root['remoteHandoff']
        phase = conn.execute(text('SELECT body FROM af_remote_scientific_phases WHERE receipt_id=:id AND owner_id=:owner'),
            {'id': handoff['receiptId'], 'owner': root['ownerId']}).mappings().first()
        body = phase['body'] if phase else None
        if (body is None or digest(body['binding']) != body['bindingSha256']
                or body['binding']['receiptId'] != handoff['receiptId']
                or body['binding']['ownerId'] != root['ownerId']):
            raise HTTPException(409, 'Scientific receiver binding is unavailable')
        envelope = {'schema': 1, 'projectId': body['binding']['projectId'],
            'scope': body['binding']['scope'], 'candidate': body['candidate']}
        validate_source(source_plan, envelope)

    def _routes(self):
        def owner(request, execution=False):
            user = self.auth.user(request)
            self.auth.require_member(user['id'])
            return user['id']

        @self.router.get('/scientific-projects/{project_id}/baseline')
        async def scientific_baseline(project_id: str, request: Request, projectPin: str):
            if self.scientific_service is None:
                raise HTTPException(404, 'Scientific project is unavailable')
            return await self.scientific_service.project_baseline(owner(request), project_id, projectPin)

        @self.router.post('/{identifier}/scientific-drive')
        async def scientific_drive(identifier: str, request: Request):
            identity = owner(request, True)
            row = self._row(identifier, identity)
            self._check_row(row, identity)
            if row['body'].get('scientificEnvelope') is None:
                raise HTTPException(409, 'Scientific placement is unavailable')
            await self._science().start_drive(identity, self._task(row)['id'])
            return await self.reconcile(identity, identifier)

        super()._routes()


class ResearchHandoffClient(TrustedHandoffClient):
    def __init__(self, store, auth, targets, *, admission_guard=None, scientific_service=None):
        self.scientific_service = scientific_service
        super().__init__(store, auth, targets, admission_guard=admission_guard)

    def _science(self):
        if self.scientific_service is None:
            raise HTTPException(409, 'Scientific placement service is unavailable')
        return self.scientific_service

    def consume_scientific_tool(self, body):
        if self.scientific_service is None:
            raise HTTPException(503, 'ORIGIN_SCIENTIFIC_UNAVAILABLE: scientific debit service is unavailable')
        return self.scientific_service.consume_remote_tool(body)

    def authorize_scientific_custody(self, body):
        if self.scientific_service is None:
            raise HTTPException(503, 'ORIGIN_SCIENTIFIC_UNAVAILABLE: custody service unavailable')
        return self.scientific_service.authorize_completed_custody(body)

    def _validate_placement(self, plan, envelope):
        service = self._science()
        validate_source(plan, envelope)
        service.validate_source(plan, envelope)

    def _placement_admission(self, owner, plan, envelope, *, task_id=None):
        if envelope is None:
            return super()._placement_admission(owner, plan, envelope, task_id=task_id)
        service = self._science()
        if task_id is not None:
            service.assert_authority(owner, task_id)
        child_id = task_id if task_id is not None else envelope['scope']['originChildTaskId']
        self.store.require_plan_execution(owner, plan, scientific_child_id=child_id)
        return child_id

    def _validate_placement_receipt(self, row, receipt, previous):
        envelope = row['body'].get('scientificEnvelope')
        if envelope is None:
            return super()._validate_placement_receipt(row, receipt, previous)
        service = self._science()
        if ('scientificClaimsRetained' in receipt
                and type(receipt['scientificClaimsRetained']) is not bool):
            raise HTTPException(409, 'Scientific retained-claim annotation must be boolean')
        scientific = validate_scientific_evidence(dict(receipt), expected_scope=envelope['scope'], previous=previous)
        if receipt.get('state') == 'CANCELLED_NO_DISPATCH' and any(scientific[key] is not None
                for key in ('lease', 'launchProof', 'checkpoint', 'evaluation', 'preparation')):
            raise HTTPException(409, 'Pre-admission cancellation cannot replace scientific custody')
        service.validate_received_native(row['owner_id'], row['task_id'], receipt)
        if receipt.get('allStopped') is True and receipt.get('state') != 'CANCELLED_NO_DISPATCH':
            if not scientific_native_stopped(dict(receipt)):
                raise HTTPException(409, 'Scientific stop requires original native terminal evidence')
            if envelope['scope']['phase'] != 'preparation' and not scientific_stopped(dict(receipt), expected_scope=envelope['scope']):
                raise HTTPException(409, 'Scientific stop requires process and GPU release evidence')

    def _scientific_cleanup_target(self, owner, task_id, expected_scope):
        # Internal original-custody cleanup only. Never used by public read/run routes.
        row = self._row(owner, task_id)
        envelope = row['body'].get('scientificEnvelope')
        task = self.store.task(task_id, owner)
        plan = self.store.plan(task['plan_id'], owner)
        service = self._science()
        if (envelope is None or envelope['scope'] != expected_scope
                or not task['cancel_requested'] or task.get('run_id') or digest(plan) != row['manifest_hash']):
            raise HTTPException(409, 'Original scientific cleanup binding is unavailable')
        service.validate_source(plan, envelope)
        target = self.targets.get(row['target_ref'])
        if target is None or owner not in target.identity_map or target.fingerprint != row['configuration_hash']:
            raise HTTPException(409, 'Original scientific cleanup target changed')
        return row, target

    async def scientific_cleanup_receipt(self, owner, task_id, *, expected_scope, reconcile=False):
        row, target = self._scientific_cleanup_target(owner, task_id, expected_scope)
        previous = row['body'].get('receipt')
        if previous:
            receipt = await self._request(owner, target, 'GET', '/api/factory/remote-handoffs/' + quote(previous['id'], safe=''))
        else:
            receipt = await self._request(owner, target, 'GET', '/api/factory/remote-handoffs/receipts/by-request',
                params={'originRef': target.origin_ref, 'originOwnerId': owner, 'requestId': row['request_id']})
        if reconcile:
            # Validate the lookup against the original scope before allowing a
            # write at the returned identifier, not merely after that write.
            receipt = self._save_receipt(row, target, receipt, persist=False)
            receipt = await self._request(owner, target, 'POST',
                '/api/factory/remote-handoffs/' + quote(receipt['id'], safe='') + '/reconcile')
        return self._save_receipt(self._row(owner, task_id), target, receipt, persist=reconcile)

    async def cancel_scientific_original(self, owner, task_id, *, expected_scope):
        row = self._row(owner, task_id)
        envelope = row['body'].get('scientificEnvelope')
        if envelope is None or envelope['scope'] != expected_scope:
            raise HTTPException(409, 'Original scientific cleanup scope changed')
        self._science().validate_source(self.store.plan(self.store.task(task_id, owner)['plan_id'], owner), envelope)
        self.store.request_cancel(task_id)
        row, target = self._scientific_cleanup_target(owner, task_id, expected_scope)
        receipt = row['body'].get('receipt') or await self.scientific_cleanup_receipt(owner, task_id, expected_scope=expected_scope)
        result = await self._request(owner, target, 'POST', '/api/factory/remote-handoffs/' + quote(receipt['id'], safe='') + '/cancel')
        if not isinstance(result, dict) or not isinstance(result.get('receipt'), dict):
            raise HTTPException(502, 'Remote scientific cancellation has no original receipt')
        self._save_receipt(self._row(owner, task_id), target, result['receipt'])
        return result
