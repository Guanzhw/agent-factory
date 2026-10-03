"""Owned Linux AT10 services, with real authority HTTP and controlled model faults."""
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import sys
import time

from agno.exceptions import ModelProviderError
from agno.models.response import ModelResponse
from sqlalchemy.engine import make_url
import jwt
import uvicorn

from agent_factory.main import create_app
from agent_factory.local_orx_profile import local_profile_settings
from agent_factory.orx_local import TaskLocalORXProvider
from agent_factory.orx_experiment_tools import LocalORXWorkflowModel, MODEL_ADAPTER_ID, TOOL_NAMES
from agent_factory.remote_handoff import HandoffTarget, TrustedOrigin
from agent_factory.remote_authority import OriginAuthorityTransport
from agent_factory.remote_bindings import TrustedRemoteBindingMapping

ORIGIN = 'at10-tree-origin'
TARGET = 'at10-tree-receiver'


def token(key):
    at=int(time.time())
    return jwt.encode({'sub':'alice','aud':'agent-factory','iat':at,'exp':at+3600},key,algorithm='HS256')


def build(config):
    url=make_url(config['dbUrl'])
    if url.host not in {'127.0.0.1','localhost'} or not re.fullmatch(r'af_test_[a-f0-9]{32}',url.database or ''):
        raise ValueError('Only generated loopback fixture databases are allowed')
    provider=TaskLocalORXProvider(binary=Path(os.environ['FACTORY_ORX_BINARY']),
        source_archive=Path(os.environ['FACTORY_ORX_SOURCE_ARCHIVE']),git_binary=Path(os.environ['FACTORY_ORX_GIT_BINARY']),
        python_binary=Path(sys._base_executable))
    settings=local_profile_settings(db_url=config['dbUrl'],workspace=Path(config['workspace']),provider=provider,
        port=config['port'],contract_revision='2')
    settings.jwt_key=config['jwtKey'];settings.queue_poll=.1;settings.max_workers=2
    if config['role']!='local':
        target=HandoffTarget(TARGET,ORIGIN,config['receiverUrl'],{'alice':'alice'},
            lambda _: {'Authorization':'Bearer '+token(config['receiverJwtKey'])},configuration_revision='at10-tree-v1')
        if config['role']=='origin':
            settings.handoff_targets={TARGET:target}
        else:
            transport=OriginAuthorityTransport(base_url=config['originUrl'],origin_ref=ORIGIN,target_ref=TARGET,
                target_revision=target.configuration_revision,target_fingerprint=target.fingerprint,
                receiver_identity_map=target.identity_map,credential_provider=lambda _:token(config['originJwtKey']))
            settings.handoff_origins={ORIGIN:TrustedOrigin(ORIGIN,{'alice':'alice'},transport,
                capabilities=frozenset({'research:read','compute:local','question:ask'}),tools=frozenset((*TOOL_NAMES,'ask_scope')),
                budget={'toolCalls':8,'maxDepth':1,'maxChildren':1,'experimentSeconds':30,'outputBytes':65536},
                configuration_revision='at10-tree-v1',tool_contract='orx-evidence-v2')}
            settings.remote_binding_mappings={m['reference']:TrustedRemoteBindingMapping(**m) for m in config.get('mappings',[])}
    app=create_app(settings);state=app.app.state.factory
    gate_path=Path(config['gate'])
    def factory(context):
        class FaultModel(LocalORXWorkflowModel):
            async def ainvoke(self,messages,**kwargs):
                return self._response(messages)

            def _response(self,messages):
                gate=json.loads(gate_path.read_text())
                task=context.store.task(context.run_context.session_id)
                child=bool(context.plan.get('delegation'))
                if gate.get('scope')=='parent' and not child and not any(m.role=='tool' and m.tool_name=='ask_scope' for m in messages):
                    return ModelResponse(role='assistant',tool_calls=[{'id':'at10-parent-scope','type':'function',
                        'function':{'name':'ask_scope','arguments':json.dumps({'question':'Confirm original child evidence scope'})}}])
                launched=any(m.role=='tool' and m.tool_name==TOOL_NAMES[1] and 'orxRunId' in str(m.content) for m in messages)
                requested=gate.get('parentFaultTask')==task['id'] or (launched and gate.get('scope','root')==('child' if child else 'root'))
                if requested and task['id'] not in gate['failedTasks']:
                    gate['failedTasks'].append(task['id'])
                    temporary=gate_path.with_suffix('.tmp');temporary.write_text(json.dumps(gate));temporary.replace(gate_path)
                    raise ModelProviderError('Controlled inference outage; no provider call',status_code=503)
                if gate.get('scope')=='parent' and not child and task['id'] in gate['failedTasks']:
                    return ModelResponse(role='assistant',content='Controlled parent resumed; child evidence remains separately owned.')
                return super()._response(messages)
        return FaultModel()
    bindings=state['execution_bindings'];key=('model',MODEL_ADAPTER_ID,'1')
    bindings._adapters[key]=replace(bindings._adapters[key],factory=factory)
    return app,state


def main():
    path=Path(os.environ['FACTORY_AT10_TREE_CONFIG']).resolve();config=json.loads(path.read_text())
    if not Path(config['workspace']).resolve().is_relative_to(path.parent):
        raise ValueError('Owned workspace must stay within fixture directory')
    if os.getenv('FACTORY_AT10_TIMING')=='1':
        from agent_factory.orx_local import TaskLocalORXAdapter
        counts={}
        def record(name,seconds):
            item=counts.setdefault(name,{'count':0,'seconds':0.})
            item['count']+=1;item['seconds']+=seconds
            path.with_suffix('.timings.json').write_text(json.dumps(counts))
        original_authority=OriginAuthorityTransport.__call__
        def authority(self,*args,**kwargs):
            start=time.monotonic()
            try:return original_authority(self,*args,**kwargs)
            finally:record('authority',time.monotonic()-start)
        OriginAuthorityTransport.__call__=authority
        original_execute=TaskLocalORXAdapter._execute
        async def execute(self,argv,**kwargs):
            start=time.monotonic()
            try:return await original_execute(self,argv,**kwargs)
            finally:record('cli:'+argv[0],time.monotonic()-start)
        TaskLocalORXAdapter._execute=execute
    app,state=build(config)
    try:uvicorn.run(app,host='127.0.0.1',port=config['port'],access_log=False)
    finally:state['store'].engine.dispose();state['store'].native_db.db_engine.dispose()


if __name__=='__main__':main()
