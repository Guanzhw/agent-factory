"""One owner submit over existing composition, plan reservation and native queue."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .byok_model import ADAPTER_ID
from .factory_api import InstanceRequest

APPLICATION_ID = 'personal-research-v1'
CONNECTION_NAME = 'ownerModel'


def template_support(store, owner):
    application = next((app for app in store.applications.list_active(owner) if app['id'] == APPLICATION_ID), None)
    if application is None:
        return {'applicationAvailable': False, 'supported': False, 'unsupportedReason':
            'PERSONAL_RESEARCH_TEMPLATE_REQUIRED' if store.settings.demo else 'PERSONAL_RESEARCH_REAL_TOOLS_REQUIRED'}
    try:
        materials = store.applications.closure(application['modes']['literature']['materialRefs'])
    except HTTPException as error:
        if error.status_code not in {404, 409}: raise
        return {'applicationAvailable': True, 'supported': False, 'templateKind': 'unavailable',
            'unsupportedReason': 'PERSONAL_RESEARCH_REAL_TOOLS_REQUIRED'}
    tools = [item for item in materials if item['kind'] == 'tool']
    bindings = store.execution_bindings
    from .execution_bindings import LEGACY_DEMO
    adapters, synthetic = [], False
    for item in tools:
        binding = item.get('runtimeBinding')
        if binding is None:
            # Historical seed tools have no explicit binding. Classify them as
            # demo-only; execution still performs the existing exact seed check.
            legacy = LEGACY_DEMO.get(item['id'])
            binding = {'adapterId': legacy[1], 'revision': '1'} if legacy is not None and legacy[0] == 'tool' else {}
            synthetic = True
        entry = bindings._adapters.get(('tool', binding.get('adapterId'), binding.get('revision')))
        adapters.append(entry)
        synthetic |= entry is not None and entry.demo_only
    supported = bool(tools) and all(entry is not None for entry in adapters) and (store.settings.demo or not synthetic)
    return {'applicationAvailable': True, 'supported': supported,
        'templateKind': 'synthetic-demo' if synthetic else 'approved-read-only',
        'unsupportedReason': None if supported else 'PERSONAL_RESEARCH_REAL_TOOLS_REQUIRED'}


class SubmitResearch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    topic: str = Field(min_length=2, max_length=2000)
    requestId: str = Field(min_length=8, max_length=100, pattern=r'^[a-zA-Z0-9_.:-]+$')


def personal_research_router(auth, store, factory):
    router = APIRouter(prefix='/api/factory/personal-research')
    @router.get('/capabilities')
    def capabilities(request: Request):
        owner = auth.user(request)['id']
        auth.require(owner, 'read')
        return {'applicationId': APPLICATION_ID, **template_support(store, owner),
            'modelSetup': '/api/factory/personal-models', 'steps': ['configure-default-model', 'submit-goal'],
            'nativeQueue': True, 'liveCompatibilityVerified': False,
            'platformBillingEnabled': False, 'hardExternalBudgetEnforced': False}
    @router.post('', status_code=202)
    async def submit(body: SubmitResearch, request: Request):
        owner = auth.user(request)['id']
        auth.require(owner, 'run')
        # The replayed request keeps its original model pin even if the default
        # changes. A stale/revoked original binding fails current admission.
        def create():
            support = template_support(store, owner)
            if not support['supported']:
                raise HTTPException(409, str(support['unsupportedReason']) +
                    ': no approved executable research tools; use the configured native ORX personal-agent path')
            model = store.personal_models.default(owner)
            if not any(app['id'] == APPLICATION_ID for app in store.applications.list_active(owner)):
                raise HTTPException(409, 'PERSONAL_RESEARCH_TEMPLATE_REQUIRED: install the approved research template')
            return store.composition.create_plan(owner, body.topic, 'literature', APPLICATION_ID,
                request_id='research-plan-' + body.requestId,
                connection_refs={CONNECTION_NAME: model['connectionRef']})
        plan = store.admit_plan(owner, body.requestId, {'personalResearch': body.model_dump()}, create)
        store.owner_submissions.approve(owner, plan)
        result = await factory.instantiate(owner, InstanceRequest(planId=plan['id'], requestId=body.requestId))
        return {**result, 'planId': plan['id'], 'billing': {
            'platformBillingEnabled': False, 'hardExternalBudgetEnforced': False, 'payer': 'owner-provider-account'}}
    @router.get('/requests/{request_id}')
    def recover(request_id: str, request: Request):
        owner = auth.user(request)['id']
        auth.require(owner, 'read')
        task = store.task_for_request(request_id, owner)
        plan = store.plan(task['plan_id'], owner)
        if plan['application'] != APPLICATION_ID: raise HTTPException(404, 'PERSONAL_RESEARCH_REQUEST_NOT_FOUND')
        return {'requestId': request_id, 'taskId': task['id'], 'planId': task['plan_id'],
            'nativeRunId': task['run_id'], 'admission': task['admission']}
    return router


def publish_application(state, *, author, reviewer):
    """Trusted one-time shared template publication, separate from owner tasks.

    Operators may compose other approved read-only research tools with this model
    adapter. The bundled minimal template retains honest synthetic tool evidence.
    """
    auth = state['auth']
    if not state['store'].settings.demo:
        raise HTTPException(409, 'PERSONAL_RESEARCH_DEMO_TEMPLATE_ONLY')
    auth.require(author, 'components:write'); auth.require(reviewer, 'agent_os:admin')
    if author == reviewer: raise HTTPException(403, 'PERSONAL_INDEPENDENT_REVIEW_REQUIRED')
    governance, applications, store = state['material_governance'], state['applications'], state['store']
    definition = {'id': APPLICATION_ID + '-model', 'kind': 'model', 'name': 'Owner BYOK model',
        'description': 'Owner configured text/function Chat Completions; live compatibility unverified.',
        'content': 'Native Agno owner BYOK dispatch. No platform key or billing.', 'license': 'MIT',
        'compatibility': ['agno:3.1.0'], 'dependencies': [], 'permissions': [],
        'runtimeBinding': {'adapterId': ADAPTER_ID, 'revision': '1', 'config': {'connectionName': CONNECTION_NAME}},
        'provenance': {'kind': 'original', 'notice': 'Native model wire subset; live compatibility unverified.'}}
    model = governance.create_draft(author, definition, APPLICATION_ID + ':model-draft')
    review = governance.request_publication(author, model['id'], model['version'], APPLICATION_ID + ':model-review')
    governance.decide_publication(reviewer, review['id'], True, APPLICATION_ID + ':model-approve')
    seeds = {item['id']: item for item in store.materials() if item['published']}
    required = ['research-skill', 'research-prompt', 'literature-tool', 'question-tool', 'local-environment']
    if any(key not in seeds for key in required): raise HTTPException(409, 'PERSONAL_RESEARCH_MATERIALS_REQUIRED')
    materials = [model, *(seeds[key] for key in required)]
    definition = {'id': APPLICATION_ID, 'name': 'Personal research', 'defaultMode': 'literature',
        'description': 'Owner BYOK research with explicitly synthetic literature fixtures.', 'discoveryKeywords': [],
        'modes': {'literature': {'materialRefs': [applications.pin(item) for item in materials],
            'capabilities': ['research:read', 'question:ask'], 'toolOrder': ['literature_search', 'ask_scope'],
            'config': {}, 'connectionRequirements': [{'name': CONNECTION_NAME, 'kind': 'model',
                'required': True, 'requiredCapabilities': []}],
            'budget': {'toolCalls': 8, 'maxDepth': 2, 'maxChildren': 4, 'experimentSeconds': 8, 'outputBytes': 65536}}}}
    application = applications.create_draft(author, definition, APPLICATION_ID + ':draft')
    review = applications.request_publication(author, application['id'], application['version'], APPLICATION_ID + ':review')
    applications.decide_publication(reviewer, review['id'], True, APPLICATION_ID + ':approve')
    return application
