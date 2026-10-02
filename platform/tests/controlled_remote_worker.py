"""Explicit acceptance server: controlled adapters, real Factory/Agno/TCP/PG.

Loaded ONLY by test_governed_remote_process_postgres.py in owned child processes.
The fixture control router is never imported by production application startup.
All keys, users, registrations, workspaces and databases are generated test data.
"""
from __future__ import annotations

import copy
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
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import MetaData, Table, func, inspect, select
from sqlalchemy.engine import make_url

from agent_factory.auth import AuthService
from agent_factory.config import Settings
from agent_factory.connections import ConnectionService, TrustedConnectionBinding
from agent_factory.demo_model import DemoModel
from agent_factory.execution_bindings import AdapterRegistration, KnowledgeContext
from agent_factory.main import create_app
from agent_factory.openresearch import BinaryPin, REVISION, VERSION
from agent_factory.orx_tools import ORX_ADAPTER_ID
from agent_factory.remote_authority import OriginAuthorityTransport
from agent_factory.remote_bindings import TrustedRemoteBindingMapping
from agent_factory.remote_handoff import HandoffTarget, TrustedOrigin
from agent_factory.store import Store

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
ORX_CONNECTION_REGISTRATION = "fixture-owner-orx"
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


class ControlledORXAdapter:
    """No command, binary or discovery network is invoked in this fixture."""
    def __init__(self, owner_id, task_id, max_output_bytes, command_timeout):
        self.owner_id, self.task_id = owner_id, task_id
        self.pin = BinaryPin(REVISION, VERSION, "d602b1b184589b72d9ce68a119b8959ee595f46869e951f63309781e60b173e7")
        self.enabled = True
        self.transport_kind = "controlled_transport_fixture"
        self.max_output_bytes, self.command_timeout = max_output_bytes, command_timeout
        self._processes = set()

    async def discover(self, query, *, corpus, limit):
        return [{"source": "openalex", "id": "W-controlled-tcp-fixture", "title": "Synthetic remote discovery metadata", "year": 2026}][:limit]


class ControlledORXProvider:
    def create_adapter(self, *, owner_id, task_id, scope, authorize, pin, max_output_bytes, command_timeout):
        return ControlledORXAdapter(owner_id, task_id, max_output_bytes, command_timeout)


class ControlledModel(DemoModel):
    """Native model API; deterministic fixture output, no provider request."""
    async def ainvoke(self, messages, **kwargs):
        return self._response(messages)


