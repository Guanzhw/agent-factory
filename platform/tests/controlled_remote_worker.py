"""Explicit acceptance server: controlled adapters, real Factory/Agno/TCP/PG.

Loaded ONLY by test_governed_remote_process_postgres.py in owned child processes.
The fixture control router is never imported by production application startup.
All keys, users, registrations, workspaces and databases are generated test data.
"""
from __future__ import annotations

import copy
import asyncio
from dataclasses import replace
import hmac
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from agno.db.postgres import PostgresDb
from agno.metrics import MessageMetrics
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import MetaData, Table, func, inspect, select
from sqlalchemy.engine import make_url

from agent_factory.auth import AuthService
from fixture_settings import Settings
from agent_factory.connections import ConnectionService, TrustedConnectionBinding
from core_native_fixture import FixtureModel as DemoModel
from agent_factory.execution_bindings import AdapterRegistration, KnowledgeContext
from core_native_fixture import create_fixture_app as create_app
from agent_factory.remote_authority import OriginAuthorityTransport
from agent_factory.remote_bindings import TrustedRemoteBindingMapping
from agent_factory.remote_handoff import HandoffTarget, TrustedOrigin
from agent_factory.store import Store
from agent_factory.usage_ledger import PricingRevision, UsagePolicy, native_response_usage

ORIGIN_OWNER = "fixture-origin-user"
RECEIVER_OWNER = "fixture-receiver-user"
OTHER_OWNER = "fixture-unrelated-user"
MANAGER = "fixture-manager"
REVIEWER = "fixture-distinct-reviewer"
ORIGIN_REF = "fixture-tcp-origin"
TARGET_REF = "fixture-tcp-receiver"
APP_ID = "fixture-governed-checksum"
MODEL_SOURCE = "fixture-origin-model-v1"
MODEL_RECEIVER = "fixture-receiver-model-v1"
CONNECTION_REGISTRATION = "fixture-owner-model"
MAPPING_REF = "fixture-exact-model-mapping"
CONNECTION_FIELDS = ("ref", "version", "fingerprint", "kind", "revision", "capabilities", "taskId")


def token(key, subject):
    import jwt
    at = int(time.time())
    return jwt.encode({"sub": subject, "aud": "agent-factory", "iat": at, "exp": at + 3600}, key, algorithm="HS256")


def pin(value):
    return {name: value[name] for name in ("id", "version", "sha256")}


class ControlledProvider:
    def __init__(self, label):
        self.label = label
        self.created = []

    def __repr__(self):
        return "<opaque-controlled-fixture-provider>"






class ControlledModel(DemoModel):
    """Native model API; deterministic fixture output, no provider request."""
    async def ainvoke(self, messages, **kwargs):
        return self._response(messages)


def controlled_request_guard(model, arguments, keywords, commitment):
    # Only this reviewed deterministic class, with no underlying SDK/network,
    # can satisfy these synthetic attempt caps and no-hidden-retry contract.
    if not isinstance(model, ControlledMeteredModel) or commitment["perAttemptInputTokens"] != 8 or commitment["perAttemptOutputTokens"] != 4:
        raise PermissionError("Explicit fixture request cap differs")


class ControlledMeteredModel(ControlledModel):
    id: str = "factory-controlled-metered-v1"
    provider: str = "controlled-fixture"

    def __init__(self, controls):
        super().__init__(id="factory-controlled-metered-v1", provider="controlled-fixture")
        self.fixture_controls = controls

    async def ainvoke(self, messages, **kwargs):
        value = self._response(messages)
        if not self.fixture_controls.get("unknownUsage"):
            value.response_usage = MessageMetrics(input_tokens=3, output_tokens=2, total_tokens=5)
        return value


def provision_owned_subjects(settings):
    native = PostgresDb(db_url=settings.db_url, id="owned-process-bootstrap")
    auth = AuthService(settings, native)
    try:
        local_owner = ORIGIN_OWNER if settings.fixture_role == "origin" else RECEIVER_OWNER
        for subject in (ORIGIN_OWNER, RECEIVER_OWNER, OTHER_OWNER, MANAGER, REVIEWER):
            if auth.directory.get(subject) is None:
                auth.directory.upsert(subject, name=subject)
        store = Store(settings.db_url, settings)
        try:
            service = ConnectionService(store, auth, settings.trusted_connections)
            bound = service.bind(local_owner, CONNECTION_REGISTRATION, "fixture-bind-before-main", capabilities=["checksum:read"])
            return {name: bound[name] for name in CONNECTION_FIELDS}
        finally:
            store.engine.dispose()
    finally:
        native.db_engine.dispose()


