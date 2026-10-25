"""Local multi-root commitments; native execution and usage remain their owners.

An allocation holds a full round against its scope, while provider attempts hold
only the allocation/task/user accounts. Closing transfers actual settled usage
once, after original task-tree and effect custody positively ends. No HTTP API
accepts client usage or stop claims.
"""
from __future__ import annotations

import copy
import math
import json
import time

from fastapi import HTTPException
from sqlalchemy import BigInteger, Column, JSON, MetaData, String, Table, select, text

from .runtime_hooks import effect_unresolved, runtime_custody_held
from .store import digest
from .usage_ledger import integer


def _key(value):
    if type(value) is not str or not 1 <= len(value) <= 200 or any(ord(c) < 32 for c in value):
        raise HTTPException(422, 'LOCAL_BUDGET_ID_INVALID')
    return value


def _sha(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise HTTPException(422, 'LOCAL_BUDGET_HASH_INVALID')
    return value


def _caps(value):
    if type(value) is not dict or set(value) != {'rounds', 'toolCalls', 'tokenLimit', 'amountMicros', 'currency'}:
        raise HTTPException(422, 'LOCAL_BUDGET_CAPS_INVALID')
    try:
        integer(value['rounds'], 'rounds', minimum=1)
        integer(value['toolCalls'], 'tools', minimum=1)
        if value['tokenLimit'] is None:
            if value['amountMicros'] is not None or value['currency'] is not None:
                raise ValueError()
        else:
            integer(value['tokenLimit'], 'tokens')
            integer(value['amountMicros'], 'amount')
            if value['currency'] not in {'USD', 'EUR', 'CNY'}:
                raise ValueError()
    except ValueError:
        raise HTTPException(422, 'LOCAL_BUDGET_CAPS_INVALID') from None
    return copy.deepcopy(value)


class LocalBudgetScopes:
    def __init__(self, store, ledger=None):
        self.store, self.ledger = store, ledger
        metadata = MetaData()
        self.scopes = Table('af_local_budget_scopes', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('body', JSON, nullable=False), Column('hash', String, nullable=False),
            Column('state', String, nullable=False), Column('rounds', BigInteger, nullable=False),
            Column('held_tools', BigInteger, nullable=False), Column('settled_tools', BigInteger, nullable=False))
        self.allocations = Table('af_local_budget_allocations', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('scope_id', String, nullable=False), Column('body', JSON, nullable=False),
            Column('hash', String, nullable=False), Column('state', String, nullable=False),
            Column('task_id', String, unique=True), Column('plan_sha', String), Column('binding_hash', String),
            Column('statement', JSON))
        self.requests = Table('af_local_budget_requests', metadata,
            Column('owner_id', String, primary_key=True), Column('request_id', String, primary_key=True),
            Column('allocation_id', String, nullable=False, unique=True), Column('delivery_id', String))
        metadata.create_all(store.engine)

    @staticmethod
    def admission_lock(conn):
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))

    def bind_request(self, conn, owner, allocation_id, request_id, *, delivery_id=None):
        _key(request_id)
        self.admission_lock(conn)
        self.lock(conn)
        allocation = self._allocation(conn, owner, allocation_id)
        previous = self.request_allocation(conn, owner, request_id)
        if previous is not None and previous != allocation_id:
            raise HTTPException(409, 'LOCAL_BUDGET_REQUEST_CONFLICT')
        if previous is not None and delivery_id is not None and self.request_delivery(conn, owner, request_id) != delivery_id:
            raise HTTPException(409, 'LOCAL_BUDGET_REQUEST_CONFLICT')
        other = conn.execute(select(self.requests.c.request_id).where(
            self.requests.c.allocation_id == allocation_id)).scalar_one_or_none()
        if other is not None and other != request_id:
            raise HTTPException(409, 'LOCAL_BUDGET_REQUEST_CONFLICT')
        task = conn.execute(text('SELECT id FROM af_tasks WHERE owner_id=:owner AND request_id=:request'),
            {'owner': owner, 'request': request_id}).scalar_one_or_none()
        if (task is not None and allocation['task_id'] != task
                or task is None and allocation['task_id'] is not None):
            raise HTTPException(409, 'LOCAL_BUDGET_BINDING_CONFLICT')
        if previous is None:
            conn.execute(self.requests.insert().values(owner_id=owner, request_id=request_id,
                allocation_id=allocation_id, delivery_id=delivery_id))

    def request_allocation(self, conn, owner, request_id):
        return conn.execute(select(self.requests.c.allocation_id).where(
            self.requests.c.owner_id == owner, self.requests.c.request_id == request_id)).scalar_one_or_none()

    def request_delivery(self, conn, owner, request_id):
        return conn.execute(select(self.requests.c.delivery_id).where(
            self.requests.c.owner_id == owner, self.requests.c.request_id == request_id)).scalar_one_or_none()

    def lock(self, conn):
        # Same short accounting lock across scopes, attempts and settlement.
        if self.store.engine.dialect.name != 'postgresql':
            raise RuntimeError('Local budget commitments require PostgreSQL')
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_usage_ledger_v1'))"))

    def _scope(self, conn, owner, scope_id):
        row = conn.execute(select(self.scopes).where(self.scopes.c.id == scope_id,
            self.scopes.c.owner_id == owner)).mappings().first()
        if row is None:
            raise HTTPException(404, 'LOCAL_BUDGET_SCOPE_NOT_FOUND')
        if row['hash'] != digest(row['body']) or row['body']['ownerId'] != owner or row['body']['scopeId'] != scope_id:
            raise HTTPException(409, 'LOCAL_BUDGET_SCOPE_INTEGRITY')
        return row

    def _allocation(self, conn, owner, allocation_id):
        row = conn.execute(select(self.allocations).where(self.allocations.c.id == allocation_id,
            self.allocations.c.owner_id == owner)).mappings().first()
        if row is None:
            raise HTTPException(404, 'LOCAL_BUDGET_ALLOCATION_NOT_FOUND')
        body = row['body']
        if (row['hash'] != digest(body) or body['ownerId'] != owner or body['allocationId'] != allocation_id
                or body['scopeId'] != row['scope_id']):
            raise HTTPException(409, 'LOCAL_BUDGET_ALLOCATION_INTEGRITY')
        if row['task_id'] is not None and row['binding_hash'] != digest({
                'allocationSha256': row['hash'], 'taskId': row['task_id'], 'planSha256': row['plan_sha']}):
            raise HTTPException(409, 'LOCAL_BUDGET_BINDING_INTEGRITY')
        return row

    @staticmethod
    def _projection(row):
        return {'allocationId': row['id'], 'scopeId': row['scope_id'], 'state': row['state'],
            'taskId': row['task_id'], 'planSha256': row['plan_sha'], 'caps': row['body']['caps'],
            'statement': row['statement']}

    def _account(self, conn, identity, owner, caps, commitment):
        if self.ledger is None:
            raise HTTPException(409, 'LOCAL_BUDGET_METERING_UNAVAILABLE')
        return self.ledger._account(conn, identity, owner, {'schema': 1, 'scope': 'local-allocation',
            'commitmentSha256': commitment, 'currency': caps['currency'],
            'tokenLimit': caps['tokenLimit'], 'amountMicros': caps['amountMicros']})

    def create_scope(self, owner, scope_id, commitment_sha, caps, deadline):
        _key(owner); _key(scope_id); _sha(commitment_sha)
        caps = _caps(caps)
        if type(deadline) not in {float, int} or not math.isfinite(deadline):
            raise HTTPException(422, 'LOCAL_BUDGET_DEADLINE_INVALID')
        if caps['tokenLimit'] is not None and (self.ledger is None or caps['currency'] != self.ledger.policy.currency):
            raise HTTPException(409, 'LOCAL_BUDGET_METERING_UNAVAILABLE')
        body = {'scopeId': scope_id, 'ownerId': owner, 'commitmentSha256': commitment_sha,
            'caps': caps, 'deadline': deadline}
        with self.store.transaction() as conn:
            self.lock(conn)
            old = conn.execute(select(self.scopes).where(self.scopes.c.id == scope_id)).mappings().first()
            if old:
                if old['body'] != body or old['hash'] != digest(body):
                    raise HTTPException(409, 'LOCAL_BUDGET_SCOPE_CONFLICT')
            else:
                if deadline <= time.time():
                    raise HTTPException(409, 'LOCAL_BUDGET_EXPIRED')
                conn.execute(self.scopes.insert().values(id=scope_id, owner_id=owner, body=body,
                    hash=digest(body), state='ACTIVE', rounds=0, held_tools=0, settled_tools=0))
                if caps['tokenLimit'] is not None:
                    self._account(conn, 'local-scope:' + scope_id, owner, caps, digest(body))
        return self.inspect(owner, scope_id)

    def allocate(self, conn, owner, scope_id, allocation_id, intent_sha, caps):
        self.lock(conn)
        _key(allocation_id); _sha(intent_sha)
        caps = _caps(caps)
        if caps['rounds'] != 1:
            raise HTTPException(422, 'LOCAL_BUDGET_ONE_ROUND_REQUIRED')
        scope = self._scope(conn, owner, scope_id)
        body = {'allocationId': allocation_id, 'scopeId': scope_id, 'ownerId': owner,
            'scopeSha256': scope['hash'], 'intentSha256': intent_sha, 'caps': caps}
        old = conn.execute(select(self.allocations).where(self.allocations.c.id == allocation_id)).mappings().first()
        if old:
            if old['body'] != body or old['hash'] != digest(body):
                raise HTTPException(409, 'LOCAL_BUDGET_ALLOCATION_CONFLICT')
            return self._projection(self._allocation(conn, owner, allocation_id))
        total = scope['body']['caps']
        if scope['state'] != 'ACTIVE' or time.time() >= scope['body']['deadline']:
            raise HTTPException(409, 'LOCAL_BUDGET_CLOSED_OR_EXPIRED')
        if (scope['rounds'] >= total['rounds'] or scope['held_tools'] + scope['settled_tools'] + caps['toolCalls'] > total['toolCalls']):
            raise HTTPException(429, 'LOCAL_BUDGET_EXHAUSTED')
        if (caps['tokenLimit'] is None) != (total['tokenLimit'] is None) or caps['currency'] != total['currency']:
            raise HTTPException(409, 'LOCAL_BUDGET_METERING_MISMATCH')
        if caps['tokenLimit'] is not None:
            if self.ledger is None:
                raise HTTPException(409, 'LOCAL_BUDGET_METERING_UNAVAILABLE')
            account = self._account(conn, 'local-scope:' + scope_id, owner, total, scope['hash'])
            self.ledger._hold(conn, [account], caps['tokenLimit'], caps['amountMicros'])
            self._account(conn, 'local-round:' + allocation_id, owner, caps, digest(body))
        conn.execute(self.allocations.insert().values(id=allocation_id, owner_id=owner, scope_id=scope_id,
            body=body, hash=digest(body), state='ALLOCATED'))
        conn.execute(self.scopes.update().where(self.scopes.c.id == scope_id).values(
            rounds=self.scopes.c.rounds + 1, held_tools=self.scopes.c.held_tools + caps['toolCalls']))
        return self._projection(self._allocation(conn, owner, allocation_id))

    def bind_root(self, conn, owner, allocation_id, task_id, plan_sha):
        self.lock(conn); _sha(plan_sha)
        row = self._allocation(conn, owner, allocation_id)
        if row['task_id'] is not None:
            if (row['task_id'], row['plan_sha']) != (task_id, plan_sha):
                raise HTTPException(409, 'LOCAL_BUDGET_BINDING_CONFLICT')
            return self._projection(row)
        scope = self._scope(conn, owner, row['scope_id'])
        if scope['state'] != 'ACTIVE' or time.time() >= scope['body']['deadline']:
            raise HTTPException(409, 'LOCAL_BUDGET_CLOSED_OR_EXPIRED')
        task = self.store.task(task_id, owner)
        plan = self.store.plan(task['plan_id'], owner)
        if (task['admission'] != 'reserved' or task['run_id'] is not None or plan.get('delegation')
                or plan.get('remoteHandoff') or digest(plan) != plan_sha):
            raise HTTPException(409, 'LOCAL_BUDGET_ORIGINAL_ROOT_REQUIRED')
        if row['body']['caps']['tokenLimit'] is not None:
            from .billing_mode import ledger_for_plan
            if ledger_for_plan(self.store, plan) is not self.ledger:
                raise HTTPException(409, 'LOCAL_BUDGET_METERING_UNAVAILABLE')
        binding = digest({'allocationSha256': row['hash'], 'taskId': task_id, 'planSha256': plan_sha})
        conn.execute(self.allocations.update().where(self.allocations.c.id == allocation_id).values(
            task_id=task_id, plan_sha=plan_sha, binding_hash=binding, state='BOUND'))
        return self._projection(self._allocation(conn, owner, allocation_id))

    def _root_allocation(self, conn, owner, root_id):
        identity = conn.execute(select(self.allocations.c.id).where(self.allocations.c.task_id == root_id,
            self.allocations.c.owner_id == owner)).scalar_one_or_none()
        if identity is None:
            return None
        row = self._allocation(conn, owner, identity)
        task = self.store.task(root_id, owner)
        if digest(self.store.plan(task['plan_id'], owner)) != row['plan_sha']:
            raise HTTPException(409, 'LOCAL_BUDGET_PLAN_CHANGED')
        scope = self._scope(conn, owner, row['scope_id'])
        if row['state'] != 'BOUND' or scope['state'] != 'ACTIVE' or time.time() >= scope['body']['deadline']:
            raise HTTPException(409, 'LOCAL_BUDGET_CLOSED_OR_EXPIRED')
        return row

    def attempt_account(self, conn, owner, root_id):
        row = self._root_allocation(conn, owner, root_id)
        if row is None:
            return None
        if row['body']['caps']['tokenLimit'] is None:
            return None
        return self._account(conn, 'local-round:' + row['id'], owner, row['body']['caps'], row['hash'])

    def check_tool_capacity(self, conn, owner, root_id):
        self.lock(conn)
        row = self._root_allocation(conn, owner, root_id)
        if row is None:
            return
        used = self.store.sql('SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE root_id=:root', root=root_id)[0]['n']
        if used >= row['body']['caps']['toolCalls']:
            raise HTTPException(429, 'LOCAL_BUDGET_TOOL_CALLS_EXHAUSTED')

    def require_current(self, owner, plan, context=None, tool=None):
        if context is None:
            return
        task = self.store.task(context.session_id, owner)
        delegation = getattr(self.store, 'delegation', None)
        root = delegation._ancestry(task)[0] if delegation else task['id']
        with self.store.transaction() as conn:
            self._root_allocation(conn, owner, root)

    def cancel(self, owner, scope_id):
        with self.store.transaction() as conn:
            self.lock(conn); self._scope(conn, owner, scope_id)
            conn.execute(self.scopes.update().where(self.scopes.c.id == scope_id).values(state='CANCELLED'))
        return self.inspect(owner, scope_id)

    def settle(self, owner, allocation_id):
        with self.store.transaction() as conn:
            self.lock(conn)
            row = self._allocation(conn, owner, allocation_id)
            if row['state'] == 'SETTLED':
                return copy.deepcopy(row['statement'])
            held = {'state': 'HELD', 'allocationId': allocation_id}
            if row['task_id'] is None:
                return held
            task = self.store.task(row['task_id'], owner)
            if digest(self.store.plan(task['plan_id'], owner)) != row['plan_sha']:
                raise HTTPException(409, 'LOCAL_BUDGET_PLAN_CHANGED')
            delegation = getattr(self.store, 'delegation', None)
            links = delegation._descendants(task['id']) if delegation else []
            if any(not link['child_id'] for link in links):
                return held
            tasks = [task, *(self.store.task(link['child_id'], owner) for link in links)]
            if any(not current['terminal'] or current['admission'] not in {'accepted', 'rejected'}
                    or runtime_custody_held(self.store, current['id'])
                    or any(effect_unresolved(effect, self.store) for effect in self.store.effects(current['id'])) for current in tasks):
                return held
            # Accounting can be disabled after an attempt was admitted. Old
            # UNKNOWN task/user usage still prevents releasing an unmetered scope.
            if self.store.sql("SELECT to_regclass('af_usage_attempts') AS existing")[0]['existing'] is not None:
                pending = self.store.sql("SELECT id FROM af_usage_attempts WHERE owner_id=:owner AND task_id=ANY(:ids) AND state!='SETTLED'",
                    owner=owner, ids=[current['id'] for current in tasks])
                if pending:
                    return held
            tools = self.store.sql('SELECT COUNT(*) AS n FROM af_delegation_tool_calls WHERE root_id=:root', root=task['id'])[0]['n']
            scope = self._scope(conn, owner, row['scope_id'])
            caps = row['body']['caps']
            tokens = amount = None
            if caps['tokenLimit'] is not None:
                if self.ledger is None:
                    raise HTTPException(409, 'LOCAL_BUDGET_METERING_UNAVAILABLE')
                account = self._account(conn, 'local-round:' + allocation_id, owner, caps, row['hash'])
                unresolved = self.store.sql("SELECT id FROM af_usage_attempts WHERE owner_id=:owner AND state!='SETTLED' AND CAST(body->'accountIds' AS JSONB) @> CAST(:ids AS JSONB)",
                    owner=owner, ids=json.dumps(['local-round:' + allocation_id]))
                if unresolved or account['held_tokens'] or account['held_amount']:
                    return held
                tokens, amount = account['settled_tokens'], account['settled_amount']
                parent = self._account(conn, 'local-scope:' + row['scope_id'], owner, scope['body']['caps'], scope['hash'])
                if parent['held_tokens'] < caps['tokenLimit'] or parent['held_amount'] < caps['amountMicros']:
                    raise HTTPException(409, 'LOCAL_BUDGET_HOLD_INTEGRITY')
                table = self.ledger.accounts
                conn.execute(table.update().where(table.c.id == parent['id']).values(
                    held_tokens=table.c.held_tokens - caps['tokenLimit'], held_amount=table.c.held_amount - caps['amountMicros'],
                    settled_tokens=table.c.settled_tokens + tokens, settled_amount=table.c.settled_amount + amount))
            if scope['held_tools'] < caps['toolCalls']:
                raise HTTPException(409, 'LOCAL_BUDGET_HOLD_INTEGRITY')
            conn.execute(self.scopes.update().where(self.scopes.c.id == row['scope_id']).values(
                held_tools=self.scopes.c.held_tools - caps['toolCalls'], settled_tools=self.scopes.c.settled_tools + tools))
            statement = {'state': 'SETTLED', 'allocationId': allocation_id, 'toolCalls': tools,
                'settledTokens': tokens, 'settledAmountMicros': amount}
            conn.execute(self.allocations.update().where(self.allocations.c.id == allocation_id).values(state='SETTLED', statement=statement))
            return statement

    def inspect(self, owner, scope_id):
        with self.store.transaction(read_only=True) as conn:
            scope = self._scope(conn, owner, scope_id)
            allocations = [self._projection(self._allocation(conn, owner, row)) for row in conn.execute(
                select(self.allocations.c.id).where(self.allocations.c.scope_id == scope_id)).scalars()]
            metered = scope['body']['caps']['tokenLimit'] is not None
            usage = None
            if metered:
                if self.ledger is None:
                    raise HTTPException(409, 'LOCAL_BUDGET_METERING_UNAVAILABLE')
                account = conn.execute(select(self.ledger.accounts).where(self.ledger.accounts.c.id == 'local-scope:' + scope_id)).mappings().one()
                if account['hash'] != digest(account['body']):
                    raise HTTPException(409, 'LOCAL_BUDGET_ACCOUNT_INTEGRITY')
                usage = {key: account[key] for key in ('held_tokens', 'held_amount', 'settled_tokens', 'settled_amount')}
            return {**scope['body'], 'state': scope['state'], 'allocatedRounds': scope['rounds'],
                'heldToolCalls': scope['held_tools'], 'settledToolCalls': scope['settled_tools'],
                'usage': usage, 'metering': 'enforced' if metered else 'unavailable', 'allocations': allocations}
