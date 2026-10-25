"""Bare-core subprocess probe for same-database application removal; no app imports."""
import json
from pathlib import Path
import sys
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request
import uvicorn

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.lifecycle_observer import FactoryLifecycleObserver


class ExplicitObserver(FactoryLifecycleObserver):
    @asynccontextmanager
    async def lifespan(self, app):
        # Keep phase assertions deterministic; the HTTP probe calls the real observer.
        yield


def serve(configuration):
    app = create_app(Settings(db_url=configuration['dbUrl'], workspace=Path(configuration['workspace']),
        jwt_key=configuration['jwtKey'], demo=True, max_workers=1),
        lifecycle_observer_type=ExplicitObserver)
    native = app
    while not hasattr(getattr(native, 'state', None), 'factory'):
        native = native.app
    state = native.state.factory
    store = state['store']

    def authorize(request):
        if request.headers.get('X-Fixture-Control') != configuration['controlKey']:
            raise HTTPException(403, 'FIXTURE_CONTROL_DENIED')

    @native.get('/__workflow_fixture/facts')
    async def facts(request: Request, taskId: str, scopeId: str):
        authorize(request)
        task = store.task(taskId, 'alice')
        operations = [store.workflow.read('alice', row['id']) for row in store.sql(
            'SELECT id FROM af_external_operations WHERE task_id=:task ORDER BY id', task=taskId)]
        return {'task': task, 'taskIds': [item['id'] for item in store.tasks('alice')],
            'operations': [{'id': item['id'], 'taskId': item['taskId'], 'runId': item['nativeRunId'],
                            'closed': item['closed'], 'observation': item['observation']} for item in operations],
            'scope': state['local_budget_scopes'].inspect('alice', scopeId),
            'native': store.native_db.get_job(task['run_id']),
            'researchImported': any(name == 'research' or name.startswith('research.') for name in sys.modules),
            'deploymentImported': any(name == 'agent_factory_server' or name.startswith('agent_factory_server.') for name in sys.modules),
            'applicationOwners': bool(store.application_runtime),
            'configuredWorkflows': len(state['settings'].native_workflows),
            'configuredAdapters': len(state['settings'].runtime_adapters)}

    @native.post('/__workflow_fixture/observe')
    async def observe(request: Request, taskId: str):
        authorize(request)
        return await state['lifecycle_observer'].observe_root(taskId)

    uvicorn.run(app, host='127.0.0.1', port=configuration['port'], log_level='error', access_log=False)


if __name__ == '__main__':
    serve(json.loads(Path(sys.argv[2]).read_text()))
