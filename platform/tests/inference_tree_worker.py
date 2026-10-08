"""Owned Linux AT10 services, with real authority HTTP and controlled model faults."""
from dataclasses import replace
from contextlib import contextmanager
from contextvars import ContextVar
import asyncio
import cProfile
import pstats
import threading
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
        python_binary=Path(getattr(sys, '_base_executable', sys.executable)))
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


class TimingRecorder:
    """Opt-in aggregate diagnostics: fixed labels only, never arguments or identities."""
    def __init__(self, path):
        self.path = path
        self.counts = {}
        self.lock = threading.Lock()

    @contextmanager
    def measure(self, name):
        if name not in {'authority', 'authority:lifecycle', 'authority:execution', 'cli', 'lifecycle',
                        'container-setup', 'experiment-setup', 'model-selection'}:
            raise ValueError('Timing labels must be fixed and public')
        started = time.monotonic()
        cancelled = False
        try:
            yield
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            seconds = time.monotonic() - started
            with self.lock:
                item = self.counts.setdefault(name, {'count': 0, 'seconds': 0., 'maxSeconds': 0., 'cancelled': 0})
                item['count'] += 1
                item['seconds'] += seconds
                item['maxSeconds'] = max(item['maxSeconds'], seconds)
                item['cancelled'] += int(cancelled)
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps(self.counts))
                temporary.replace(self.path)


class OneShotAuthorityProfile:
    """Profile one synthetic authority callback, emitting only bounded code statistics."""
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.claimed = False

    def call(self, callback, *args, **kwargs):
        with self.lock:
            selected = not self.claimed
            self.claimed = True
        if not selected:
            return callback(*args, **kwargs)
        profiler = cProfile.Profile()
        try:
            return profiler.runcall(callback, *args, **kwargs)
        finally:
            rows = []
            for (filename, _line, function), (primitive, calls, _self, cumulative, _callers) in pstats.Stats(profiler).stats.items():
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*|<(lambda|module|listcomp|dictcomp|setcomp|genexpr)>', function):
                    continue
                rows.append({'file': Path(filename).name, 'function': function,
                    'calls': calls, 'primitiveCalls': primitive, 'cumulativeSeconds': cumulative})
            rows.sort(key=lambda row: row['cumulativeSeconds'], reverse=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'schema': 1, 'callback': 'origin-authority', 'functions': rows[:20]}))
            temporary.replace(self.path)


class RecoveryRecorder:
    """Bounded synthetic recovery phases; no arguments, identifiers or exception text."""
    stages = frozenset({'eligibility', 'proof', 'completed-launch', 'root-lock-wait', 'root-lock-held',
                        'prepare-pause', 'publish-pause', 'observe-wait', 'validate-requirement',
                        'command-prepare', 'command-dispatch', 'service-start'})
    codes = frozenset({'APPROVED_RECOVERY_' + suffix for suffix in (
        'CANCELED', 'MISSING', 'PROOF', 'STALE', 'SCOPE', 'TOOLS', 'ALREADY_RECORDED',
        'CURRENT', 'PLATFORM', 'STOPPING', 'EFFECT', 'STOP')} | {'INFERENCE_WAIT_EXPIRED'})

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.events = []
        self.started = time.monotonic()
        self.started_unix = time.time()
        self.active = ContextVar('at10_recovery_active', default=False)

    @contextmanager
    def measure(self, stage, *, identity=None):
        if stage not in self.stages:
            raise ValueError('Only fixed recovery stages are allowed')
        started = time.monotonic()
        outcome = 'OK'
        try:
            yield
        except BaseException as error:
            from agno.exceptions import RunCancelledException
            from fastapi import HTTPException
            if isinstance(error, asyncio.CancelledError):
                outcome = 'CANCELLED'
            elif isinstance(error, RunCancelledException):
                outcome = 'RUN_CANCELLED'
            elif isinstance(error, HTTPException):
                candidate = error.detail.split(':', 1)[0] if isinstance(error.detail, str) else ''
                outcome = candidate if candidate in self.codes else 'HTTP_OTHER'
            else:
                outcome = 'OTHER'
            raise
        finally:
            ended = time.monotonic()
            event = {'stage': stage, 'startSeconds': started - self.started,
                     'endSeconds': ended - self.started, 'seconds': ended - started, 'outcome': outcome}
            if identity is not None:
                event['identity'] = {key: value for key, value in identity.items()
                    if key in {'proofPresent', 'queueRunMatches', 'queueOwnerMatches', 'queueTaskMatches'}
                    and type(value) is bool}
            with self.lock:
                self.events.append(event)
                self.events = self.events[-256:]
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'schema': 1, 'startedUnixSeconds': self.started_unix, 'events': self.events}))
                temporary.replace(self.path)


