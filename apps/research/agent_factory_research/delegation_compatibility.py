"""Research placement and custody on the existing scoped delegation lifecycle."""
from typing import Any

from fastapi import HTTPException

from agent_factory.delegation import DelegationService


class ResearchDelegationService(DelegationService):
    async def create(self, owner: str, parentTaskId: str, goal: str, mode: str,
                     requestId: str, *, placement: dict | None = None,
                     scientific_placement: dict | None = None) -> dict[str, Any]:
        if placement is not None and scientific_placement is not None:
            raise HTTPException(422, 'Only one delegated placement may be specified')
        return await super().create(owner, parentTaskId, goal, mode, requestId,
            placement=scientific_placement if scientific_placement is not None else placement)

    def _creation_request(self, owner: str, parent: dict[str, Any], goal: str,
                          mode: str, placement: dict | None) -> dict[str, Any]:
        plan = self.store.plan(parent['plan_id'], owner)
        receiver_binding = plan.get('remoteHandoff')
        receiver = self.store.handoff_receiver
        if receiver_binding and receiver is not None and receiver.scientific_service is not None:
            receipt = receiver._row(receiver_binding['receiptId'], owner)
            if receipt['body'].get('scientificEnvelope') is not None:
                raise HTTPException(409, 'Receiver scientific phases cannot delegate further')
        request = super()._creation_request(owner, parent, goal, mode, None)
        if placement is not None:
            self.store.handoff_client._science()
            # Keep the original durable request fingerprint and replay identity.
            request['scientificPlacement'] = placement
        return request

    async def _dispatch_placement(self, owner: str, parent: dict[str, Any],
                                  task: dict[str, Any], plan: dict[str, Any],
                                  placement: dict, native_request: str) -> dict[str, Any]:
        client = self.store.handoff_client
        envelope = client._science().prepare_placement(owner, parent, task, plan, placement)
        row = client.reserve(owner, plan['id'], placement['targetRef'], native_request,
            scientific_envelope=envelope)
        if row['state'] == 'RESERVED':
            receipt = await client.prepare(owner, task['id'])
            if receipt.get('state') == 'PREPARED':
                receipt = await client.dispatch(owner, task['id'])
        else:
            # An uncertain acknowledgement only reads the original receipt.
            receipt = await client.receipt(owner, task['id'])
        return receipt

    async def _facts(self, task: dict[str, Any]) -> dict[str, Any]:
        client = getattr(self.store, 'handoff_client', None)
        scientific = getattr(client, 'scientific_service', None)
        if not task.get('run_id') and scientific is not None:
            rows = self.store.sql('SELECT child_id FROM af_remote_scientific_origins WHERE child_id=:id AND owner_id=:owner',
                id=task['id'], owner=task['owner_id'])
            if rows:
                reader = scientific.cleanup_phase if task['cancel_requested'] else scientific.origin_phase
                phase = await reader(task['owner_id'], task['id'])
                raw, stopped = phase['status'], phase['allStopped']
                return {'taskId': task['id'], 'ownerId': task['owner_id'], 'planId': task['plan_id'],
                    'runId': None, 'admission': task['admission'], 'nativeStatus': raw,
                    'snapshot': phase['receipt'], 'effects': self.store.effects(task['id']),
                    'cancelRequested': task['cancel_requested'], 'unknown': raw == 'unknown',
                    'failed': raw in {'failed', 'error'}, 'pending': not stopped, 'stopped': stopped}
        return await super()._facts(task)

    async def _cancel_placement(self, owner: str, task: dict[str, Any]) -> bool:
        client = getattr(self.store, 'handoff_client', None)
        scientific = getattr(client, 'scientific_service', None)
        if scientific is None:
            return False
        rows = self.store.sql('SELECT child_id FROM af_remote_scientific_origins WHERE child_id=:id AND owner_id=:owner',
            id=task['id'], owner=owner)
        if not rows:
            return False
        await scientific.cancel_original(owner, task['id'])
        return True
