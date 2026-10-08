"""One governed attached ORX turn over existing process leases and usage broker.

No scheduler, provider loop, arbitrary URL, installation route or new credential
store. The operator installs a task-owned supervisor using the existing
ResourceProvider interface. Its initial program must deny provider access until
bound. Independent operator inspection, not a response from that supervisor,
attests per-task broker-only egress and disabled native tools before dispatch.

The original native project/session is retained. Current execution authority and
installer controls are checked on every broker request. Original process-provider
custody alone handles stop/reclaim after revocation; an interrupt ACK never frees
capacity. This first profile permits one existing session turn and one provider
request; broader native tool execution is deliberately not admitted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import inspect
import secrets
from types import SimpleNamespace
from typing import Any, Callable

from .orx_research_broker import ORXResearchBroker, MODEL
from .orx_research_session import OpenResearchSessionHTTP, _id
from .resources import PersistentResourceService, TERMINAL
from .store import digest

EFFECT = 'managed-orx-attached-turn-v1'


def require(value):
    if not value:
        raise ValueError('MANAGED_ORX_ATTACHMENT_UNCONFIRMED')


def profile_pin(options):
    """Canonical native wire options from SessionProfile.options()."""
    return {key: value for key, value in {
        'harness': options['harness'], 'model': options['model'],
        'permissionMode': options.get('permission_mode'),
        'serviceTier': options.get('service_tier'),
        'reasoningLevel': options.get('reasoning_level'),
        'planMode': options.get('plan_mode')}.items() if value is not None}


@dataclass(frozen=True)
class InstalledAttachment:
    """Trusted installation pin. Never deserialize this from an HTTP request.

    authority is an in-process provenance token retained by the independently
    installed enforcement reader. A remote JSON/signed assertion cannot carry it.
    Production readers must inspect actual task scope and routing controls; a
    controlled test reader is synthetic evidence, never a deployment attestation.
    """
    supervisor_id: str
    revision: str
    enforcement_sha256: str
    authority: object = field(repr=False, compare=False)

    def __post_init__(self):
        require(type(self.authority) is object)
        require(all(type(v) is str and 1 <= len(v) <= 128 for v in (self.supervisor_id, self.revision)))
        require(type(self.enforcement_sha256) is str and len(self.enforcement_sha256) == 64
                and all(c in '0123456789abcdef' for c in self.enforcement_sha256))

    def public(self):
        return {'supervisorId': self.supervisor_id, 'revision': self.revision,
                'enforcementSha256': self.enforcement_sha256}


@dataclass(frozen=True)
class AttachmentControlWitness:
    """Result of an independent trusted reader, not native-runtime telemetry."""
    authority: object = field(repr=False, compare=False)
    lease_id: str
    lease_fingerprint: str
    enforcement_sha256: str
    broker_capability_sha256: str
    project_identity_hash: str
    connection_fingerprint: str
    profile_sha256: str
    native_session_id: str
    session_exclusive: bool
    task_process_scope: str
    broker_only_egress: bool
    provider_credentials_absent: bool
    native_tools_disabled: bool


class ManagedORXSessionProvider:
    """ResourceProvider decorator; reuse existing allocation and lifecycle owners.

    bind_session is the installed supervisor bridge: bind this task's broker app
    and ephemeral capability, then return its scoped original-session transport.
    It must not send a message, create a project/session, grant tools or alter
    model credentials. Process allocation itself remains provider-owned.
    """
    effect_key = 'bounded-process-run-v1'

    def __init__(self, *, store, process_provider, attachment: dict,
                 installation: InstalledAttachment, read_controls: Callable,
                 bind_session: Callable, credential: Callable, ledger_model: Any, observe_session: Callable | None = None,
                 broker_transport=None):
        require(type(installation) is InstalledAttachment and all(callable(v) for v in
            (read_controls, bind_session, credential)))
        require(set(attachment) == {'ownerId', 'connectionRef', 'connectionFingerprint', 'connectionVersion', 'connectionRevision', 'projectId', 'projectIdentityHash', 'sessionId', 'profile', 'profileSha256'})
        _id(attachment['projectId']); _id(attachment['sessionId'])
        require(type(attachment['connectionVersion']) is int and attachment['connectionVersion'] >= 1
                and type(attachment['connectionRevision']) is str and 1 <= len(attachment['connectionRevision']) <= 120
                and all(type(attachment[k]) is str and 1 <= len(attachment[k]) <= 200
                        for k in ('ownerId', 'connectionRef')))
        require(all(type(attachment[k]) is str and len(attachment[k]) == 64
                    and all(c in '0123456789abcdef' for c in attachment[k])
                    for k in ('connectionFingerprint', 'projectIdentityHash')))
        profile = attachment['profile']
        require(type(profile) is dict and set(profile) <= {'harness', 'model', 'permissionMode', 'serviceTier', 'reasoningLevel', 'planMode'}
                and profile.get('harness') == 'opencode'
                and profile.get('model') == 'factory/' + MODEL and attachment['profileSha256'] == digest(profile))
        require(all(type(attachment[k]) is str and 1 <= len(attachment[k]) <= 160
                    for k in ('projectId', 'sessionId')))
        require(type(attachment['projectIdentityHash']) is str and len(attachment['projectIdentityHash']) == 64)
        require(ledger_model.id == MODEL)
        require(all(callable(getattr(process_provider, name, None)) for name in
            ('allocate_bound', 'inspect', 'cancel', 'reclaim')))
        self.store, self.process_provider, self.installation = store, process_provider, installation
        self.read_controls, self.bind_session, self._credential = read_controls, bind_session, credential
        self.observe_session = observe_session
        self._model, self._broker_transport = ledger_model, broker_transport
        import copy
        self._contract = {**copy.deepcopy(attachment), 'installation': installation.public(),
                         'modelRequests': 1, 'nativeTools': 'disabled', 'brokerModel': MODEL}
        self.limits = process_provider.limits
        self.preflight_seconds = getattr(process_provider, 'preflight_seconds', 0)
        self.aggregate_config = getattr(process_provider, 'aggregate_config', None)
        self.capacity_namespace = process_provider.capacity_namespace
        self._process_pin = process_provider.configuration_fingerprint
        self.configuration_fingerprint = digest({'adapter': EFFECT, 'contract': self.contract,
            'processProvider': process_provider.configuration_fingerprint})
        self._brokers: dict[str, ORXResearchBroker] = {}
        self._turns: dict[str, tuple] = {}
        self._results: dict[str, dict] = {}

    @property
    def contract(self):
        import copy
        return copy.deepcopy(self._contract)

    def _original(self, lease_id, owner):
        require(owner == self.contract['ownerId'] and self.process_provider.configuration_fingerprint == self._process_pin
                and self.process_provider.capacity_namespace == self.capacity_namespace)
        rows = self.store.sql('SELECT body FROM af_leases WHERE id=:id AND owner_id=:owner', id=lease_id, owner=owner)
        require(len(rows) == 1)
        lease = rows[0]['body']
        if isinstance(lease, str):
            import json
            lease = json.loads(lease)
        task = self.store.task(lease['localTaskId'], owner)
        plan = self.store.plan(task['plan_id'], owner)
        require(task['run_id'] == lease['nativeRunId'] and task['plan_id'] == lease['planId']
                and digest(plan) == lease['planHash']
                and plan.get('inputValues', {}).get('managedAttachment') == self.contract)
        context = SimpleNamespace(user_id=owner, session_id=task['id'], run_id=task['run_id'],
            session_state={'factory_envelope': {'plan_ref': plan['id'], 'user_id': owner,
                'task_id': task['id'], 'request_id': task['request_id']}})
        return lease, task, plan, context

    def _current(self, lease):
        original, task, plan, context = self._original(lease['id'], lease['ownerId'])
        require(all(original[key] == lease[key] for key in ('fingerprint', 'nativeRunId', 'planHash', 'providerNamespace')))
        require(not task.get('terminal') and not task.get('cancel_requested')
                and datetime.now(timezone.utc) < datetime.fromisoformat(lease['deadlineAt']))
        require(original.get('state') not in TERMINAL | {'CANCEL_REQUESTED', 'RECLAIMING', 'RECLAIMED'}
                and not original.get('cancelRequested') and original.get('releaseAck') not in {'unknown', 'confirmed'})
        resources = self.store.process_runtime.resources
        target = resources._authorize(context.user_id, original['connectionRef'])
        require(target.provider is self and resources._target_fingerprint(target) == original['targetFingerprint'])
        resources._admit_effect(context.user_id, original)
        from .orx_workspace_adapter import ADAPTER_ID
        self.store.connections.preflight(context.user_id, self.contract['connectionRef'], 'orx',
            expected_adapter_ref=ADAPTER_ID, required_capabilities=['project:read'],
            expected_fingerprint=self.contract['connectionFingerprint'],
            expected_version=self.contract['connectionVersion'], expected_revision=self.contract['connectionRevision'])
        self.store.require_plan_execution(context.user_id, plan, run_context=context)
        self.store.authorize_tool(context, 'bounded_process_run')
        return plan, context

    async def _controls(self, lease, capability):
        value = self.read_controls(lease=lease, contract=self.contract)
        if inspect.isawaitable(value):
            value = await value
        require(type(value) is AttachmentControlWitness and value.authority is self.installation.authority
            and value.lease_id == lease['id'] and value.lease_fingerprint == lease['fingerprint']
            and value.enforcement_sha256 == self.installation.enforcement_sha256
            and value.broker_capability_sha256 == hashlib.sha256(capability.encode()).hexdigest()
            and value.project_identity_hash == self.contract['projectIdentityHash']
            and value.connection_fingerprint == self.contract['connectionFingerprint']
            and value.profile_sha256 == self.contract['profileSha256']
            and value.native_session_id == self.contract['sessionId'] and value.session_exclusive is True
            and value.task_process_scope == lease['id']
            and value.broker_only_egress is True and value.provider_credentials_absent is True
            and value.native_tools_disabled is True)

    def _intent(self, lease, intent):
        self._current(lease)
        key = EFFECT + ':' + intent['key']
        result = self.store.effect_reserve(lease['nativeRunId'], key, {'lease': lease['fingerprint'], **dict(intent)})
        require(result['status'] == 'new')  # Never resend UNKNOWN, even on restart.

    @staticmethod
    def _live(lease, snapshot):
        PersistentResourceService.process_snapshot(lease, snapshot)
        require(snapshot.get('state') in {'RUNNING', 'ACCEPTED'}
                and snapshot.get('executionStatus') in {'RUNNING', 'PREPARED'}
                and snapshot.get('stopEvidence') is None and snapshot.get('released') is not True)

    def _effect_result(self, lease, key):
        effect = next((e for e in self.store.effects(lease['localTaskId'])
            if e.get('effect_key') == lease['nativeRunId'] + ':' + EFFECT + ':' + key
            and e.get('status') == 'DONE'), None)
        if effect is None:
            return None
        value = effect.get('result')
        return __import__('json').loads(value) if isinstance(value, str) else value

    def _client_scope(self, client):
        require(isinstance(client, OpenResearchSessionHTTP))
        profile = self.contract['profile']
        require(client.project_id == self.contract['projectId'] and client.harness == profile['harness']
            and client.model == profile['model'] and client.permission_mode == profile.get('permissionMode')
            and client._optional_pins() == {k: profile[k] for k in ('serviceTier', 'planMode', 'reasoningLevel') if k in profile})

    async def _observe_result(self, lease, snapshot):
        if snapshot.get('state') not in TERMINAL | {'RECLAIMED'}:
            return
        self._live_result_scope(lease)
        if lease['id'] not in self._turns:
            if not callable(self.observe_session):
                return
            before = self._effect_result(lease, 'before-turn')
            receipt = self._effect_result(lease, 'one-original-message')
            # An unknown ACK does not reveal an original native turn ID.
            if before is None or receipt is None or not receipt.get('turnId'):
                return
            client = self.observe_session(lease=lease, contract=self.contract)
            if inspect.isawaitable(client):
                client = await client
            self._client_scope(client)
            goal = self._original(lease['id'], lease['ownerId'])[2]['normalizedGoal']
            self._turns[lease['id']] = (client, before, receipt, goal)
        client, before, receipt, goal = self._turns[lease['id']]
        after = await client.read_messages(self.contract['sessionId'])
        self._live_result_scope(lease)
        known = set(before['messageIds'])
        added = [row for row in after['messages'] if row['id'] not in known]
        users = [row for row in added if row['role'] == 'user' and row.get('parentId') == before['activeLeafId']]
        require(len(added) == 2 and len(users) == 1 and not after['queued'])
        user = users[0]
        require(len(user['parts']) == 1 and user['parts'][0].get('type') == 'text'
                and user['parts'][0].get('text') == goal)
        answers = [row for row in added if row['role'] == 'assistant' and row.get('parentId') == user['id']
                   and row['id'] == after['activeLeafId'] and type(row.get('completedAt')) is int]
        require(len(answers) == 1 and all(part.get('type') == 'text' for part in answers[0]['parts']))
        answer = answers[0]
        result_text = '\n'.join(part['text'] for part in answer['parts'] if type(part.get('text')) is str)
        require(0 < len(result_text.encode()) <= 32768)
        value = {**receipt, 'projectId': self.contract['projectId'], 'userMessageId': user['id'],
            'assistantMessageId': answer['id'], 'text': result_text,
            'correlationSource': 'exclusive-original-turn-transcript-delta',
            'evidenceKind': 'native-session-response', 'scientificConclusionVerified': False}
        old = self._results.get(lease['id'])
        require(old is None or old == value)
        if old is None:
            self.store.artifact_write(lease['nativeRunId'], 'native-response-' + lease['id'] + '.json',
                __import__('json').dumps(value, sort_keys=True), 'application/json',
                {'evidenceKind': 'native-session-response', 'sessionId': self.contract['sessionId'],
                 'turnId': receipt['turnId'], 'leaseId': lease['id'], 'scientificConclusionVerified': False})
            self.store.event(lease['localTaskId'], 'managed_native_session_result',
                'Original exclusive native turn response observed; process stop is checked separately', value)
            self._results[lease['id']] = value

    def _live_result_scope(self, lease):
        # Observation never grants execution or changes provider accounting.
        _, _, plan, context = self._original(lease['id'], lease['ownerId'])
        self.store.require_plan_execution(context.user_id, plan, run_context=context)

    def _snapshot(self, lease, snapshot):
        # Reuse the same process identity, enforcement and positive-stop validator.
        PersistentResourceService.process_snapshot(lease, snapshot)
        if snapshot.get('state') in TERMINAL | {'RECLAIMED'}:
            # Kernel stop proof settles custody of an uncertain message dispatch,
            # not its successful delivery or model result. Never retransmit it.
            key = lease['nativeRunId'] + ':' + EFFECT + ':one-original-message'
            pending = [effect for effect in self.store.effects(lease['localTaskId'])
                       if effect.get('effect_key') == key and effect.get('status') == 'UNKNOWN']
            if pending:
                self.store.effect_complete(lease['nativeRunId'], EFFECT + ':one-original-message', {
                    'sessionId': self.contract['sessionId'], 'deliveryOutcome': 'unknown',
                    'allStopped': True, 'stopEvidence': snapshot['stopEvidence'], 'cancelled': True})
            previous = next((e.get('result') for e in self.store.effects(lease['localTaskId'])
                if e.get('effect_key') == lease['nativeRunId'] + ':' + EFFECT and e.get('status') in {'DONE', 'CANCELLED'}), None)
            if isinstance(previous, str):
                previous = __import__('json').loads(previous)
            saved_result = previous.get('nativeResult') if isinstance(previous, dict) else None
            native_result = self._results.get(lease['id'], saved_result)
            if saved_result is not None:
                require(native_result == saved_result)
            self.store.effect_complete(lease['nativeRunId'], EFFECT, {
                'leaseId': lease['id'], 'projectId': self.contract['projectId'],
                'sessionId': self.contract['sessionId'], 'allStopped': True,
                'stopEvidence': snapshot['stopEvidence'], 'executionStatus': snapshot['executionStatus'],
                'nativeResult': native_result})
        return snapshot

    async def allocate_bound(self, lease, *, before_effect):
        plan, context = self._current(lease)
        committed = self.store.effect_reserve(lease['nativeRunId'], EFFECT,
            {'leaseId': lease['id'], 'leaseFingerprint': lease['fingerprint'], 'contract': self.contract})
        require(committed['status'] == 'new')
        capability = secrets.token_urlsafe(32)
        async def authority():
            self._current(lease)
            await self._controls(lease, capability)
            self._live(lease, await self.process_provider.inspect(lease['id'], lease['ownerId']))
            self._current(lease)
            return True
        async def reserve(_ordinal, _input, _output, body):
            await authority()
            # First managed profile is text-only; no arbitrary harness tools.
            require(not body.get('tools') and body.get('tool_choice') in (None, 'none'))
            return self.store.usage_ledger.begin_attempt(context, plan, self._model,
                streaming=body.get('stream', False), arguments=(body,))
        async def settle(ticket, usage):
            self.store.usage_ledger.finish_attempt(ticket, usage)
        async def hold(ticket, _reason):
            self.store.usage_ledger.finish_attempt(ticket, None)
        commitment = plan.get('usageBudget') or {}
        require(commitment.get('model') == MODEL and commitment.get('provider') == self._model.provider
                and type(commitment.get('perAttemptOutputTokens')) is int)
        broker = ORXResearchBroker(capability=capability,
            session_id=digest({'task': context.session_id, 'run': context.run_id}),
            credential=self._credential, current_authority=authority, reserve=reserve, settle=settle, hold=hold,
            transport=self._broker_transport, max_requests=1,
            max_output_tokens=min(4096, commitment['perAttemptOutputTokens']))
        self._brokers[lease['id']] = broker
        before_effect()
        process = await self.process_provider.allocate_bound(lease, before_effect=before_effect)
        self._live(lease, process)
        self._current(lease)
        # No provider request may run before independent controls are checked.
        client = self.bind_session(lease=lease, contract=self.contract, broker=broker, capability=capability)
        if inspect.isawaitable(client):
            client = await client
        self._client_scope(client)
        await authority()
        original = await client.read_session(self.contract['sessionId'])
        require(not original['busy'] and not original['archived'])
        transcript = await client.read_messages(self.contract['sessionId'])
        require(not transcript['queued'])
        before = {'messageIds': [row['id'] for row in transcript['messages']], 'activeLeafId': transcript['activeLeafId']}
        baseline = self.store.effect_reserve(context.run_id, EFFECT + ':before-turn', {'lease': lease['fingerprint'], **before})
        require(baseline['status'] == 'new')
        self.store.effect_complete(context.run_id, EFFECT + ':before-turn', before)
        await authority()
        receipt = await client.send_message(self.contract['sessionId'], plan['normalizedGoal'],
            client_turn_id=digest({'lease': lease['id'], 'run': context.run_id}), key='one-original-message',
            commit_intent=lambda *, intent: self._intent(lease, intent))
        self.store.effect_complete(context.run_id, EFFECT + ':one-original-message', receipt)
        self._turns[lease['id']] = (client, before, receipt, plan['normalizedGoal'])
        self.store.event(context.session_id, 'managed_native_session_accepted',
            'Original native session accepted one governed turn; completion is not yet proved',
            {'leaseId': lease['id'], 'projectId': self.contract['projectId'], **receipt,
             'usageSource': 'shared-ledger-broker', 'enforcementSource': 'independent-operator-reader'})
        observed = await self.process_provider.inspect(lease['id'], lease['ownerId'])
        await self._observe_result(lease, observed)
        return self._snapshot(lease, observed)

    async def inspect(self, lease_id, owner):
        lease, _, _, _ = self._original(lease_id, owner)
        # Inspection/cleanup never creates another broker or retransmits a turn.
        observed = await self.process_provider.inspect(lease_id, owner)
        try:
            await self._observe_result(lease, observed)
        except Exception:
            pass  # Stop proof remains usable; absent result is never invented.
        return self._snapshot(lease, observed)

    async def cancel(self, lease_id, owner):
        lease, _, _, _ = self._original(lease_id, owner)
        broker = self._brokers.get(lease_id)
        if broker is not None:
            broker.stopped_reason = 'ORIGINAL_CUSTODY_STOP'
        return self._snapshot(lease, await self.process_provider.cancel(lease_id, owner))

    async def reclaim(self, lease_id, owner):
        lease, _, _, _ = self._original(lease_id, owner)
        current = await self.process_provider.inspect(lease_id, owner)
        self._snapshot(lease, current)
        require((current.get('stopEvidence') or {}).get('allStopped') is True and current.get('state') in TERMINAL | {'RECLAIMED'})
        result = self._snapshot(lease, await self.process_provider.reclaim(lease_id, owner))
        if result.get('state') == 'RECLAIMED':
            self._brokers.pop(lease_id, None)
        return result

    async def allocate(self, *args, **kwargs):
        raise ValueError('MANAGED_ORX_REQUIRES_ORIGINAL_NATIVE_LEASE')
