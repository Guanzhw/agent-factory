"""Application-owned serial research rounds; execution remains in the native driver.

Only trusted drivers supply verified evaluation/artifact evidence. No browser read
advances a round, and an uncertain dispatch is observed under its original ID.
"""
from copy import deepcopy
from dataclasses import dataclass
import math
import time
from typing import Any, Mapping, Protocol
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, UniqueConstraint, select

from agent_factory.store import digest


@dataclass(frozen=True)
class IterationPreset:
    id: str
    owner_id: str
    fingerprint: str
    pins: Mapping[str, Any]
    baseline_source: Mapping[str, Any]
    round_caps: Mapping[str, Any]
    round_seconds: float


class RoundDriver(Protocol):
    def reserve(self, owner, activity, round) -> dict[str, Any]: ...
    async def dispatch(self, owner, round) -> Any: ...
    async def observe(self, owner, round) -> dict[str, Any]: ...
    async def cancel(self, owner, round) -> Any: ...


def _require(value, code, status=409):
    if not value:
        raise HTTPException(status, code)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _caps(value):
    _require(isinstance(value, dict) and set(value) == {'rounds', 'toolCalls', 'tokenLimit', 'amountMicros', 'currency'},
             'ITERATION_CAP_SCHEMA', 422)
    _require(all(type(value[key]) is int and value[key] > 0 for key in ('rounds', 'toolCalls')),
             'ITERATION_CAP_SCHEMA', 422)
    if value['amountMicros'] is None:
        _require(value['tokenLimit'] is None and value['currency'] is None, 'ITERATION_CAP_SCHEMA', 422)
    else:
        _require(type(value['tokenLimit']) is int and value['tokenLimit'] > 0
                 and type(value['amountMicros']) is int and value['amountMicros'] >= 0
                 and isinstance(value['currency'], str) and bool(value['currency']), 'ITERATION_CAP_SCHEMA', 422)
    return deepcopy(value)


