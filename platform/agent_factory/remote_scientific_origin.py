"""Origin-only scientific scope journal over existing delegation and handoff.

No new queue, native ticket, provider launch or authority grant is created here.
The operator derives variant identity; the native parent remains the mandate.
"""
from copy import deepcopy
import inspect
import re
import time
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import text

from .autoresearch_profile import APPLICATION_ID
from .remote_authority import AuthorityScientificCall, AuthorityScientificCustody
from .remote_scientific_evidence import validate_scientific_evidence, validate_scientific_scope, scientific_stopped
from .remote_scientific_profile import TOOLS, CAPABILITIES
from .research_assessment import assess_observations
from .research_manifest import validate_manifest, manifest_fingerprint
from .store import canonical, digest, now

ERROR = 'REMOTE_SCIENTIFIC_ORIGIN_DENIED'
_PLACEMENT = {'targetRef', 'projectId', 'projectPin', 'phase', 'candidate', 'prior', 'scopeBinding'}


def require(value):
    if not value:
        raise HTTPException(409, ERROR)


def validate_source(plan: Any, envelope: Any):
    """Pure shape/binding validation only, never proof of origin authority."""
    require(type(plan) is dict)
    require(type(envelope) is dict and set(envelope) == {'schema', 'projectId', 'scope', 'candidate'}
            and type(envelope['schema']) is int and envelope['schema'] == 1
            and type(envelope['projectId']) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', envelope['projectId'])
            and type(envelope['candidate']) is dict
            and len(canonical(envelope).encode()) <= 1024 * 1024)
    plan = cast(dict[str, Any], plan)
    scope = validate_scientific_scope(envelope['scope'])
    phase = scope['phase']
    require(digest(plan) == scope['sourceManifestSha256']
            and digest(envelope['candidate']) == scope['candidateSha256']
            and plan.get('application') == APPLICATION_ID
            and (plan.get('applicationRef') or {}).get('id') == APPLICATION_ID
            and plan.get('mode') == 'remote-scientific-' + phase
            and plan.get('tools') == [TOOLS[phase]] and plan.get('capabilities') == [CAPABILITIES[phase]]
            and plan.get('delegation') == {'parentTaskId': scope['originParentTaskId'],
                'rootTaskId': scope['originParentTaskId'], 'depth': 1}
            and type(plan['delegation']['depth']) is int and not plan.get('remoteHandoff'))
    return deepcopy(envelope)


