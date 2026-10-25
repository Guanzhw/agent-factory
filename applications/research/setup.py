"""Explicit research publication using core governance and owner bindings."""
from copy import deepcopy
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from agent_factory.application_schema import Budget
from agent_factory.applications import GovernedStorage
from agent_factory.material_governance import PinnedRef
from agent_factory.store import digest
from .projects import Reference, RequestId
from .workflow import FUNCTION_TOOLS, INPUT_SCHEMA, WORKFLOW_ID


class EnvironmentSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    adapterId: Reference
    revision: Reference
    connectionRef: Reference | None = None


class PrepareSetup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    name: str = Field(min_length=1, max_length=120)
    modelConnectionRef: Reference
    environment: EnvironmentSelection
    experimentMaterialRefs: list[PinnedRef] = Field(min_length=1, max_length=20)
    connectionRefs: dict[Reference, Reference] = Field(default_factory=dict, max_length=12)
    budget: Budget


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
    def __init__(self, store, auth, connections, models, *, controller_registrations, qa_workflow=None):
        self.store, self.auth, self.connections, self.models = store, auth, connections, models
        self.apps, self.materials = store.applications, store.material_governance
        self.controller_registrations = tuple(controller_registrations)
        self.qa_workflow = qa_workflow
        self.db = GovernedStorage(store, 'research_setup_v1')
        metadata = MetaData()
        self.drafts = Table('research_setup', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('intent', JSON, nullable=False), Column('result', JSON, nullable=False))
        self.commands = self.db.command_table('research_setup_commands', metadata)
        metadata.create_all(store.engine)

    @staticmethod
    def _controllers():
        return {*FUNCTION_TOOLS, 'factory_wait_operations'}

    def candidates(self, owner):
        self.auth.require_member(owner)
        fields = ('reference', 'provider', 'model', 'available', 'connectionRef')
        return {'workflowPin': self.store.native_workflows.pin(WORKFLOW_ID),
            'models': [{k: item[k] for k in fields if k in item} for item in self.models.list(owner)],
            'connections': [{k: item[k] for k in ('ref', 'registrationRef', 'kind', 'capabilities', 'available')}
                for item in self.connections.list(owner)],
            'environments': [{k: item[k] for k in ('adapterId', 'revision', 'connectionKind', 'requiredCapabilities')}
                for item in self.store.execution_bindings.describe() if item['kind'] == 'environment'],
            'experimentMaterials': [self._tool_candidate(item)
                for item in self.store.materials(published_only=True)
                if item['kind'] == 'tool' and item.get('runtimeBinding') and item['content'] not in self._controllers()]}

    def _tool_candidate(self, item):
        result = {k: item[k] for k in ('id', 'version', 'sha256', 'name', 'permissions', 'dependencies', 'runtimeBinding')}
        requirements = []
        descriptors = self.store.execution_bindings.describe()
        try:
            for material in self.apps.closure([self.apps.pin(item)]):
                if material['kind'] not in {'tool', 'knowledge'}:
                    continue
                binding = material.get('runtimeBinding') or {}
                entry = next((x for x in descriptors if x['kind'] == material['kind']
                    and x['adapterId'] == binding.get('adapterId') and x['revision'] == binding.get('revision')
                   ), None)
                if entry is None:
                    raise HTTPException(409, 'RESEARCH_SETUP_ADAPTER_UNAVAILABLE')
                if entry['connectionKind']:
                    requirements.append({'name': binding.get('config', {}).get('connectionName'),
                        'kind': entry['connectionKind'], 'requiredCapabilities': entry['requiredCapabilities']})
        except HTTPException as error:
            return {**result, 'connectionRequirements': [], 'available': False, 'unavailableReason': error.detail}
        return {**result, 'connectionRequirements': requirements, 'available': True}


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
        tools = [] if intent.get('mode') == 'qa' else self.apps.closure(intent['experimentMaterialRefs'])
        selected = {(ref['id'], ref['version'], ref['sha256']) for ref in intent['experimentMaterialRefs']}
        if any(item['content'] in self._controllers() for item in tools if item['kind'] == 'tool'):
            raise HTTPException(422, 'RESEARCH_SETUP_EXPERIMENT_CONTROLLER')
        for item in tools:
            if (item['id'], item['version'], item['sha256']) in selected and (item['kind'] != 'tool' or not item.get('runtimeBinding')):
                raise HTTPException(422, 'RESEARCH_SETUP_EXPERIMENT_TOOL_REQUIRED')
            if item['kind'] in {'model', 'environment'}:
                raise HTTPException(422, 'RESEARCH_SETUP_EXPERIMENT_RESOURCE_CONFLICT')
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
        for item in tools:
            if item['kind'] in {'tool', 'knowledge'}:
                binding = item.get('runtimeBinding')
                if not binding:
                    raise HTTPException(409, 'RESEARCH_SETUP_BINDING_REQUIRED')
                entry = descriptor(item['kind'], binding['adapterId'], binding['revision'])
                slot = binding['config'].get('connectionName')
                if slot in {'model', 'environment'}:
                    raise HTTPException(422, 'RESEARCH_SETUP_RESERVED_CONNECTION_SLOT')
                require(entry, slot)
        if set(refs) != set(requirements):
            raise HTTPException(422, 'RESEARCH_SETUP_UNUSED_CONNECTION')
        pins = {name: self.connections.preflight(owner, refs[name], value['kind'],
            required_capabilities=value['requiredCapabilities']) for name, value in requirements.items()}
        missing = self.store.execution_bindings.preflight(tools, owner, pins)
        if missing:
            raise HTTPException(409, {'code': 'RESEARCH_SETUP_BINDINGS_UNAVAILABLE', 'missing': missing})
        controllers = []
        registrations = self.controller_registrations
        names = self._controllers()
        if intent.get('mode') == 'qa':
            from .qa_workflow import FUNCTION_TOOLS as QA_TOOLS
            if self.qa_workflow is None:
                raise HTTPException(409, 'RESEARCH_QA_NOT_INSTALLED')
            registrations = self.qa_workflow.tool_registrations
            names = set(QA_TOOLS)
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

    def prepare(self, owner, request: PrepareSetup):
        return self._prepare(owner, request.requestId, request.model_dump(exclude={'requestId'}, exclude_none=True))

    def _prepare(self, owner, request_id, intent):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'prepare', 'intent': intent})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None:
                return old
            refs, *_ = self._selection(owner, intent)
            identifier = str(uuid4())
            preview = {**intent, 'workflowPin': self.store.native_workflows.pin('research-qa' if intent.get('mode') == 'qa' else WORKFLOW_ID)}
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
            if self.store.native_workflows.pin('research-qa' if intent.get('mode') == 'qa' else WORKFLOW_ID) != preview['workflowPin']:
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
            if intent.get('mode') == 'qa':
                from .qa_workflow import INPUT_SCHEMA as QA_INPUT_SCHEMA
                research.update(nativeComponent=preview['workflowPin'], inputSchema=QA_INPUT_SCHEMA)
                default_mode, modes = 'qa', {'qa': research}
            else:
                research.update(nativeComponent=preview['workflowPin'], inputSchema=INPUT_SCHEMA)
                default_mode, modes = 'research', {'research': research, 'experiment': mode(generated[:2] + tools)}
            application = self.apps.create_draft(owner, {'contractVersion': 2, 'name': intent['name'],
                'defaultMode': default_mode, 'modes': modes}, str(uuid4()))
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

    @router.post('/drafts')
    def prepare(request: Request, body: PrepareSetup):
        return service.prepare(auth.user(request)['id'], body)

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