def material_definition(identifier, kind, content, adapter=None, config=None, permissions=()):
    value = {"id": identifier, "kind": kind, "name": identifier, "content": content,
             "description": "Original explicit controlled process acceptance fixture.", "license": "MIT",
             "compatibility": ["agno:3.1.0"], "permissions": list(permissions), "dependencies": [],
             "provenance": {"kind": "original", "notice": "Controlled adapter data; does not establish live provider compatibility."}}
    if adapter:
        value["runtimeBinding"] = {"adapterId": adapter, "revision": "1", "config": config or {}}
    return value


def publish_fixture(state, source_application=None):
    governance, applications = state["material_governance"], state["applications"]
    definitions = [
        material_definition("fixture-selected-model", "model", "Explicit operator-installed controlled model.", MODEL_SOURCE, {"connectionName": "provider"}),
        material_definition("fixture-selected-environment", "environment", "Fixed bounded local environment.", "fixture-environment-v1"),
        material_definition("fixture-selected-knowledge", "knowledge", "Original public controlled checksum knowledge.", "fixture-controlled-knowledge-v1"),
        material_definition("fixture-selected-skill", "skill", "Calculate only the approved checksum and report artifact evidence."),
        material_definition("fixture-selected-prompt", "prompt", "Follow the reviewed task and current authority."),
        material_definition("fixture-selected-checksum", "tool", "checksum", "fixture-checksum-v1", permissions=["checksum:read"]),
        material_definition("fixture-selected-question", "tool", "ask_scope", "fixture-ask-scope-v1", permissions=["question:ask"]),
    ]
    materials = {}
    for definition in definitions:
        mid = definition["id"]
        created = governance.create_draft(MANAGER, definition, "fixture-draft-" + mid)
        governance.publish(MANAGER, mid, created["version"], "fixture-publish-" + mid)
        materials[mid] = created
    common = [pin(materials["fixture-selected-" + suffix]) for suffix in ("model", "environment", "knowledge", "skill", "prompt", "checksum")]
    budget = {"toolCalls": 8, "maxDepth": 2, "maxChildren": 4, "experimentSeconds": 8, "outputBytes": 65536}
    requirement = [{"name": "provider", "kind": "model", "requiredCapabilities": ["checksum:read"], "required": True}]
    direct = {"materialRefs": common, "capabilities": ["checksum:read"], "toolOrder": ["checksum"], "budget": budget, "connectionRequirements": requirement}
    paused = {**direct, "materialRefs": [*common, pin(materials["fixture-selected-question"])],
              "capabilities": ["checksum:read", "question:ask"], "toolOrder": ["ask_scope", "checksum"], "config": {"askScopeBelowLength": 2000}}
    modes = {"direct": direct, "paused": paused}
    if source_application is None:
        application = applications.create_draft(MANAGER, {"id": APP_ID, "name": "Governed controlled checksum",
            "description": "Actual non-demo policy path with explicitly controlled provider.", "defaultMode": "direct",
            "modes": modes}, "fixture-application-draft")
    else:
        # The receiver installs and publishes its exact imported snapshot.
        application = applications.import_snapshot(MANAGER, source_application, "fixture-application-import")
    applications.publish(MANAGER, application["id"], application["version"], "fixture-application-publish")
    return pin(application), materials, application


def install_dispatch_hold(state, controls):
    """Fixture-only protocol staging; never writes production approval state."""
    client = state['handoff_client']
    dispatch = client.dispatch
    async def staged_dispatch(owner, task_id):
        if controls.get('holdDispatch'):
            return await client.receipt(owner, task_id)
        return await dispatch(owner, task_id)
    client.dispatch = staged_dispatch


