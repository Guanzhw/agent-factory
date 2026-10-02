"""Owned AT10 acceptance worker; no fixture routes or production import."""
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import sys

from agno.exceptions import ModelProviderError
from sqlalchemy.engine import make_url
import uvicorn

from agent_factory.main import create_app
from agent_factory.local_orx_profile import local_profile_settings
from agent_factory.orx_experiment_tools import LocalORXWorkflowModel, MODEL_ADAPTER_ID, TOOL_NAMES
from agent_factory.orx_local import TaskLocalORXProvider


def main():
    database=os.environ['AT10_FIXTURE_DATABASE_URL']
    parsed=make_url(database)
    if parsed.host not in {'127.0.0.1','localhost'} or not re.fullmatch(r'af_test_[a-f0-9]{32}',parsed.database or ''):
        raise ValueError('Only a newly owned loopback fixture database is allowed')
    root=Path(os.environ['AT10_FIXTURE_WORKSPACE']).resolve()
    gate_path=root/'inference-fault.json'
    if not gate_path.is_file():raise ValueError('Explicit controlled-fault fixture required')
    provider=TaskLocalORXProvider(binary=Path(os.environ['FACTORY_ORX_BINARY']),
        source_archive=Path(os.environ['FACTORY_ORX_SOURCE_ARCHIVE']),git_binary=Path(os.environ['FACTORY_ORX_GIT_BINARY']),
        python_binary=Path(sys._base_executable))
    settings=local_profile_settings(db_url=database,workspace=root,provider=provider,contract_revision='2',
        port=int(os.environ['AT10_FIXTURE_PORT']))
    settings.queue_poll=.1
    settings.jwt_key=os.environ['AT10_FIXTURE_JWT_KEY']
    app=create_app(settings);state=app.app.state.factory
    class FaultModel(LocalORXWorkflowModel):
        def _response(self,messages):
            gate=json.loads(gate_path.read_text())
            launched=any(m.role=='tool' and m.tool_name==TOOL_NAMES[1] and 'orxRunId' in str(m.content) for m in messages)
            if launched and gate['failures']:
                gate['failures']-=1;gate['actualFailures']+=1
                temporary=gate_path.with_suffix('.tmp');temporary.write_text(json.dumps(gate));temporary.replace(gate_path)
                raise ModelProviderError('Controlled inference outage without a provider call',status_code=503)
            return super()._response(messages)
    bindings=state['execution_bindings'];key=('model',MODEL_ADAPTER_ID,'1')
    bindings._adapters[key]=replace(bindings._adapters[key],factory=lambda _:FaultModel())
    try:uvicorn.run(app,host='127.0.0.1',port=settings.port,access_log=False)
    finally:state['store'].engine.dispose();state['store'].native_db.db_engine.dispose()


if __name__=='__main__':main()
