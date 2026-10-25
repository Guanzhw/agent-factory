"""Owned two-process neutral v2 fixture; never imported by production startup.

Reuses the existing TCP server helpers and observer/dispatch gates. The worker
installs explicit test checksum bindings into independent core.
"""
import asyncio
from dataclasses import replace
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time

import httpx
from fastapi import HTTPException, Request
from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agno.tools import tool
from sqlalchemy import MetaData, Table, func, inspect, select
from sqlalchemy.engine import make_url

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.remote_handoff import HandoffTarget, TrustedOrigin
from agent_factory.remote_authority import OriginAuthorityTransport
from core_native_fixture import SEEDS, fixture_v2_definitions as demo_v2_definitions
from core_native_fixture import fixture_bindings as default_bindings, fixture_zero_prices as default_zero_prices
from core_native_fixture import build_tools
from controlled_remote_worker import (ORIGIN_OWNER, RECEIVER_OWNER, MANAGER, ORIGIN_REF, TARGET_REF,
    token, install_dispatch_hold, install_origin_observation_hold)
from controlled_remote_server import OwnedServer, loopback_port
from pg_fixture import IsolatedPostgres

APP_ID = 'fixture-neutral-inputs-v2'
BUDGET = {'toolCalls': 3, 'maxDepth': 1, 'maxChildren': 1, 'operationSeconds': 7, 'outputBytes': 65536}
PLAN_BUDGET = {**BUDGET, 'depth': 0}
CONFIG_SCHEMA = {'type': 'object', 'properties': {'label': {'type': 'string', 'maxLength': 60}},
                 'required': ['label'], 'additionalProperties': False}
CONFIG = {'label': 'original immutable v2 configuration'}
INPUT_SCHEMA = {'type': 'object', 'properties': {'payload': {'type': 'string', 'maxLength': 200}},
                'required': ['payload'], 'additionalProperties': False}