def install_origin_observation_hold(state, controls):
    """Gate only background origin reconciliation; direct actions remain real."""
    client = state['handoff_client']
    observe = client.observe_pending
    lock = asyncio.Lock()
    state['fixture_origin_observation_lock'] = lock

    async def staged_observe(*, limit=50):
        async with lock:
            if controls.get('holdOriginObservation'):
                return {'checked': 0, 'reconciled': 0, 'errors': []}
            return await observe(limit=limit)

    client.observe_pending = staged_observe


class FixtureSessionBridge:
    """Managed browser sessions ONLY for this authenticated fixture server."""
    def __init__(self, app, configuration):
        self.app, self.configuration = app, configuration

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = list(scope.get("headers", []))
            if not any(name.lower() == b"authorization" for name, _ in headers):
                issued = None
                if scope["path"] == "/__fixture/session":
                    key = next((value.decode("latin-1") for name, value in headers if name.lower() == b"x-fixture-control"), "")
                    if hmac.compare_digest(key, self.configuration["controlKey"]):
                        issued = token(self.configuration["jwtKey"], MANAGER)
                else:
                    cookies = SimpleCookie()
                    for name, value in headers:
                        if name.lower() == b"cookie":
                            cookies.load(value.decode("latin-1"))
                    if "__fixture_native_session" in cookies:
                        issued = cookies["__fixture_native_session"].value
                    origins = [value.decode("latin-1") for name, value in headers if name.lower() == b"origin"]
                    host = next((value.decode("latin-1") for name, value in headers if name.lower() == b"host"), "")
                    if issued and scope.get("method") not in {"GET", "HEAD", "OPTIONS"} and origins and (len(origins) != 1 or urlsplit(origins[0]).netloc != host):
                        return await JSONResponse({"message": "Cross-origin fixture session denied"}, status_code=403)(scope, receive, send)
                if issued and issued.isascii() and "\r" not in issued and "\n" not in issued:
                    scope = {**scope, "headers": [*headers, (b"authorization", ("Bearer " + issued).encode("ascii"))]}
        await self.app(scope, receive, send)


class DropDispatchAcknowledgement:
    """Fixture-only post-commit crash, after the actual native dispatch reply."""
    def __init__(self, app, controls, marker):
        self.app, self.controls, self.marker = app, controls, marker

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].endswith("/dispatch")
                or self.controls.get("fault") not in {"exit_after_dispatch", "exit_after_queued_dispatch"}):
            diagnostic = {"status": 200, "body": bytearray()}
            async def traced(message):
                if message["type"] == "http.response.start":
                    diagnostic["status"] = message["status"]
                if message["type"] == "http.response.body" and diagnostic["status"] >= 400 and scope.get("path", "").startswith("/api/factory/remote-"):
                    diagnostic["body"].extend(message.get("body", b"")[:8192])
                    if not message.get("more_body"):
                        print("CONTROLLED_FIXTURE_DENIAL " + str(diagnostic["status"]) + " " + scope["path"] + " " + diagnostic["body"].decode("utf-8", "replace"), flush=True)
                await send(message)
            return await self.app(scope, receive, traced)
        buffered = []
        async def capture(message):
            buffered.append(message)
        await self.app(scope, receive, capture)
        status = next(message["status"] for message in buffered if message["type"] == "http.response.start")
        if status == 202:
            self.marker.write_text(json.dumps({"pid": os.getpid(), "phase": "after-native-dispatch-before-http-ack", "status": status, "workerStopped": self.controls.get("fault") == "exit_after_queued_dispatch"}), encoding="utf-8")
            os._exit(41)
        for message in buffered:
            await send(message)