class RemoteScientificOrigin:
    def __init__(self, store, auth, *, handoff_client, project_validator, project_bindings=None):
        require(callable(project_validator))
        self.store, self.auth = store, auth
        self.handoff, self.project_validator = handoff_client, project_validator
        self.project_bindings: dict[str, Any] = deepcopy(project_bindings or {})
        require(type(self.project_bindings) is dict and len(self.project_bindings) <= 100)
        for project, pin in self.project_bindings.items():
            require(type(project) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}', project)
                    and type(pin) is dict and set(pin) == {'targetRef', 'projectPin', 'manifest', 'ownerId'}
                    and type(pin['projectPin']) is str and re.fullmatch('[a-f0-9]{64}', pin['projectPin']))
            validate_manifest(cast(dict[str, Any], pin)['manifest'])
        store.sql('''CREATE TABLE IF NOT EXISTS af_remote_scientific_origins (
            child_id TEXT PRIMARY KEY REFERENCES af_tasks(id), owner_id TEXT NOT NULL,
            parent_id TEXT NOT NULL REFERENCES af_tasks(id), fingerprint TEXT NOT NULL,
            body JSONB NOT NULL, receipt JSONB)''')
        store.sql('''CREATE TABLE IF NOT EXISTS af_remote_scientific_calls (
            child_id TEXT NOT NULL REFERENCES af_tasks(id), call_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, body JSONB NOT NULL,
            PRIMARY KEY(child_id,call_id))''')
        store.sql('''CREATE TABLE IF NOT EXISTS af_remote_scientific_receiver_runs (
            child_id TEXT PRIMARY KEY REFERENCES af_tasks(id), receiver_task_id TEXT NOT NULL,
            native_run_id TEXT NOT NULL)''')

        store.sql('''CREATE TABLE IF NOT EXISTS af_remote_scientific_drive_intents (
            child_id TEXT PRIMARY KEY REFERENCES af_tasks(id), scope_sha256 TEXT NOT NULL,
            receiver_id TEXT NOT NULL, requested_at TEXT NOT NULL)''')

    def _row(self, owner, child_id):
        rows = self.store.sql('SELECT * FROM af_remote_scientific_origins WHERE child_id=:child AND owner_id=:owner',
                              child=child_id, owner=owner)
        if len(rows) != 1:
            raise HTTPException(404, 'REMOTE_SCIENTIFIC_ORIGIN_NOT_FOUND')
        row = rows[0]
        require(digest(row['body']) == row['fingerprint'])
        body = row['body']
        scope = validate_scientific_scope(body['envelope']['scope'])
        require(scope['originChildTaskId'] == row['child_id'] and scope['originParentTaskId'] == row['parent_id']
                and body['ownerId'] == row['owner_id'])
        return row

    def _parent_current(self, owner, parent, placement):
        self.auth.require(owner, 'run')
        self.store.require_current_policy()
        actual = self.store.task(parent['id'], owner)
        require(all(actual.get(key) == parent.get(key) for key in ('id', 'owner_id', 'plan_id', 'request_id', 'fingerprint', 'run_id'))
                and actual['owner_id'] == owner and actual.get('run_id')
                and not actual['cancel_requested'] and not actual['terminal'])
        ticket = self.store.lifecycle_observer._binding(actual)
        require(ticket and ticket['status'] == ticket['persistedRunStatus'] == 'paused')
        context = SimpleNamespace(run_context=self.store.process_runtime._context(actual))
        preset = self.store.autoresearch.current(context)
        session = self.store.autoresearch.row(owner, actual['id'])['body']
        require(type(session['deadline']) in (int, float) and time.time() < session['deadline']
                and any(digest(candidate) == digest(placement['candidate']) for candidate in session['candidates'].values()))
        plan = self.store.plan(actual['plan_id'], owner)
        scope = placement['scopeBinding']
        require(scope['originParentTaskId'] == actual['id'] and scope['originParentRunId'] == actual['run_id']
                and scope['originParentPlanSha256'] == digest(plan)
                and scope['candidateSha256'] == digest(placement['candidate'])
                and scope['comparisonManifestSha256'] == manifest_fingerprint(validate_manifest(preset.manifest))
                and scope['receiverSciencePinSha256'] == placement['projectPin'])
        return plan

    def _binding(self, owner, parent, child, plan, placement: Any, *, current):
        fresh_child = self.store.task(child['id'], owner)
        require(all(fresh_child.get(key) == child.get(key) for key in ('id', 'owner_id', 'plan_id', 'request_id', 'fingerprint', 'run_id')))
        child = fresh_child
        fresh_parent = self.store.task(parent['id'], owner)
        require(all(fresh_parent.get(key) == parent.get(key) for key in ('id', 'owner_id', 'plan_id', 'request_id', 'fingerprint', 'run_id')))
        parent = fresh_parent
        require(type(placement) is dict and set(placement) == _PLACEMENT and placement['phase'] in TOOLS
                and type(placement['scopeBinding']) is dict
                and set(placement['scopeBinding']) == {'originParentTaskId', 'originParentRunId',
                    'originParentPlanSha256', 'candidateSha256', 'comparisonManifestSha256', 'receiverSciencePinSha256'}
                and type(placement['prior']) is dict
                and child['owner_id'] == owner
                and not child.get('run_id') and child['plan_id'] == plan['id']
                and digest(plan) == digest(self.store.plan(child['plan_id'], owner)))
        link = self.store.delegation._link(child['id'])
        require(link and link['owner_id'] == owner and link['parent_id'] == parent['id']
                and link['root_id'] == parent['id'] and link['depth'] == 1
                and type(link['depth']) is int and link['plan_id'] == plan['id'])
        experiments = self.store.sql('SELECT * FROM af_autoresearch_remote_experiments WHERE parent_run_id=:run', run=parent['run_id'])
        require(len(experiments) == 1)
        experiment = experiments[0]
        bound = experiment['body']['binding']
        entry = experiment['body']['phases'].get(placement['phase'])
        require(experiment['fingerprint'] == digest(bound) and experiment['owner_id'] == owner
                and experiment['parent_task_id'] == parent['id'] and bound['parentRunId'] == parent['run_id']
                and bound['candidateSha256'] == digest(placement['candidate'])
                and experiment['body']['candidate'] == placement['candidate']
                and entry and entry['placement'] == placement and entry['placementSha256'] == digest(placement)
                and entry['requestId'] == link['request_id']
                and link['request_id'] == 'ar-remote:' + digest({'binding': bound, 'phase': placement['phase']}))
        parent_plan = self.store.plan(parent['plan_id'], owner)
        require(plan.get('applicationRef') == parent_plan.get('applicationRef')
                and set(plan['tools']) <= set(parent_plan['tools'])
                and set(plan['capabilities']) <= set(parent_plan['capabilities']))
        if current:
            require(not child['cancel_requested'] and not child['terminal'] and not self.store.has_failures(child['id']))
            self._parent_current(owner, parent, placement)
            self.store.delegation._mandate(owner, parent)
            self.store.require_plan_execution(owner, plan, scientific_child_id=child['id'])
        variant = self.project_validator(owner, deepcopy(parent), deepcopy(plan), deepcopy(placement))
        require(not inspect.isawaitable(variant) and type(variant) is str and re.fullmatch('[a-f0-9]{64}', variant))
        scope = {**cast(dict[str, Any], placement['scopeBinding']), 'schema': 1, 'phase': placement['phase'],
            'originChildTaskId': child['id'], 'sourceManifestSha256': digest(plan), 'variantSha256': variant}
        envelope = {'schema': 1, 'projectId': placement['projectId'], 'scope': scope,
                    'candidate': deepcopy(placement['candidate'])}
        validate_source(plan, envelope)
        return envelope

    def prepare_placement(self, owner, parent, child, sourceplan, scientific_placement):
        # Persist an inert immutable intent before the specialized child policy
        # checks its journal. Denial creates no placement or execution grant.
        envelope = self._binding(owner, parent, child, sourceplan, scientific_placement, current=False)
        body = {'ownerId': owner, 'planId': sourceplan['id'], 'placement': deepcopy(scientific_placement),
                'envelope': envelope}
        self.store.sql('''INSERT INTO af_remote_scientific_origins
            VALUES(:child,:owner,:parent,:fp,CAST(:body AS JSONB),NULL)
            ON CONFLICT(child_id) DO NOTHING''', child=child['id'], owner=owner, parent=parent['id'],
            fp=digest(body), body=canonical(body))
        require(self._row(owner, child['id'])['body'] == body)
        self.assert_authority(owner, child['id'])
        return deepcopy(envelope)

    def validate_source(self, plan, envelope):
        result = validate_source(plan, envelope)
        row = self._row(plan['ownerId'], result['scope']['originChildTaskId'])
        require(row['body']['planId'] == plan['id'] and row['body']['envelope'] == result)
        return result

    def assert_authority(self, owner, child_id):
        row = self._row(owner, child_id)
        child = self.store.task(child_id, owner)
        parent = self.store.task(row['parent_id'], owner)
        plan = self.store.plan(row['body']['planId'], owner)
        expected = self._binding(owner, parent, child, plan, row['body']['placement'], current=True)
        require(expected == row['body']['envelope'])
        return deepcopy(expected['scope'])

    def authorize_completed_custody(self, body):
        """Original successful training checkpoint read, never execution authority."""
        body = AuthorityScientificCustody.model_validate(body).model_dump()
        owner, child_id = body['originOwner'], body['originTaskId']
        row = self._row(owner, child_id)
        child = self.store.task(child_id, owner)
        parent = self.store.task(row['parent_id'], owner)
        plan = self.store.plan(row['body']['planId'], owner)
        envelope = self._binding(owner, parent, child, plan, row['body']['placement'], current=False)
        scope = envelope['scope']
        require(envelope == row['body']['envelope'] and scope['phase'] == 'training'
                and child['terminal'] is True and not child['cancel_requested']
                and not self.store.has_failures(child_id)
                and digest(scope) == body['phaseScopeSha256']
                and scope['sourceManifestSha256'] == body['manifestSha256'])
        self._parent_current(owner, parent, row['body']['placement'])
        self.store.delegation._mandate(owner, self.store.task(parent['id'], owner))
        self.store.plan_policy.require_scientific_custody(owner, plan, scientific_child_id=child_id)
        placement = self.handoff._row(owner, child_id)
        target = self.handoff._target(owner, placement, execution=False)
        require(placement['target_ref'] == body['targetRef'] and target.origin_ref == body['originRef']
                and target.configuration_revision == body['targetRevision']
                and target.fingerprint == body['targetFingerprint']
                and target.identity_map.get(owner) == body['receiverIdentity'])
        receipt = placement['body'].get('receipt') or {}
        self.validate_received_native(owner, child_id, receipt)
        require(receipt.get('remoteTaskId') == body['receiverTaskId']
                and receipt.get('remoteRunId') == body['nativeRunId']
                and receipt.get('applicationStatus') == 'completed' and receipt.get('allStopped') is True)
        evidence = validate_scientific_evidence(receipt, expected_scope=scope)
        lease = evidence['lease']
        require(scientific_stopped(receipt, expected_scope=scope)
                and lease is not None and lease['id'] == body['leaseId']
                and lease['state'] == 'RECLAIMED' and lease['executionStatus'] == 'COMPLETED'
                and type(lease['exitCode']) is int and lease['exitCode'] == 0
                and evidence['checkpoint'] is not None)
        # Recheck live parent at the return boundary. Artifact bytes are still
        # revalidated by the receiver's original checkpoint reader afterward.
        self._parent_current(owner, self.store.task(parent['id'], owner), row['body']['placement'])
        return {'custodyProofSha256': digest({'request': body, 'checkpoint': evidence['checkpoint']})}

    def consume_remote_tool(self, body):
        body = AuthorityScientificCall.model_validate(body).model_dump()
        owner, child_id = body['originOwner'], body['originTaskId']
        row = self._row(owner, child_id)
        root = row['parent_id']
        delegation = self.store.delegation
        with delegation._root_lock(root), self.store.transaction() as conn:
            scope = self.assert_authority(owner, child_id)
            require(body['phaseScopeSha256'] == digest(scope) and body['manifestSha256'] == scope['sourceManifestSha256']
                    and body['tool'] == TOOLS[scope['phase']])
            # Serialize first native attestation with authenticated receipt saves,
            # which lock this same original placement before checking the pin.
            locked = self.store.sql('SELECT * FROM af_remote_placements WHERE task_id=:id AND owner_id=:owner FOR UPDATE',
                                    id=child_id, owner=owner)
            require(len(locked) == 1)
            placement = locked[0]
            target = self.handoff._target(owner, placement)
            receipt = placement['body'].get('receipt') or {}
            require(placement['target_ref'] == body['targetRef'] and target.origin_ref == body['originRef']
                    and target.configuration_revision == body['targetRevision']
                    and target.fingerprint == body['targetFingerprint']
                    and target.identity_map.get(owner) == body['receiverIdentity']
                    and receipt.get('remoteTaskId') == body['receiverTaskId']
                    and receipt.get('remoteRunId') in (None, body['nativeRunId']))
            self.auth.require(body['receiverIdentity'], 'read')
            # The authenticated receiver may reach its first protected tool
            # before the dispatch response arrives. Pin that attested original
            # native identity against the already authenticated PREPARED task.
            # This is not a locally fabricated ticket or an execution grant.
            conn.execute(text('''INSERT INTO af_remote_scientific_receiver_runs
                VALUES(:child,:receiver,:native) ON CONFLICT(child_id) DO NOTHING'''),
                {'child': child_id, 'receiver': body['receiverTaskId'], 'native': body['nativeRunId']})
            receiver = self.store.sql('SELECT * FROM af_remote_scientific_receiver_runs WHERE child_id=:child', child=child_id)
            require(len(receiver) == 1 and receiver[0]['receiver_task_id'] == body['receiverTaskId']
                    and receiver[0]['native_run_id'] == body['nativeRunId'])
            old = self.store.sql('SELECT * FROM af_remote_scientific_calls WHERE child_id=:child AND call_id=:call',
                                 child=child_id, call=body['callId'])
            if old:
                require(len(old) == 1 and old[0]['body'] == body and old[0]['fingerprint'] == digest(body))
                return {'callProofSha256': old[0]['fingerprint']}
            existing = self.store.sql('SELECT * FROM af_delegation_tool_calls WHERE task_id=:id AND call_id=:call',
                                      id=child_id, call=body['callId'])
            require(not existing)
            # Charge the same shared table as native tools, atomically with the
            # exact receiver/native/scope binding. Never call the locking native
            # helper recursively while holding this root lock.
            for task in (self.store.task(child_id, owner), self.store.task(root, owner)):
                ids = [task['id'], *(item['child_id'] for item in delegation._descendants(task['id']) if item['child_id'])]
                used = self.store.sql('SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE task_id=ANY(:ids)', ids=ids)[0]['n']
                limit = self.store.plan(task['plan_id'], owner)['budget']['toolCalls']
                if used >= limit:
                    raise HTTPException(429, 'REMOTE_SCIENTIFIC_TOOL_BUDGET_EXHAUSTED')
            conn.execute(text('INSERT INTO af_delegation_tool_calls VALUES(:task,:call,:root,:name,:at)'),
                {'task': child_id, 'call': body['callId'], 'root': root, 'name': body['tool'], 'at': now()})
            conn.execute(text('INSERT INTO af_remote_scientific_calls VALUES(:child,:call,:fp,CAST(:body AS JSONB))'),
                {'child': child_id, 'call': body['callId'], 'fp': digest(body), 'body': canonical(body)})
            return {'callProofSha256': digest(body)}

    def validate_received_native(self, owner, child_id, receipt):
        """Reject a receipt conflicting with the first authenticated tool debit."""
        self._row(owner, child_id)
        receiver = self.store.sql('SELECT * FROM af_remote_scientific_receiver_runs WHERE child_id=:child', child=child_id)
        if receiver:
            require(len(receiver) == 1 and receipt.get('remoteTaskId') == receiver[0]['receiver_task_id']
                    and receipt.get('remoteRunId') == receiver[0]['native_run_id'])

    def drive_outcome(self, owner, child_id):
        """Read only the original once-intent; this is not a retry grant."""
        origin = self._row(owner, child_id)
        rows = self.store.sql('SELECT * FROM af_remote_scientific_drive_intents WHERE child_id=:child', child=child_id)
        if not rows:
            return None
        require(len(rows) == 1)
        receipt = self.handoff._row(owner, child_id)['body'].get('receipt') or {}
        scope_sha = digest(origin['body']['envelope']['scope'])
        require(rows[0]['scope_sha256'] == scope_sha and rows[0]['receiver_id'] == receipt.get('id')
                and receipt.get('remoteTaskId') and receipt.get('remoteRunId'))
        self.validate_received_native(owner, child_id, receipt)
        return {'driveRequested': True, 'scopeSha256': scope_sha, 'receiptId': receipt['id'],
                'receiverTaskId': receipt['remoteTaskId'], 'nativeRunId': receipt['remoteRunId']}

    async def start_phase(self, owner, child_id):
        """Once-only controller request; an unknown acknowledgement is never replayed."""
        scope = self.assert_authority(owner, child_id)
        row = self.handoff._row(owner, child_id)
        target = self.handoff._target(owner, row)
        receipt = row['body'].get('receipt') or {}
        # Only a positively acknowledged PREPARING admission can repeat its
        # idempotent prepare check. Unknown delivery is first reconciled by GET.
        if not receipt.get('remoteRunId'):
            if row.get('state') == 'PREPARING' and receipt.get('state') == 'PREPARING' and not row['body'].get('dispatchAttempted'):
                receipt = await self.handoff.prepare(owner, child_id)
                self.assert_authority(owner, child_id)
                row = self.handoff._row(owner, child_id)
            if receipt.get('receiverReviewRequired') is True:
                return None
            if row.get('state') == 'PREPARED' and receipt.get('state') == 'PREPARED' and not row['body'].get('dispatchAttempted'):
                self.assert_authority(owner, child_id)
                receipt = await self.handoff.dispatch(owner, child_id)
                self.assert_authority(owner, child_id)
                row = self.handoff._row(owner, child_id)
            elif row['body'].get('dispatchAttempted') or row.get('state') in {'UNKNOWN', 'PREPARE_UNKNOWN', 'DISPATCH_UNKNOWN'}:
                await self.handoff.receipt(owner, child_id)
                return None
            if not receipt.get('remoteRunId'):
                return None
        require(type(receipt.get('id')) is str and receipt.get('remoteTaskId'))
        self.validate_received_native(owner, child_id, receipt)
        claimed = self.store.sql('''INSERT INTO af_remote_scientific_drive_intents
            VALUES(:child,:scope,:receiver,:at) ON CONFLICT(child_id) DO NOTHING RETURNING child_id''',
            child=child_id, scope=digest(scope), receiver=receipt['id'], at=now())
        if not claimed:
            return None
        # Recheck immediately before the sole effect. Failure retains intent;
        # custody remains available through GET and original cancellation.
        self.assert_authority(owner, child_id)
        target = self.handoff._target(owner, self.handoff._row(owner, child_id))
        result = await self.handoff._request(owner, target, 'POST',
            '/api/factory/remote-handoffs/' + quote(receipt['id'], safe='') + '/scientific-drive')
        self.validate_received_native(owner, child_id, result)
        return self.handoff._save_receipt(self.handoff._row(owner, child_id), target, result)

    async def origin_phase(self, owner, child_id):
        # Custody remains readable after execution authority ends. This method
        # never returns an execution grant and never clears UNKNOWN capacity.
        self.auth.require(owner, 'read')
        return await self._phase_receipt(owner, child_id, cleanup=False)

    async def cleanup_phase(self, owner, child_id):
        """Internal stop-custody read after original cancellation, never a grant."""
        require(self.store.task(child_id, owner)['cancel_requested'] is True)
        return await self._phase_receipt(owner, child_id, cleanup=True)

    async def _phase_receipt(self, owner, child_id, *, cleanup):
        row = self._row(owner, child_id)
        scope = row['body']['envelope']['scope']
        if cleanup:
            receipt = await self.handoff.scientific_cleanup_receipt(owner, child_id, expected_scope=deepcopy(scope))
        else:
            receipt = await self.handoff.receipt(owner, child_id)
        # HTTP may overlap another observer. Serialize only the local journal,
        # then use the latest already-authenticated persisted handoff receipt.
        # Never overwrite it with the potentially stale response we awaited.
        with self.store.transaction():
            locked = self.store.sql('SELECT * FROM af_remote_scientific_origins WHERE child_id=:child AND owner_id=:owner FOR UPDATE',
                                    child=child_id, owner=owner)
            require(len(locked) == 1)
            current = self._row(owner, child_id)
            require(current['fingerprint'] == row['fingerprint'] and current['body']['envelope']['scope'] == scope)
            placement = self.handoff._row(owner, child_id)
            receipt = deepcopy(placement['body'].get('receipt'))
            require(type(receipt) is dict)
            receipt = cast(dict[str, Any], receipt)
            receipt['originDispatchState'] = placement['state']
            self.validate_received_native(owner, child_id, receipt)
            validate_scientific_evidence(receipt, expected_scope=scope, previous=current['receipt'])
            changed = self.store.sql('''UPDATE af_remote_scientific_origins SET receipt=CAST(:receipt AS JSONB)
                WHERE child_id=:child AND owner_id=:owner AND fingerprint=:fp
                AND receipt IS NOT DISTINCT FROM CAST(:previous AS JSONB) RETURNING child_id''',
                receipt=canonical(receipt), child=child_id, owner=owner, fp=current['fingerprint'],
                previous=canonical(current['receipt']) if current['receipt'] is not None else None)
            require(len(changed) == 1)
        status = str(receipt.get('applicationStatus', receipt.get('nativeStatus', 'unknown'))).lower()
        status = {'waiting_approval': 'paused', 'waiting_input': 'paused', 'canceling': 'running'}.get(status, status)
        if (not receipt.get('remoteRunId') and receipt.get('state') in {'PREPARING', 'PREPARED'}
                and receipt.get('originDispatchState', receipt['state']) in {'PREPARING', 'PREPARED'}):
            status = 'pending'
        require(status in {'queued', 'pending', 'running', 'paused', 'completed', 'failed', 'cancelled', 'canceled', 'unknown'})
        stopped = receipt.get('allStopped') is True and status in {'completed', 'failed', 'cancelled', 'canceled'}
        if scope['phase'] == 'preparation':
            native = receipt.get('native') or {}
            native_status = str((native.get('queue') or {}).get('status') or native.get('status', '')).lower().removeprefix('runstatus.')
            stopped = stopped and (native_status in {'completed', 'failed', 'cancelled', 'canceled', 'error'}
                or receipt.get('state') == 'CANCELLED_NO_DISPATCH')
        else:
            stopped = stopped and scientific_stopped(receipt, expected_scope=scope)
        return {'scope': deepcopy(scope), 'receipt': receipt, 'status': status, 'allStopped': stopped}

    async def project_baseline(self, owner, target_ref, project_id, project_pin):
        self.auth.require(owner, 'read')
        pin = self.project_bindings.get(project_id)
        require(pin and pin['ownerId'] == owner and pin['targetRef'] == target_ref and pin['projectPin'] == project_pin)
        pin = cast(dict[str, Any], pin)
        target = self.handoff.targets.get(target_ref)
        require(target is not None and owner in target.identity_map)
        fingerprint = target.fingerprint
        reply = await self.handoff._request(owner, target, 'GET',
            '/api/factory/remote-handoffs/scientific-projects/' + quote(project_id, safe='') + '/baseline',
            params={'projectPin': project_pin})
        self.auth.require(owner, 'read')
        current = self.handoff.targets.get(target_ref)
        require(current is not None and current.fingerprint == fingerprint and owner in current.identity_map
                and type(reply) is dict and set(reply) == {'schema', 'projectId', 'projectPin', 'observation'}
                and type(reply['schema']) is int and reply['schema'] == 1
                and reply['projectId'] == project_id and reply['projectPin'] == project_pin)
        observation = reply['observation']
        assess_observations(observation, observation)
        require(observation['status'] == 'completed'
                and observation['comparisonIdentitySha256'] == manifest_fingerprint(pin['manifest'])
                and observation['variantSha256'] == pin['manifest']['baselineSourceManifestSha256'])
        return deepcopy(observation)

    async def cancel_original(self, owner, child_id):
        row = self._row(owner, child_id)
        scope = row['body']['envelope']['scope']
        # Only root's separately guarded internal cleanup hook may bypass a
        # revoked public read/run grant; it retains original placement identity.
        return await self.handoff.cancel_scientific_original(owner, child_id, expected_scope=deepcopy(scope))