def install_recovery_timing(path):
    from agent_factory.control_commands import ControlCommands
    from agent_factory.delegation import DelegationService
    recorder = RecoveryRecorder(path)
    from agent_factory import inference_wait
    def timed_sync(original, stage):
        def wrapped(*args, **kwargs):
            with recorder.measure(stage):
                return original(*args, **kwargs)
        return wrapped
    def timed_async(original, stage):
        async def wrapped(*args, **kwargs):
            with recorder.measure(stage):
                return await original(*args, **kwargs)
        return wrapped
    for method, stage in (('prepare_pause', 'prepare-pause'), ('publish_pause', 'publish-pause'),
                          ('observe', 'observe-wait'), ('validate_requirement', 'validate-requirement')):
        setattr(inference_wait, method, timed_sync(getattr(inference_wait, method), stage))
    for method, stage in (('_prepare', 'command-prepare'), ('dispatch', 'command-dispatch')):
        setattr(ControlCommands, method, timed_async(getattr(ControlCommands, method), stage))
    original_eligibility = ControlCommands.approved_recovery
    async def eligibility(self, task, snapshot, **kwargs):
        queue = snapshot.get('queue') or {}
        proof = ((queue.get('payload') or {}).get('continue') or {}).get('kwargs', {}).get('metadata', {}).get('factoryControlCommand')
        identity = {'proofPresent': isinstance(proof, dict) and bool(proof),
                    'queueRunMatches': queue.get('id') == task.get('run_id'),
                    'queueOwnerMatches': queue.get('user_id') == task.get('owner_id'),
                    'queueTaskMatches': queue.get('session_id') == task.get('id')}
        token = recorder.active.set(True)
        try:
            with recorder.measure('eligibility', identity=identity):
                return await original_eligibility(self, task, snapshot, **kwargs)
        finally:
            recorder.active.reset(token)
    ControlCommands.approved_recovery = eligibility
    original_proof = ControlCommands._approval_payload
    def proof(*args, **kwargs):
        with recorder.measure('proof'):
            return original_proof(*args, **kwargs)
    ControlCommands._approval_payload = staticmethod(proof)
    original_completed = ControlCommands._completed_launch
    def completed(self, *args, **kwargs):
        with recorder.measure('completed-launch'):
            return original_completed(self, *args, **kwargs)
    ControlCommands._completed_launch = completed
    original_lock = DelegationService._root_lock
    @contextmanager
    def root_lock(self, *args, **kwargs):
        if not recorder.active.get():
            with original_lock(self, *args, **kwargs) as value:
                yield value
            return
        # ExitStack preserves the original context manager's exception/unlock semantics.
        from contextlib import ExitStack
        with ExitStack() as stack:
            with recorder.measure('root-lock-wait'):
                value = stack.enter_context(original_lock(self, *args, **kwargs))
            with recorder.measure('root-lock-held'):
                yield value
    DelegationService._root_lock = root_lock
    return recorder


def install_timing(path):
    from agent_factory.orx_local import TaskLocalORXAdapter
    from agent_factory.lifecycle_observer import FactoryLifecycleObserver
    from agent_factory.orx_linux import TaskLinuxContainer
    from agent_factory.model_dispatch import DelegatingModel
    recorder = TimingRecorder(path)
    install_recovery_timing(path.with_suffix('.recovery.json'))
    from agent_factory.remote_handoff import TrustedHandoffClient
    authority_profile = OneShotAuthorityProfile(path.with_suffix('.profile.json'))
    original_callback = TrustedHandoffClient.authority_callback
    def origin_authority(self, *args, **kwargs):
        return authority_profile.call(original_callback, self, *args, **kwargs)
    TrustedHandoffClient.authority_callback = origin_authority
    original_authority = OriginAuthorityTransport.__call__
    def authority(self, *args, **kwargs):
        # Examine names only; no locals, filenames, stack text or arguments are saved.
        frame = sys._getframe(1)
        lifecycle = False
        for _ in range(40):
            if frame is None:
                break
            if frame.f_code.co_name in {'observe_root', '_reason'}:
                lifecycle = True
                break
            frame = frame.f_back
        del frame
        with recorder.measure('authority'), recorder.measure('authority:lifecycle' if lifecycle else 'authority:execution'):
            return original_authority(self, *args, **kwargs)
    OriginAuthorityTransport.__call__ = authority
    original_execute = TaskLocalORXAdapter._execute
    async def execute(self, argv, **kwargs):
        with recorder.measure('cli'):
            return await original_execute(self, argv, **kwargs)
    TaskLocalORXAdapter._execute = execute
    original_observe = FactoryLifecycleObserver.observe_root
    async def observe(self, *args, **kwargs):
        with recorder.measure('lifecycle'):
            return await original_observe(self, *args, **kwargs)
    FactoryLifecycleObserver.observe_root = observe
    original_container = TaskLinuxContainer.__init__
    def container_setup(self, *args, **kwargs):
        with recorder.measure('container-setup'):
            original_container(self, *args, **kwargs)
    TaskLinuxContainer.__init__ = container_setup
    original_experiment = TaskLocalORXAdapter.ensure_experiment
    async def experiment_setup(self, *args, **kwargs):
        with recorder.measure('experiment-setup'):
            return await original_experiment(self, *args, **kwargs)
    TaskLocalORXAdapter.ensure_experiment = experiment_setup
    original_selection = DelegatingModel._prepare_selection
    def model_selection(self, *args, **kwargs):
        with recorder.measure('model-selection'):
            return original_selection(self, *args, **kwargs)
    DelegatingModel._prepare_selection = model_selection


def main():
    path=Path(os.environ['FACTORY_AT10_TREE_CONFIG']).resolve();config=json.loads(path.read_text())
    if not Path(config['workspace']).resolve().is_relative_to(path.parent):
        raise ValueError('Owned workspace must stay within fixture directory')
    if os.getenv('FACTORY_AT10_TIMING')=='1':
        install_timing(path.with_suffix('.timings.json'))
    app,state=build(config)
    try:uvicorn.run(app,host='127.0.0.1',port=config['port'],access_log=False)
    finally:state['store'].engine.dispose();state['store'].native_db.db_engine.dispose()


if __name__=='__main__':main()