class ResearchIterations:
    def __init__(self, store, auth, *, research, presets, round_driver: RoundDriver):
        self.research = research.require_store(store)
        self.store, self.auth, self.driver = store, auth, round_driver
        self.presets = deepcopy(dict(presets))
        self.accepting = True
        metadata = MetaData()
        self.activities = Table('af_research_activities', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('request_id', String, nullable=False), Column('fingerprint', String, nullable=False),
            Column('body', JSON, nullable=False), UniqueConstraint('owner_id', 'request_id'))
        self.rounds = Table('af_research_rounds', metadata,
            Column('id', String, primary_key=True), Column('activity_id', String, nullable=False),
            Column('ordinal', Integer, nullable=False), Column('previous_id', String, unique=True),
            Column('body', JSON, nullable=False), UniqueConstraint('activity_id', 'ordinal'))
        metadata.create_all(store.engine)

    @property
    def scopes(self):
        return self.store.local_budget_scopes

    def _member(self, owner):
        self.research.require_store(self.store, ready=True)
        self.auth.require_member(owner)

    def _activity(self, conn, owner, identifier, *, lock=False):
        query = select(self.activities).where(self.activities.c.id == identifier, self.activities.c.owner_id == owner)
        row = conn.execute(query.with_for_update() if lock else query).mappings().first()
        _require(row is not None, 'ITERATION_NOT_FOUND', 404)
        return deepcopy(row['body'])

    def _round(self, conn, identifier):
        row = conn.execute(select(self.rounds).where(self.rounds.c.id == identifier)).mappings().first()
        _require(row is not None, 'ITERATION_ROUND_NOT_FOUND', 404)
        return deepcopy(row['body'])

    def _save(self, conn, activity, round=None):
        conn.execute(self.activities.update().where(self.activities.c.id == activity['id']).values(body=deepcopy(activity)))
        if round is not None:
            conn.execute(self.rounds.update().where(self.rounds.c.id == round['id']).values(body=deepcopy(round)))

    def inspect(self, owner, activity_id):
        self._member(owner)
        with self.store.transaction(read_only=True) as conn:
            activity = self._activity(conn, owner, activity_id)
            rounds = conn.execute(select(self.rounds.c.body).where(self.rounds.c.activity_id == activity_id)
                                  .order_by(self.rounds.c.ordinal)).scalars().all()
            budget = self.scopes.inspect(owner, activity['scopeId'])
            return {'activity': activity, 'rounds': deepcopy(rounds), 'budget': budget}

    def round_for_task(self, owner, task_id):
        """Resolve only a persisted original root; never create an activity."""
        self._member(owner)
        with self.store.transaction(read_only=True) as conn:
            row = conn.execute(select(self.rounds.c.body).join(
                self.activities, self.activities.c.id == self.rounds.c.activity_id).where(
                self.activities.c.owner_id == owner,
                self.rounds.c.body['taskId'].as_string() == task_id)).scalar_one_or_none()
            _require(row is not None, 'ITERATION_ROUND_NOT_FOUND', 404)
            return deepcopy(row)

    def _preset(self, owner, identifier):
        preset = self.presets.get(identifier)
        if not isinstance(preset, IterationPreset) or preset.owner_id != owner:
            raise HTTPException(404, 'ITERATION_PRESET_NOT_FOUND')
        return preset

    def _reserve(self, conn, owner, activity, ordinal, previous):
        _require(not activity['cancelRequested'], 'ITERATION_CANCELLED')
        _require(time.time() + activity['roundSeconds'] <= activity['deadline'], 'ITERATION_DEADLINE')
        identifier = str(uuid5(NAMESPACE_URL, activity['id'] + ':round:' + str(ordinal)))
        intent = {'id': identifier, 'activityId': activity['id'], 'ownerId': owner, 'ordinal': ordinal,
                  'previousRoundId': previous, 'requestId': 'research-round:' + identifier,
                  'allocationId': identifier, 'baselineSource': deepcopy(activity['baselineSource']),
                  'pins': deepcopy(activity['pins']), 'presetFingerprint': activity['presetFingerprint'],
                  'deadline': activity['deadline'], 'roundSeconds': activity['roundSeconds'],
                  'caps': deepcopy(activity['roundCaps'])}
        allocation = self.scopes.allocate(conn, owner, activity['scopeId'], identifier, digest(intent), intent['caps'])
        _require(allocation['allocationId'] == identifier, 'ITERATION_ALLOCATION_IDENTITY')
        round = {**intent, 'intentSha256': digest(intent), 'state': 'RESERVED', 'dispatchAttempted': False,
                 'taskId': None, 'planId': None, 'planSha256': None, 'runId': None, 'observation': None}
        bound = self.driver.reserve(owner, deepcopy(activity), deepcopy(round))
        _require(isinstance(bound, dict) and set(bound) == {'taskId', 'planId', 'planSha256'}
                 and all(isinstance(v, str) and v for v in bound.values()), 'ITERATION_DRIVER_BINDING')
        self.scopes.bind_root(conn, owner, identifier, bound['taskId'], bound['planSha256'])
        round.update(bound)
        conn.execute(self.rounds.insert().values(id=identifier, activity_id=activity['id'], ordinal=ordinal,
                                                previous_id=previous, body=round))
        activity.update(currentRoundId=identifier, status='reserved')
        self._save(conn, activity)
        return round

    async def start(self, owner, preset_id, goal, request_id, *, caps, deadline):
        self._member(owner)
        _require(self.accepting, 'ITERATION_ADMISSION_CLOSED')
        preset = self._preset(owner, preset_id)
        caps, round_caps = _caps(caps), _caps(dict(preset.round_caps))
        _require(caps['rounds'] <= 2 and round_caps['rounds'] == 1, 'ITERATION_TWO_ROUND_PRESET', 422)
        _require(isinstance(goal, str) and 2 <= len(goal.strip()) <= 2000
                 and isinstance(request_id, str) and 1 <= len(request_id) <= 200, 'ITERATION_REQUEST', 422)
        _require(_finite(deadline) and _finite(preset.round_seconds) and preset.round_seconds > 0,
                 'ITERATION_DEADLINE', 422)
        _require((caps['currency'], caps['tokenLimit'] is None) == (round_caps['currency'], round_caps['tokenLimit'] is None),
                 'ITERATION_METERING_MISMATCH', 422)
        _require(caps['tokenLimit'] is None or getattr(self.store, 'usage_ledger', None) is not None,
                 'ITERATION_METERING_UNAVAILABLE', 422)
        baseline = deepcopy(dict(preset.baseline_source))
        _require(baseline.get('kind') in {'reviewedSeed', 'sourceArtifact'}
                 and _finite(baseline.get('metricValue')) and baseline['metricValue'] >= 0
                 and all(isinstance(baseline.get(k), str) and baseline[k] for k in
                         ('sha256', 'datasetSha256', 'evaluatorSha256')), 'ITERATION_BASELINE_PIN', 422)
        intent = {'continuationPolicy': 'strict-improvement-v1', 'ownerId': owner, 'presetId': preset_id, 'presetFingerprint': preset.fingerprint,
                  'goal': goal.strip(), 'requestId': request_id, 'caps': caps, 'deadline': deadline,
                  'pins': deepcopy(dict(preset.pins)), 'baselineSource': baseline,
                  'roundCaps': round_caps, 'roundSeconds': preset.round_seconds}
        fingerprint = digest(intent)
        identifier = str(uuid5(NAMESPACE_URL, 'research-activity:' + digest({'owner': owner, 'request': request_id})))
        with self.store.transaction() as conn:
            self.scopes.lock(conn)
            old = conn.execute(select(self.activities).where(self.activities.c.id == identifier).with_for_update()).mappings().first()
            if old is not None:
                _require(old['owner_id'] == owner and old['fingerprint'] == fingerprint, 'ITERATION_REQUEST_CONFLICT')
            else:
                self.scopes.create_scope(owner, identifier, fingerprint, caps, deadline)
                activity = {**intent, 'id': identifier, 'scopeId': identifier, 'cancelRequested': False,
                            'status': 'reserved', 'stopReason': None, 'currentRoundId': None}
                conn.execute(self.activities.insert().values(id=identifier, owner_id=owner, request_id=request_id,
                                                             fingerprint=fingerprint, body=activity))
                self._reserve(conn, owner, activity, 1, None)
        await self._dispatch(owner, identifier)
        return self.inspect(owner, identifier)

    async def _dispatch(self, owner, activity_id):
        expired = False
        with self.store.transaction() as conn:
            self.scopes.lock(conn)
            activity = self._activity(conn, owner, activity_id, lock=True)
            round = self._round(conn, activity['currentRoundId'])
            if not self.accepting or activity['cancelRequested'] or round['dispatchAttempted']:
                return
            expired = time.time() + activity['roundSeconds'] > activity['deadline']
            if expired:
                self.scopes.cancel(owner, activity['scopeId'])
                activity.update(cancelRequested=True, status='canceling', stopReason='deadline')
            else:
                round.update(dispatchAttempted=True, state='DISPATCH_UNKNOWN')
                activity['status'] = 'unknown'
            self._save(conn, activity, round)
        if expired:
            await self.driver.cancel(owner, deepcopy(round))
            return
        # The driver rechecks current native authority. A lost acknowledgement
        # leaves this committed fence; no subsequent call repeats dispatch.
        outcome = await self.driver.dispatch(owner, deepcopy(round))
        if outcome == {'notSubmitted': True, 'reason': 'preflight_rejected'}:
            with self.store.transaction() as conn:
                self.scopes.lock(conn)
                activity = self._activity(conn, owner, activity_id, lock=True)
                current = self._round(conn, round['id'])
                _require(current['dispatchAttempted'] and current['runId'] is None
                         and current['taskId'] == round['taskId'], 'ITERATION_DISPATCH_IDENTITY')
                task = self.store.task(current['taskId'], owner)
                _require(task['run_id'] is None, 'ITERATION_DISPATCH_IDENTITY')
                self.store.admission_failed(task['id'], 'Iteration rejected before native submission')
                current['dispatchRejected'] = True
                self._save(conn, activity, current)

    def _evaluation(self, round, observation):
        value, source = observation.get('evaluation'), observation.get('sourcePin')
        if value is None:
            return None
        _require(isinstance(value, dict) and isinstance(source, dict), 'ITERATION_EVALUATION_IDENTITY')
        baseline = round['baselineSource']
        _require(value.get('metric') == 'mean_squared_error'
                 and all(_finite(value.get(k)) and value[k] >= 0 for k in ('baselineValue', 'candidateValue'))
                 and value['baselineValue'] == baseline['metricValue']
                 and value.get('baselineSourceSha256') == baseline['sha256'], 'ITERATION_EVALUATION_IDENTITY')
        _require(source.get('kind') == 'sourceArtifact' and source.get('ownerId') == round['ownerId']
                 and source.get('taskId') == round['taskId']
                 and value.get('candidateSourceSha256') == source.get('sha256')
                 and all(value.get(k) == source.get(k) == baseline[k] for k in ('datasetSha256', 'evaluatorSha256'))
                 and all(isinstance(item.get(k), str) and item[k] for item in (source, value) for k in ('artifactId', 'sha256')),
                 'ITERATION_EVALUATION_IDENTITY')
        return {**deepcopy(source), 'metricValue': value['candidateValue'],
                'evaluationArtifactId': value['artifactId'], 'evaluationSha256': value['sha256']}

    async def reconcile(self, owner, activity_id):
        self._member(owner)
        snapshot = self.inspect(owner, activity_id)
        activity, round = snapshot['activity'], snapshot['rounds'][-1]
        if round['state'] == 'SETTLED':
            return snapshot
        if not activity['cancelRequested'] and time.time() >= activity['deadline']:
            await self._cancel(owner, activity_id, reason='deadline')
            snapshot = self.inspect(owner, activity_id)
            activity, round = snapshot['activity'], snapshot['rounds'][-1]
        if not round['dispatchAttempted'] and not activity['cancelRequested']:
            await self._dispatch(owner, activity_id)
            return self.inspect(owner, activity_id)
        observed = await self.driver.observe(owner, deepcopy(round))
        _require(isinstance(observed, dict) and observed.get('taskId') == round['taskId']
                 and observed.get('state') in {'pending', 'unknown', 'stopped'}, 'ITERATION_OBSERVATION_IDENTITY')
        promoted = self._evaluation(round, observed) if observed['state'] == 'stopped' else None
        settlement = self.scopes.settle(owner, round['allocationId']) if observed['state'] == 'stopped' else None
        with self.store.transaction() as conn:
            self.scopes.lock(conn)
            activity = self._activity(conn, owner, activity_id, lock=True)
            current = self._round(conn, round['id'])
            if current['state'] == 'SETTLED' or activity['currentRoundId'] != round['id']:
                return self.inspect(owner, activity_id)
            _require(current['runId'] is None or current['runId'] == observed.get('runId'), 'ITERATION_RUN_IDENTITY')
            current['runId'] = observed.get('runId')
            current['observation'] = deepcopy(observed)
            if settlement is None or settlement['state'] != 'SETTLED':
                current['state'] = 'UNKNOWN' if observed['state'] != 'pending' else 'RUNNING'
                activity['status'] = 'canceling' if activity['cancelRequested'] else current['state'].lower()
            else:
                _require(settlement['allocationId'] == current['allocationId'], 'ITERATION_ALLOCATION_IDENTITY')
                current.update(state='SETTLED', settlement=deepcopy(settlement))
                reason = ((activity.get('stopReason') or 'cancelled') if activity['cancelRequested'] else 'evaluation_unavailable' if promoted is None
                          else 'improved' if promoted['metricValue'] < current['baselineSource']['metricValue']
                          else 'tie' if promoted['metricValue'] == current['baselineSource']['metricValue'] else 'regressed')
                if reason == 'improved':
                    activity['baselineSource'] = promoted
                activity.update(status='ready' if reason == 'improved' else 'stopped', stopReason=None if reason == 'improved' else reason)
                current['decision'] = reason
            self._save(conn, activity, current)
        return self.inspect(owner, activity_id)

    async def advance(self, owner, activity_id, previous_round_id, request_id):
        self._member(owner)
        _require(self.accepting, 'ITERATION_ADMISSION_CLOSED')
        _require(isinstance(request_id, str) and 1 <= len(request_id) <= 200, 'ITERATION_REQUEST', 422)
        with self.store.transaction() as conn:
            self.scopes.lock(conn)
            activity = self._activity(conn, owner, activity_id, lock=True)
            previous = self._round(conn, previous_round_id)
            _require(previous['activityId'] == activity_id, 'ITERATION_ROUND_NOT_FOUND', 404)
            successor = conn.execute(select(self.rounds).where(self.rounds.c.previous_id == previous_round_id)).mappings().first()
            requests = activity.setdefault('advanceRequests', {})
            replay = request_id in requests
            _require(not replay or requests[request_id] == previous_round_id, 'ITERATION_REQUEST_CONFLICT')
            if successor is None and not replay:
                _require(activity['currentRoundId'] == previous_round_id and activity['status'] == 'ready'
                         and previous['state'] == 'SETTLED' and previous.get('decision') == 'improved', 'ITERATION_NOT_READY')
                if previous['ordinal'] >= activity['caps']['rounds']:
                    activity.update(status='stopped', stopReason='round_limit')
                    self._save(conn, activity)
                elif time.time() + activity['roundSeconds'] > activity['deadline']:
                    activity.update(status='stopped', stopReason='deadline')
                    self._save(conn, activity)
                else:
                    try:
                        with conn.begin_nested():
                            self._reserve(conn, owner, activity, previous['ordinal'] + 1, previous_round_id)
                    except HTTPException as error:
                        if error.status_code != 429 or error.detail != 'LOCAL_BUDGET_EXHAUSTED':
                            raise
                        activity.update(status='stopped', stopReason='budget_exhausted')
                        self._save(conn, activity)
            if not replay:
                _require(len(requests) < 16, 'ITERATION_REQUEST_LIMIT', 422)
                requests[request_id] = previous_round_id
                self._save(conn, activity)
        await self._dispatch(owner, activity_id)
        return self.inspect(owner, activity_id)

    async def cancel(self, owner, activity_id):
        return await self._cancel(owner, activity_id, reason='cancelled')

    async def _cancel(self, owner, activity_id, *, reason):
        self._member(owner)
        with self.store.transaction() as conn:
            self.scopes.lock(conn)
            activity = self._activity(conn, owner, activity_id, lock=True)
            self.scopes.cancel(owner, activity['scopeId'])
            round = self._round(conn, activity['currentRoundId'])
            activity.update(cancelRequested=True, status='stopped' if round['state'] == 'SETTLED' else 'canceling',
                            stopReason=reason)
            self._save(conn, activity)
        await self.driver.cancel(owner, deepcopy(round))
        return self.inspect(owner, activity_id)