class V2Server(OwnedServer):
    def start(self):
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError('Owned v2 server already running')
        project = Path(__file__).resolve().parents[2]
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR') if key in os.environ}
        env.update(FACTORY_REMOTE_PROCESS_CONFIG=str(self.path), AGNO_TELEMETRY='false',
            PYTHONPATH=os.pathsep.join(str(project / name) for name in
                ('platform', 'platform/tests', 'deployment')))
        if self.log is not None:
            self.log.close()
        self.log = (self.directory / (self.configuration['role'] + '-server.log')).open('ab')
        self.process = subprocess.Popen([sys.executable, '-m', 'remote_v2_fixture'], cwd=project, env=env,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        self.starts.append(self.process.pid)
        deadline = time.monotonic() + 25
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise AssertionError('Owned v2 startup failed: ' + self.log_tail())
                try:
                    if client.get(self.url + '/api/health').status_code == 200:
                        return self
                except httpx.HTTPError:
                    pass
                time.sleep(.04)
        raise AssertionError('Owned v2 startup timeout: ' + self.log_tail())


class V2Pair:
    def __init__(self, database_url):
        self.database_url = database_url
        self.directory = tempfile.TemporaryDirectory(prefix='factory-remote-v2-')
        self.path = Path(self.directory.name)
        self.databases = []
        self.origin = self.receiver = None

    def start(self):
        try:
            for _ in range(2):
                self.databases.append(IsolatedPostgres(self.database_url).__enter__())
            ports = [loopback_port(), loopback_port()]
            while ports[0] == ports[1]:
                ports[1] = loopback_port()
            keys = [secrets.token_urlsafe(48), secrets.token_urlsafe(48)]
            common = {'originUrl': f'http://127.0.0.1:{ports[0]}', 'receiverUrl': f'http://127.0.0.1:{ports[1]}',
                      'originJwtKey': keys[0], 'receiverJwtKey': keys[1], 'controlKey': secrets.token_urlsafe(32)}
            for index, role in enumerate(('origin', 'receiver')):
                if role == 'receiver':
                    common['sourceApplication'] = self.origin.facts()['applicationSnapshot']
                server = V2Server({**common, 'role': role, 'dbUrl': self.databases[index].url,
                    'jwtKey': keys[index], 'port': ports[index], 'workspace': str(self.path / role)}, self.path)
                setattr(self, role, server)
                server.start()
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        for server in (self.receiver, self.origin):
            if server is not None:
                server.stop()
        for database in reversed(self.databases):
            database.__exit__(None, None, None)
        self.databases.clear()
        self.directory.cleanup()


class LostReply:
    def __init__(self, app, controls, marker):
        self.app, self.controls, self.marker = app, controls, marker

    async def __call__(self, scope, receive, send):
        phase = self.controls.get('fault')
        if scope['type'] != 'http' or scope['method'] != 'POST' or phase not in {'prepare', 'dispatch'} \
                or not scope['path'].endswith('/' + phase):
            return await self.app(scope, receive, send)
        buffered = []
        async def capture(message):
            buffered.append(message)
        await self.app(scope, receive, capture)
        status = next(message['status'] for message in buffered if message['type'] == 'http.response.start')
        if status in {200, 201, 202}:
            self.marker.write_text(json.dumps({'phase': phase, 'status': status, 'pid': os.getpid()}))
            os._exit(41)
        for message in buffered:
            await send(message)


def main():
    path = Path(os.environ['FACTORY_REMOTE_PROCESS_CONFIG']).resolve()
    config = json.loads(path.read_text())
    url = make_url(config['dbUrl'])
    if url.host not in {'127.0.0.1', 'localhost', '::1'} or not (url.database or '').startswith('af_test_'):
        raise ValueError('Owned v2 fixture requires generated loopback database')
    role = config['role']
    if role not in {'origin', 'receiver'}:
        raise ValueError('Invalid fixture role')
    workspace = Path(config['workspace']).resolve()
    if not workspace.is_relative_to(path.parent):
        raise ValueError('Fixture workspace is outside its owned directory')
    owner = ORIGIN_OWNER if role == 'origin' else RECEIVER_OWNER
    controls = {'fault': None, 'holdWork': False}
    pending, observations = {}, []
    target = HandoffTarget(TARGET_REF, ORIGIN_REF, config['receiverUrl'], {ORIGIN_OWNER: RECEIVER_OWNER},
        lambda _: {'Authorization': 'Bearer ' + token(config['receiverJwtKey'], RECEIVER_OWNER)},
        configuration_revision='neutral-v2-target', supported_application_contracts=(1, 2))
    settings = Settings(db_url=config['dbUrl'], workspace=workspace, jwt_key=config['jwtKey'],
        port=config['port'], max_workers=1, max_user_tasks=12, max_total_tasks=24,
        storage_low_water_bytes=1, usage_pricing=default_zero_prices(), fee_management_enabled=True)
    if role == 'origin':
        settings.handoff_targets = {TARGET_REF: target}
    else:
        authority = OriginAuthorityTransport(base_url=config['originUrl'], origin_ref=ORIGIN_REF,
            target_ref=TARGET_REF, target_revision=target.configuration_revision, target_fingerprint=target.fingerprint,
            receiver_identity_map=target.identity_map,
            credential_provider=lambda _: token(config['originJwtKey'], RECEIVER_OWNER))
        settings.handoff_origins = {ORIGIN_REF: TrustedOrigin(ORIGIN_REF, {ORIGIN_OWNER: RECEIVER_OWNER}, authority,
            tools=frozenset({'checksum'}), capabilities=frozenset({'checksum:read'}),
            supported_application_contracts=(1, 2), v2_budget=BUDGET)}

    def bindings(settings, store, connections):
        registry = default_bindings(settings, store, connections)
        key = ('tool', 'fixture-checksum-v1', '1')
        original = registry._adapters[key]
        def factory(ctx):
            actual_checksum = original.factory(ctx)
            @tool(name='checksum')
            async def checksum(text: str, run_context: RunContext) -> str:
                selected = ctx.plan
                values = {name: selected[name] for name in
                    ('contractVersion', 'inputSchema', 'inputValues', 'budget')}
                values['applicationConfig'] = selected['config']['applicationConfig']
                values.update(taskId=run_context.session_id, runId=run_context.run_id, text=text)
                if text != selected['inputValues']['payload']:
                    raise AssertionError('Native model did not pass the original input text')
                reserved = store.effect_reserve(run_context.run_id, 'neutral-v2-checksum', values)
                if reserved['status'] != 'new':
                    raise ValueError('Original v2 checksum cannot be dispatched again')
                store.event(run_context.run_id, 'v2_adapter_input', 'Controlled adapter consumed original v2 values', values)
                observations.append(values)
                async def work():
                    async with asyncio.timeout(30):
                        while controls['holdWork']:
                            await asyncio.sleep(.02)
                    if store.cancellation_requested(run_context.run_id):
                        result = {'cancelled': True, 'allStopped': True}
                    else:
                        result = json.loads(actual_checksum(text, run_context))
                    store.effect_complete(run_context.run_id, 'neutral-v2-checksum', result)
                    return json.dumps(result)
                task = asyncio.create_task(work())
                pending[run_context.session_id] = task
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
                # Agno cancellation is cooperative. Stop this native wait at
                # the persisted cancellation boundary without canceling the
                # independent operation or manufacturing its stop evidence.
                # asyncio.wait timeouts leave the owned task untouched.
                while not task.done():
                    if await asyncio.to_thread(store.cancellation_requested, run_context.run_id):
                        raise RunCancelledException('CONTROLLED_V2_NATIVE_WAIT_CANCELLED')
                    await asyncio.wait({task}, timeout=.05)
                return await asyncio.shield(task)
            return checksum
        registry._adapters[key] = replace(original, factory=factory)
        return registry

    app = create_app(settings, bindings_factory=bindings, seed_materials=SEEDS,
        demo_definitions=demo_v2_definitions, tool_catalog_factory=build_tools, queue_max_attempts=1)
    state = app.app.state.factory
    store = state['store']
    for subject in (ORIGIN_OWNER, RECEIVER_OWNER, MANAGER):
        if state['auth'].directory.get(subject) is None:
            state['auth'].directory.upsert(subject, name=subject)
    definition = demo_v2_definitions({row['id']: row for row in store.materials(published_only=True)})[0]
    definition['id'] = APP_ID
    definition['modes']['execute'].update(configSchema=CONFIG_SCHEMA, config=CONFIG,
                                         inputSchema=INPUT_SCHEMA, budget=BUDGET)
    draft = (state['applications'].import_snapshot(MANAGER, config['sourceApplication'], 'neutral-v2-app-import')
             if role == 'receiver' else
             state['applications'].create_draft(MANAGER, definition, 'neutral-v2-app-draft'))
    state['applications'].publish(MANAGER, draft['id'], draft['version'], 'neutral-v2-app-publish')
    application_ref = {key: draft[key] for key in ('id', 'version', 'sha256')}
    if role == 'origin':
        install_dispatch_hold(state, controls)
        install_origin_observation_hold(state, controls)

    def authenticated(request):
        if not hmac.compare_digest(request.headers.get('X-Fixture-Control', ''), config['controlKey']):
            raise HTTPException(403, 'Fixture control authentication required')

    @app.app.get('/__fixture/state')
    def facts(request: Request, taskId: str | None = None):
        authenticated(request)
        db = store.native_db
        count = 0
        if inspect(db.db_engine).has_table(db.job_table_name, schema=db.db_schema):
            table = Table(db.job_table_name, MetaData(), schema=db.db_schema, autoload_with=db.db_engine)
            query = select(func.count()).select_from(table)
            if taskId:
                query = query.where(table.c.session_id == taskId)
            with db.db_engine.connect() as conn:
                count = conn.execute(query).scalar()
        task = store.task(taskId, owner) if taskId else None
        native = db.get_job(task['run_id']) if task and task.get('run_id') else None
        return {'applicationRef': application_ref,
            'applicationSnapshot': state['applications'].require_current(application_ref),
            'pid': os.getpid(), 'nativeTickets': count,
            'nativeStatus': native.get('status') if native else None,
            'task': task, 'plan': store.plan(task['plan_id'], owner) if task else None,
            'effects': store.effects(taskId) if task else [], 'events': store.events(taskId) if task else [],
            'adapterInputs': observations,
            'placements': store.sql('SELECT * FROM af_remote_placements') if role == 'origin' else [],
            'handoffs': store.sql('SELECT * FROM af_remote_handoffs') if role == 'receiver' else []}

    @app.app.post('/__fixture/control')
    async def control(request: Request):
        authenticated(request)
        body = await request.json()
        op = body.get('op')
        if op in {'dispatch-hold', 'dispatch-release'} and role == 'origin':
            controls['holdDispatch'] = op == 'dispatch-hold'
        elif op in {'origin-observation-hold', 'origin-observation-release'} and role == 'origin':
            async with state['fixture_origin_observation_lock']:
                controls['holdOriginObservation'] = op == 'origin-observation-hold'
        elif op in {'work-hold', 'work-release'}:
            controls['holdWork'] = op == 'work-hold'
        elif op in {'observer-stop', 'observer-start'}:
            await (state['lifecycle_observer'].stop() if op == 'observer-stop' else state['lifecycle_observer'].start())
        elif op == 'fault' and body.get('fault') in {'prepare', 'dispatch', None}:
            if body.get('fault') == 'dispatch':
                await app.app.state.queue_worker.stop()
            controls['fault'] = body.get('fault')
        else:
            raise HTTPException(422, 'Unsupported v2 fixture control')
        return {'fixtureOnly': True, 'op': op}

    import uvicorn
    uvicorn.run(LostReply(app, controls, path.parent / (role + '-fault.json')),
                host='127.0.0.1', port=settings.port, log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