def main():
    config_path = Path(os.environ["FACTORY_REMOTE_PROCESS_CONFIG"]).resolve()
    configuration = json.loads(config_path.read_text(encoding="utf-8"))
    directory = config_path.parent
    url = make_url(configuration["dbUrl"])
    if url.host not in {"127.0.0.1", "localhost", "::1"} or not re.fullmatch(r"af_test_[a-f0-9]{32}", url.database or ""):
        raise ValueError("Fixture server refuses a database outside its generated loopback scope")
    role = configuration["role"]
    if role not in {"origin", "receiver"}:
        raise ValueError("Unsupported fixture role")
    workspace = Path(configuration["workspace"]).resolve()
    if not workspace.is_relative_to(directory):
        raise ValueError("Fixture workspace must remain below its owned configuration directory")
    # Explicit historical accounting fixture; installed providers are controlled.
    settings = Settings(fee_management_enabled=True, platform_paid_models_enabled=True,
        db_url=configuration["dbUrl"], jwt_key=configuration["jwtKey"], workspace=workspace,
        port=configuration["port"], max_workers=1, max_user_tasks=12, max_total_tasks=24)
    settings.fixture_role = role
    if configuration.get("registeredTools"):
        settings.runtime_tool_contract = "legacy-v1"
        settings.policy_revision = "fixture-registered-plan-policy-v1"
        settings.material_policy_revision = "fixture-registered-material-policy-v1"
    owner = ORIGIN_OWNER if role == "origin" else RECEIVER_OWNER
    adapter = MODEL_SOURCE if role == "origin" else MODEL_RECEIVER
    provider = ControlledProvider(role + "-opaque-handle-marker")
    trusted = TrustedConnectionBinding(owner, "model", adapter, frozenset({"checksum:read"}), "fixture-provider-v1",
        available=True, opaque_handle=provider, handle_ref=role + "-stable-owned-provider")
    settings.trusted_connections = {CONNECTION_REGISTRATION: trusted}
    connection_pin = provision_owned_subjects(settings)
    controls = {"fault": None, "unknownUsage": False}
    if configuration.get("usageProfile") == "metered":
        settings.usage_policy = UsagePolicy("fixture-metered-policy-v1", task_token_limit=40, task_amount_micros=64,
            user_token_limit=400, user_amount_micros=640)
        settings.usage_pricing = tuple(PricingRevision(identifier, "1", "controlled-fixture", "factory-controlled-metered-v1",
            "fixture-tariff-v1", input_micros_per_million=1_000_000, output_micros_per_million=2_000_000,
            per_attempt_input_tokens=8, per_attempt_output_tokens=4, usage_reader=native_response_usage,
            request_guard=controlled_request_guard) for identifier in (MODEL_SOURCE, MODEL_RECEIVER))
    else:
        # Existing remote fixtures explicitly install this exact no-provider
        # native class; missing/unregistered adapters are never free by default.
        settings.usage_pricing = tuple(PricingRevision(identifier, "1", "controlled-fixture", identifier,
            "fixture-zero-local-v1", local_model_type=ControlledModel) for identifier in (MODEL_SOURCE, MODEL_RECEIVER))
    def model(context):
        if context.connection is not provider or context.run_context.user_id != owner:
            raise PermissionError("Controlled provider handle is outside its exact selected owner")
        provider.created.append({"ownerId": owner, "taskId": context.run_context.session_id, "runId": context.run_context.run_id})
        context.store.event(context.run_context.run_id, "controlled_provider_selected", "Explicit test provider; no network request",
            {"fixtureOnly": True, "ownerId": owner, "adapterId": adapter, "pid": os.getpid(), "workspace": str(workspace)})
        return ControlledMeteredModel(controls) if configuration.get("usageProfile") == "metered" else ControlledModel(id=adapter)
    settings.runtime_adapters = [AdapterRegistration("model", adapter, "1", model, connection_kind="model", required_capabilities=("checksum:read",)),
        AdapterRegistration("knowledge", "fixture-controlled-knowledge-v1", "1", lambda context: KnowledgeContext("Original scoped fixture checksum context.", {"evidenceKind": "controlled-adapter"}))]
    target = HandoffTarget(TARGET_REF, ORIGIN_REF, configuration["receiverUrl"], {ORIGIN_OWNER: RECEIVER_OWNER},
        lambda source_owner: {"Authorization": "Bearer " + token(configuration["receiverJwtKey"], RECEIVER_OWNER)}, configuration_revision="fixture-target-v1")
    initial_mapping = None
    if role == "origin":
        settings.handoff_targets = {TARGET_REF: target}
    else:
        transport = OriginAuthorityTransport(base_url=configuration["originUrl"], origin_ref=ORIGIN_REF, target_ref=TARGET_REF,
            target_revision=target.configuration_revision, target_fingerprint=target.fingerprint,
            receiver_identity_map=target.identity_map,
            credential_provider=lambda source_owner: token(configuration["originJwtKey"], RECEIVER_OWNER))
        origin_options = {"tools": frozenset({"ask_scope", "checksum"}),
            "capabilities": frozenset({"question:ask", "checksum:read"}),
            "configuration_revision": "fixture-registered-origin-v1", "tool_contract": "legacy-v1"} if configuration.get("registeredTools") else {}
        settings.handoff_origins = {ORIGIN_REF: TrustedOrigin(ORIGIN_REF, {ORIGIN_OWNER: RECEIVER_OWNER}, transport, **origin_options)}
        source = configuration["sourceSpec"]
        effective = {**copy.deepcopy(source), "adapterId": MODEL_RECEIVER, "connection": connection_pin}
        initial_mapping = TrustedRemoteBindingMapping(MAPPING_REF, "fixture-mapping-v1", ORIGIN_REF, ORIGIN_OWNER, RECEIVER_OWNER,
            "model", source, effective)
        settings.remote_binding_mappings = {MAPPING_REF: initial_mapping}
    application = create_app(settings)
    state = application.app.state.factory
    if role == 'origin':
        install_dispatch_hold(state, controls)
        install_origin_observation_hold(state, controls)
    application_ref, materials, snapshot = publish_fixture(state, configuration.get("sourceApplication"))
    marker = directory / (role + "-fault.json")
    if role == "origin":
        client = state["handoff_client"]
        request_remote = client._request

        async def interrupted_request(source_owner, target, method, path, **kwargs):
            if controls.get("fault") == "exit_before_remote_dispatch" and method == "POST" and path.endswith("/dispatch"):
                grant = kwargs.get("json", {}).get("usageGrant")
                row = client._row(source_owner, grant["originTaskId"])
                if row["state"] != "DISPATCH_UNKNOWN" or row["body"].get("usageGrant") != grant:
                    raise RuntimeError("Fault injection requires a positively committed original allocation")
                marker.write_text(json.dumps({"pid": os.getpid(), "phase": "after-origin-allocation-before-transport",
                    "grantId": grant["id"], "grantSha256": grant["sha256"]}), encoding="utf-8")
                os._exit(42)
            return await request_remote(source_owner, target, method, path, **kwargs)

        client._request = interrupted_request

    def authenticated(request):
        if not hmac.compare_digest(request.headers.get("X-Fixture-Control", ""), configuration["controlKey"]):
            raise HTTPException(403, "Explicit test fixture authentication required")

    @application.app.post("/__fixture/session")
    async def session(request: Request):
        authenticated(request)
        body = await request.json()
        if set(body) != {"actor"} or body["actor"] not in {ORIGIN_OWNER, RECEIVER_OWNER, OTHER_OWNER, MANAGER, REVIEWER}:
            raise HTTPException(422, "Only explicit generated fixture subjects are available")
        # Existing managed subject/current policy only; no role grant occurs.
        issued = state["auth"]._issue_native_token(body["actor"], lifetime_seconds=3600)
        response = JSONResponse({"fixtureOnly": True, "actor": body["actor"]})
        response.set_cookie("__fixture_native_session", issued, httponly=True, samesite="strict", max_age=3600)
        return response

    @application.app.get("/__fixture/state")
    def facts(request: Request, taskId: str | None = None):
        authenticated(request)
        store, db = state["store"], state["store"].native_db
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
        return {"fixtureOnly": True, "pid": os.getpid(), "mode": "production-policy-controlled-provider", "demo": False,
            "workspace": str(workspace), "applicationRef": application_ref, "applicationSnapshot": snapshot, "connection": connection_pin,
            "materials": {key: pin(value) for key, value in materials.items()}, "providerCreated": list(provider.created),
            "nativeTickets": count, "tasks": store.tasks(owner),
            'nativeStatus': native.get('status') if native else None,
            'events': store.events(taskId) if taskId else [], 'artifacts': store.artifacts(taskId) if taskId else [],
            "plan": store.plan(store.task(taskId, owner)["plan_id"], owner) if taskId else None,
            "placements": store.sql("SELECT * FROM af_remote_placements") if role == "origin" else [],
            "handoffs": store.sql("SELECT * FROM af_remote_handoffs") if role == "receiver" else [],
            "usageLedger": store.usage_ledger.inspect(owner, taskId) if taskId else None,
            "usageGrants": store.sql("SELECT * FROM af_usage_remote_grants"),
            "usageAccounts": store.sql("SELECT * FROM af_usage_accounts"),
            "bindingProofs": store.sql("SELECT * FROM af_remote_binding_proofs WHERE receiver_owner=:owner", owner=owner) if role == "receiver" else []}

    @application.app.post("/__fixture/control")
    async def control(request: Request):
        authenticated(request)
        body = await request.json()
        if set(body) - {"op", "fault"}:
            raise HTTPException(422, "Unsupported fixture controls")
        op = body.get("op")
        if op == "fault":
            if body.get("fault") not in {None, "exit_after_dispatch", "exit_after_queued_dispatch", "exit_before_remote_dispatch"}:
                raise HTTPException(422, "Unsupported fixture fault")
            if body.get("fault") == "exit_after_queued_dispatch":
                # Fix the crash boundary before any provider attempt. Durable
                # native admission remains live; restart starts the real worker.
                await application.app.state.queue_worker.stop()
            controls["fault"] = body.get("fault")
        elif op in {"usage-unknown", "usage-known"}:
            controls["unknownUsage"] = op == "usage-unknown"
        elif op in {"usage-price-change", "usage-model-change", "usage-price-restore"}:
            ledger = state["store"].usage_ledger
            ledger.by_adapter = {(price.adapter_id, price.adapter_revision): price if op == "usage-price-restore" or price.adapter_id not in {MODEL_SOURCE, MODEL_RECEIVER} else
                replace(price, revision="fixture-tariff-v2", input_micros_per_million=2_000_000) if op == "usage-price-change" else
                replace(price, model="changed-controlled-model-v2") for price in settings.usage_pricing}
        elif op in {"role-revoke", "role-restore"}:
            state['auth'].directory.set_disabled(owner, op == 'role-revoke')
        elif op in {'dispatch-hold', 'dispatch-release'} and role == 'origin':
            controls['holdDispatch'] = op == 'dispatch-hold'
        elif op in {'origin-observation-hold', 'origin-observation-release'} and role == 'origin':
            # Returning from hold acknowledges any earlier observation drained.
            # Receiver observation, native workers and explicit reconcile run normally.
            async with state['fixture_origin_observation_lock']:
                controls['holdOriginObservation'] = op == 'origin-observation-hold'
        elif op in {'receiver-observer-stop', 'receiver-observer-start'} and role == 'receiver':
            # Isolate dispatch-boundary tests from legitimate autonomous cleanup.
            # This drains only lifecycle observation, never the native worker.
            observer = state['lifecycle_observer']
            if op == 'receiver-observer-stop':
                await observer.stop()
            else:
                await observer.start()
        elif op in {"connection-unavailable", "connection-restore", "connection-rotate"}:
            state["connections"].trusted_bindings[CONNECTION_REGISTRATION] = trusted if op == "connection-restore" else replace(trusted,
                available=False, opaque_handle=None) if op == "connection-unavailable" else replace(trusted, revision="fixture-provider-v2")
        elif op in {"mapping-remove", "mapping-restore", "mapping-rotate", "mapping-wrong-owner"} and role == "receiver":
            mappings = state["store"].remote_bindings.mappings
            if op == "mapping-remove":
                mappings.clear()
            else:
                mappings[MAPPING_REF] = initial_mapping if op == "mapping-restore" else replace(initial_mapping,
                    revision="fixture-mapping-v2") if op == "mapping-rotate" else replace(initial_mapping, receiver_owner=OTHER_OWNER)
        else:
            raise HTTPException(422, "Unsupported fixture operation")
        return {"fixtureOnly": True, "op": op}

    import uvicorn
    uvicorn.run(DropDispatchAcknowledgement(FixtureSessionBridge(state["http_app"], configuration), controls, marker), host="127.0.0.1", port=settings.port,
                access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