def provision_owned_subjects(settings):
    native = PostgresDb(db_url=settings.db_url, id="owned-process-bootstrap")
    auth = AuthService(settings, native)
    try:
        read_scopes = ["agents:factory-executor:read", "components:read", "registry:read", "sessions:read", "filesystem:read"]
        auth.authorization.define_role("fixture-reader", read_scopes)
        auth.authorization.define_role("fixture-user", [*read_scopes, "agents:factory-executor:run"])
        auth.authorization.define_role("fixture-admin-role", ["agent_os:admin"])
        local_owner = ORIGIN_OWNER if settings.fixture_role == "origin" else RECEIVER_OWNER
        for subject in (ORIGIN_OWNER, RECEIVER_OWNER, OTHER_OWNER, MANAGER, REVIEWER):
            if auth.directory.get(subject) is None:
                auth.directory.upsert(subject, name=subject)
                role = "fixture-admin-role" if subject in {MANAGER, REVIEWER} else "fixture-user" if subject in {local_owner, OTHER_OWNER} else "fixture-reader"
                auth.authorization.assign(subject, role)
        store = Store(settings.db_url, settings)
        try:
            service = ConnectionService(store, auth, settings.trusted_connections)
            bound = service.bind(local_owner, CONNECTION_REGISTRATION, "fixture-bind-before-main", capabilities=["checksum:read"])
            if ORX_CONNECTION_REGISTRATION in settings.trusted_connections:
                orx = service.bind(local_owner, ORX_CONNECTION_REGISTRATION, "fixture-orx-bind-before-main", capabilities=["research:read"])
                settings.fixture_orx_pin = {name: orx[name] for name in CONNECTION_FIELDS}
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
        material_definition("fixture-selected-environment", "environment", "Fixed bounded local environment.", "local-bounded-environment-v1"),
        material_definition("fixture-selected-knowledge", "knowledge", "Original public controlled checksum knowledge.", "fixture-knowledge-v1"),
        material_definition("fixture-selected-skill", "skill", "Calculate only the approved checksum and report artifact evidence."),
        material_definition("fixture-selected-prompt", "prompt", "Follow the reviewed task and current authority."),
        material_definition("fixture-selected-checksum", "tool", "checksum", "native-checksum-v1", permissions=["checksum:read"]),
        material_definition("fixture-selected-question", "tool", "ask_scope", "native-ask-scope-v1", permissions=["question:ask"]),
    ]
    if state["settings"].runtime_tool_contract == "registered-runtime-v1":
        definitions.append(material_definition("fixture-selected-orx", "tool", "orx_discover", ORX_ADAPTER_ID,
            {"connectionName": "discovery"}, permissions=["research:read"]))
    materials = {}
    for definition in definitions:
        mid = definition["id"]
        created = governance.create_draft(MANAGER, definition, "fixture-draft-" + mid)
        review = governance.request_publication(MANAGER, mid, created["version"], "fixture-review-" + mid)
        governance.decide_publication(REVIEWER, review["id"], True, "fixture-approve-" + mid)
        materials[mid] = created
    common = [pin(materials["fixture-selected-" + suffix]) for suffix in ("model", "environment", "knowledge", "skill", "prompt", "checksum")]
    budget = {"toolCalls": 8, "maxDepth": 2, "maxChildren": 4, "experimentSeconds": 8, "outputBytes": 65536}
    requirement = [{"name": "provider", "kind": "model", "requiredCapabilities": ["checksum:read"], "required": True}]
    direct = {"materialRefs": common, "capabilities": ["checksum:read"], "toolOrder": ["checksum"], "budget": budget, "connectionRequirements": requirement}
    paused = {**direct, "materialRefs": [*common, pin(materials["fixture-selected-question"])],
              "capabilities": ["checksum:read", "question:ask"], "toolOrder": ["ask_scope", "checksum"], "config": {"askScopeBelowLength": 2000}}
    modes = {"direct": direct, "paused": paused}
    if "fixture-selected-orx" in materials:
        modes["discovery"] = {**direct, "materialRefs": [*common, pin(materials["fixture-selected-orx"])],
            "capabilities": ["checksum:read", "research:read"], "toolOrder": ["checksum", "orx_discover"],
            "connectionRequirements": [*requirement, {"name": "discovery", "kind": "orx", "requiredCapabilities": ["research:read"], "required": True}]}
    if source_application is None:
        application = applications.create_draft(MANAGER, {"id": APP_ID, "name": "Governed controlled checksum",
            "description": "Actual non-demo policy path with explicitly controlled provider.", "defaultMode": "direct",
            "modes": modes}, "fixture-application-draft")
    else:
        # Operator-only exact snapshot install does not copy source approval.
        # The receiver below independently reviews its own imported draft.
        application = applications.import_snapshot(MANAGER, source_application, "fixture-application-import")
    review = applications.request_publication(MANAGER, application["id"], application["version"], "fixture-application-review")
    applications.decide_publication(REVIEWER, review["id"], True, "fixture-application-approve")
    return pin(application), materials, application


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
                or self.controls.get("fault") != "exit_after_dispatch"):
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
            self.marker.write_text(json.dumps({"pid": os.getpid(), "phase": "after-native-dispatch-before-http-ack", "status": status}), encoding="utf-8")
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
    settings = Settings(db_url=configuration["dbUrl"], demo=False, jwt_key=configuration["jwtKey"], workspace=workspace,
        port=configuration["port"], max_workers=1, max_user_tasks=12, max_total_tasks=24, temporary_policy="admin-review")
    settings.fixture_role = role
    if configuration.get("registeredTools"):
        settings.runtime_tool_contract = "registered-runtime-v1"
        settings.policy_revision = "fixture-registered-plan-policy-v1"
        settings.material_policy_revision = "fixture-registered-material-policy-v1"
    owner = ORIGIN_OWNER if role == "origin" else RECEIVER_OWNER
    adapter = MODEL_SOURCE if role == "origin" else MODEL_RECEIVER
    provider = ControlledProvider(role + "-opaque-handle-marker")
    trusted = TrustedConnectionBinding(owner, "model", adapter, frozenset({"checksum:read"}), "fixture-provider-v1",
        available=True, opaque_handle=provider, handle_ref=role + "-stable-owned-provider")
    settings.trusted_connections = {CONNECTION_REGISTRATION: trusted}
    if configuration.get("registeredTools"):
        settings.trusted_connections[ORX_CONNECTION_REGISTRATION] = TrustedConnectionBinding(owner, "orx", ORX_ADAPTER_ID,
            frozenset({"research:read"}), "fixture-orx-provider-v1", available=True, opaque_handle=ControlledORXProvider(),
            handle_ref=role + "-stable-owned-orx-provider")
    connection_pin = provision_owned_subjects(settings)
    def model(context):
        if context.connection is not provider or context.run_context.user_id != owner:
            raise PermissionError("Controlled provider handle is outside its exact selected owner")
        provider.created.append({"ownerId": owner, "taskId": context.run_context.session_id, "runId": context.run_context.run_id})
        context.store.event(context.run_context.run_id, "controlled_provider_selected", "Explicit test provider; no network request",
            {"fixtureOnly": True, "ownerId": owner, "adapterId": adapter, "pid": os.getpid(), "workspace": str(workspace)})
        return ControlledModel(id=adapter)
    settings.runtime_adapters = [AdapterRegistration("model", adapter, "1", model, connection_kind="model", required_capabilities=("checksum:read",)),
        AdapterRegistration("knowledge", "fixture-knowledge-v1", "1", lambda context: KnowledgeContext("Original scoped fixture checksum context.", {"evidenceKind": "controlled-adapter"}))]
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
        origin_options = {"tools": frozenset({"ask_scope", "checksum", "orx_discover"}),
            "capabilities": frozenset({"question:ask", "checksum:read", "research:read"}),
            "configuration_revision": "fixture-registered-origin-v1", "tool_contract": "registered-runtime-v1"} if configuration.get("registeredTools") else {}
        settings.handoff_origins = {ORIGIN_REF: TrustedOrigin(ORIGIN_REF, {ORIGIN_OWNER: RECEIVER_OWNER}, transport, **origin_options)}
        source = configuration["sourceSpec"]
        effective = {**copy.deepcopy(source), "adapterId": MODEL_RECEIVER, "connection": connection_pin}
        initial_mapping = TrustedRemoteBindingMapping(MAPPING_REF, "fixture-mapping-v1", ORIGIN_REF, ORIGIN_OWNER, RECEIVER_OWNER,
            "model", source, effective)
        settings.remote_binding_mappings = {MAPPING_REF: initial_mapping}
        if configuration.get("registeredTools"):
            orx_source = configuration["sourceORXSpec"]
            settings.remote_binding_mappings["fixture-exact-orx-mapping"] = TrustedRemoteBindingMapping("fixture-exact-orx-mapping",
                "fixture-orx-mapping-v1", ORIGIN_REF, ORIGIN_OWNER, RECEIVER_OWNER, "tool", orx_source,
                {**copy.deepcopy(orx_source), "connection": settings.fixture_orx_pin})
    application = create_app(settings)
    state = application.app.state.factory
    application_ref, materials, snapshot = publish_fixture(state, configuration.get("sourceApplication"))
    controls = {"fault": None}
    marker = directory / (role + "-fault.json")

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
        return {"fixtureOnly": True, "pid": os.getpid(), "mode": "production-policy-controlled-provider", "demo": settings.demo,
            "workspace": str(workspace), "applicationRef": application_ref, "applicationSnapshot": snapshot, "connection": connection_pin,
            "materials": {key: pin(value) for key, value in materials.items()}, "orxConnection": getattr(settings, "fixture_orx_pin", None), "providerCreated": list(provider.created),
            "nativeTickets": count, "tasks": store.tasks(owner),
            "plan": store.plan(store.task(taskId, owner)["plan_id"], owner) if taskId else None,
            "placements": store.sql("SELECT * FROM af_remote_placements") if role == "origin" else [],
            "handoffs": store.sql("SELECT * FROM af_remote_handoffs") if role == "receiver" else [],
            "bindingProofs": store.sql("SELECT * FROM af_remote_binding_proofs WHERE receiver_owner=:owner", owner=owner) if role == "receiver" else []}

    @application.app.post("/__fixture/control")
    async def control(request: Request):
        authenticated(request)
        body = await request.json()
        if set(body) - {"op", "fault"}:
            raise HTTPException(422, "Unsupported fixture controls")
        op = body.get("op")
        if op == "fault":
            if body.get("fault") not in {None, "exit_after_dispatch"}:
                raise HTTPException(422, "Unsupported fixture fault")
            controls["fault"] = body.get("fault")
        elif op in {"role-revoke", "role-restore"}:
            state["auth"].authorization.unassign(owner, "fixture-user" if op == "role-revoke" else "fixture-reader")
            state["auth"].authorization.assign(owner, "fixture-reader" if op == "role-revoke" else "fixture-user")
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
    uvicorn.run(DropDispatchAcknowledgement(FixtureSessionBridge(application, configuration), controls, marker), host="127.0.0.1", port=settings.port,
                access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
