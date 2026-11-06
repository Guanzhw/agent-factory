"""Optional private-QA setup and reads of historical research setup records."""
from copy import deepcopy
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from agent_factory.application_schema import Budget
from agent_factory.applications import GovernedStorage
from agent_factory.store import digest
from .projects import Reference, RequestId
from .qa_workflow import FUNCTION_TOOLS, INPUT_SCHEMA, WORKFLOW_ID


class PrepareQASetup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    name: str = Field(min_length=1, max_length=120)
    modelConnectionRef: Reference
    budget: Budget


class PublishSetup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId


class ResearchSetup:
    def __init__(self, store, auth, connections, models, *, qa_workflow=None):
        self.store, self.auth, self.connections, self.models = store, auth, connections, models
        self.apps, self.materials = store.applications, store.material_governance
        self.qa_workflow = qa_workflow
        self.db = GovernedStorage(store, 'research_setup_v1')
        metadata = MetaData()
        self.drafts = Table('research_setup', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('intent', JSON, nullable=False), Column('result', JSON, nullable=False))
        self.commands = self.db.command_table('research_setup_commands', metadata)
        metadata.create_all(store.engine)
        with self.db.read() as conn:
            references = [result['applicationRef'] for result in conn.execute(select(self.drafts.c.result)).scalars()
                          if result.get('applicationRef') is not None]
        for ref in references:
            self.apps.mark_application_entry(ref)

    def candidates(self, owner):
        self.auth.require_member(owner)
        fields = ('reference', 'provider', 'model', 'available', 'connectionRef')
        return {'workflowPin': None,
            'qaMinimumToolCalls': len(self.qa_workflow.tool_registrations) if self.qa_workflow is not None else None,
            'models': [{k: item[k] for k in fields if k in item} for item in self.models.list(owner)],
            'connections': [{k: item[k] for k in ('ref', 'registrationRef', 'kind', 'capabilities', 'available')}
                for item in self.connections.list(owner)],
            'environments': [{k: item[k] for k in ('adapterId', 'revision', 'connectionKind', 'requiredCapabilities')}
                for item in self.store.execution_bindings.describe() if item['kind'] == 'environment'],
            'experimentMaterials': []}

    def _row(self, conn, owner, identifier):
        row = conn.execute(select(self.drafts).where(self.drafts.c.id == identifier,
            self.drafts.c.owner_id == owner)).mappings().first()
        if row is None:
            raise HTTPException(404, 'RESEARCH_SETUP_NOT_FOUND')
        return row

    def read(self, owner, identifier):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            return deepcopy(self._row(conn, owner, identifier)['result'])

    def request_result(self, owner, request_id):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            result = conn.execute(select(self.commands.c.result).where(self.commands.c.actor_id == owner,
                self.commands.c.request_id == request_id)).scalar()
            if result is None:
                raise HTTPException(404, 'RESEARCH_SETUP_REQUEST_NOT_FOUND')
            return deepcopy(result)

    def _selection(self, owner, intent):
        descriptors = self.store.execution_bindings.describe()
        def descriptor(kind, adapter_id, revision):
            entry = next((x for x in descriptors if x['kind'] == kind and x['adapterId'] == adapter_id
                and x['revision'] == revision), None)
            if entry is None:
                raise HTTPException(409, 'RESEARCH_SETUP_ADAPTER_UNAVAILABLE')
            return entry
        env = intent['environment']
        environment = descriptor('environment', env['adapterId'], env['revision'])
        model = descriptor('model', 'owner-chat-completions-v1', '1')
        tools = []
        refs = dict(intent['connectionRefs'])
        if {'model', 'environment'} & refs.keys():
            raise HTTPException(422, 'RESEARCH_SETUP_RESERVED_CONNECTION_SLOT')
        refs['model'] = intent['modelConnectionRef']
        if env.get('connectionRef'):
            refs['environment'] = env['connectionRef']
        requirements = {}
        def require(entry, slot):
            kind = entry['connectionKind']
            if kind is None:
                if slot is not None:
                    raise HTTPException(422, 'RESEARCH_SETUP_UNEXPECTED_CONNECTION')
                return
            if not slot or slot not in refs:
                raise HTTPException(422, 'RESEARCH_SETUP_CONNECTION_REQUIRED')
            value = {'name': slot, 'kind': kind, 'requiredCapabilities': entry['requiredCapabilities'], 'required': True}
            old = requirements.get(slot)
            if old and old['kind'] != kind:
                raise HTTPException(422, 'RESEARCH_SETUP_CONNECTION_SLOT_CONFLICT')
            if old:
                value['requiredCapabilities'] = sorted(set(old['requiredCapabilities']) | set(value['requiredCapabilities']))
            requirements[slot] = value
        require(model, 'model')
        require(environment, 'environment' if env.get('connectionRef') else None)
        if set(refs) != set(requirements):
            raise HTTPException(422, 'RESEARCH_SETUP_UNUSED_CONNECTION')
        pins = {name: self.connections.preflight(owner, refs[name], value['kind'],
            required_capabilities=value['requiredCapabilities']) for name, value in requirements.items()}
        missing = self.store.execution_bindings.preflight(tools, owner, pins)
        if missing:
            raise HTTPException(409, {'code': 'RESEARCH_SETUP_BINDINGS_UNAVAILABLE', 'missing': missing})
        controllers = []
        if self.qa_workflow is None:
            raise HTTPException(409, 'RESEARCH_QA_NOT_INSTALLED')
        registrations = self.qa_workflow.tool_registrations
        names = set(FUNCTION_TOOLS)
        if {entry.tool_name for entry in registrations} != names:
            raise HTTPException(409, 'RESEARCH_SETUP_CONTROLLER_UNAVAILABLE')
        for registration in registrations:
            entry = descriptor('tool', registration.adapter_id, registration.revision)
            if entry['toolName'] != registration.tool_name:
                raise HTTPException(409, 'RESEARCH_SETUP_CONTROLLER_UNAVAILABLE')
            controllers.append(entry)
        return refs, pins, list(requirements.values()), tools, model, environment, controllers

    def prepare_qa(self, owner, request: PrepareQASetup):
        if self.qa_workflow is None:
            raise HTTPException(409, 'RESEARCH_QA_NOT_INSTALLED')
        registration = self.qa_workflow.environment_registration
        intent = request.model_dump(exclude={'requestId'}) | {'mode': 'qa',
            'environment': {'adapterId': registration.adapter_id, 'revision': registration.revision},
            'experimentMaterialRefs': [], 'connectionRefs': {}}
        return self._prepare(owner, request.requestId, intent)

    def _prepare(self, owner, request_id, intent):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'prepare', 'intent': intent})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None:
                return old
            refs, *_ = self._selection(owner, intent)
            identifier = str(uuid4())
            preview = {**intent, 'workflowPin': self.store.native_workflows.pin(WORKFLOW_ID)}
            result = {'id': identifier, 'state': 'draft', 'applicationRef': None,
                'connectionRefs': refs, 'materialRefs': [], 'preview': preview}
            conn.execute(self.drafts.insert().values(id=identifier, owner_id=owner, intent=intent, result=result))
            return self.db.record(conn, self.commands, owner, request_id, fingerprint, 'prepare', result)

    def publish(self, owner, identifier, request: PublishSetup):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'publish', 'id': identifier})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            if old is not None:
                return old
            row = self._row(conn, owner, identifier)
            if row['result']['state'] == 'published':
                return self.db.record(conn, self.commands, owner, request.requestId, fingerprint, 'publish', row['result'])
            intent, preview = row['intent'], row['result']['preview']
            if intent.get('mode') != 'qa':
                raise HTTPException(409, 'RESEARCH_USE_AGENT_SESSION')
            if self.store.native_workflows.pin(WORKFLOW_ID) != preview['workflowPin']:
                raise HTTPException(409, 'RESEARCH_SETUP_PREVIEW_CHANGED')
            refs, pins, requirements, tools, model, environment, controllers = self._selection(owner, intent)
            generated = []
            for kind, entry, slot in [('model', model, 'model'), ('environment', environment, 'environment' if environment['connectionKind'] else None),
                    *[('tool', item, None) for item in controllers]]:
                definition = {'kind': kind, 'name': entry['toolName'] or kind, 'content': entry['toolName'] or 'Research execution resource.',
                    'permissions': entry['permissions'] if kind == 'tool' else [],
                    'runtimeBinding': {'adapterId': entry['adapterId'], 'revision': entry['revision'],
                        'config': {'connectionName': slot} if slot else {}}}
                material = self.materials.create_draft(owner, definition, str(uuid4()))
                self.materials.publish(owner, material['id'], material['version'], str(uuid4()))
                generated.append(material)
            missing = self.store.execution_bindings.preflight(generated + tools, owner, pins)
            if missing:
                raise HTTPException(409, {'code': 'RESEARCH_SETUP_BINDINGS_UNAVAILABLE', 'missing': missing})
            self.store.execution_bindings.build(generated + tools, owner, pins)
            def mode(materials):
                caps = {cap for item in materials for cap in item['permissions']}
                caps.update(cap for value in requirements for cap in value['requiredCapabilities'])
                return {'materialRefs': [self.apps.pin(item) for item in materials], 'capabilities': sorted(caps),
                    'connectionRequirements': requirements, 'budget': intent['budget'],
                    'toolOrder': [item['content'] for item in materials if item['kind'] == 'tool']}
            research = mode(generated + tools)
            research.update(nativeComponent=preview['workflowPin'], inputSchema=INPUT_SCHEMA)
            default_mode, modes = 'qa', {'qa': research}
            application = self.apps.create_draft(owner, {'contractVersion': 2, 'name': intent['name'],
                'defaultMode': default_mode, 'modes': modes}, str(uuid4()), entry_kind='application')
            self.apps.publish(owner, application['id'], application['version'], str(uuid4()))
            result = {**row['result'], 'state': 'published', 'applicationRef': self.apps.pin(application),
                'connectionRefs': refs, 'materialRefs': research['materialRefs'], 'mode': default_mode}
            conn.execute(self.drafts.update().where(self.drafts.c.id == identifier).values(result=result))
            return self.db.record(conn, self.commands, owner, request.requestId, fingerprint, 'publish', result)


def setup_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/setup')

    @router.get('')
    def candidates(request: Request):
        return service.candidates(auth.user(request)['id'])

    @router.post('/qa/drafts')
    def prepare_qa(request: Request, body: PrepareQASetup):
        return service.prepare_qa(auth.user(request)['id'], body)

    @router.get('/requests/{request_id}')
    def recover(request: Request, request_id: str):
        return service.request_result(auth.user(request)['id'], request_id)

    @router.get('/{identifier}')
    def read(request: Request, identifier: str):
        return service.read(auth.user(request)['id'], identifier)

    @router.post('/{identifier}/publish')
    def publish(request: Request, identifier: str, body: PublishSetup):
        return service.publish(auth.user(request)['id'], identifier, body)

    return router
