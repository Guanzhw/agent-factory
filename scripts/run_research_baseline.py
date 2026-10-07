"""Task-local preparation -> baseline -> independent evaluation, existing native APIs.

Run inside the pinned research venv with PYTHONDONTWRITEBYTECODE=1. Factory must
be installed as the actual site-packages/agent_factory source package. Configuration,
progress, interpreter contracts and receipts contain private paths: KEEP LOCAL.
No dependency install, database provisioning, remote endpoint or model payment.
Existing workspace means inspect-only; never reset or automatically replay a stage.
"""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import stat
import sys
import time
import warnings
from types import ModuleType
from typing import Any, cast

ERROR = 'RESEARCH_BASELINE_STOPPED'
_KEYS = {'schema', 'ackLocalDevelopment', 'ackTraining', 'databaseUrlFile', 'workspace', 'requestId',
         'inputRoot', 'tokenizerBasename', 'shards', 'validationIds', 'upstreamRoot', 'projectRoot',
         'venvRoot', 'interpreterTarget', 'interpreterSha256', 'approvedInterpreterRoots', 'deviceUuid',
         'receiverNamespaceSha256', 'nvidiaSmi', 'limits', 'microbatch'}


# Public diagnostic vocabulary only: no exception text, arguments, traceback,
# configuration values, paths, request identifiers or credential-derived data.
_STAGES = frozenset({
    'PREPARATION_APP_SETTINGS',
    'PREPARATION_APP_NATIVE_DB',
    'PREPARATION_APP_STORE',
    'PREPARATION_APP_ORX_SCHEMA',
    'PREPARATION_APP_AUTH',
    'PREPARATION_APP_DEMO_IDENTITIES',
    'PREPARATION_APP_STORAGE',
    'PREPARATION_APP_EVENT_REPLAY',
    'PREPARATION_APP_CATALOG',
    'PREPARATION_APP_GOVERNANCE',
    'PREPARATION_APP_DEMO_GOVERNANCE',
    'PREPARATION_APP_CONNECTIONS',
    'PREPARATION_APP_SYNTHESIS_SOURCES',
    'PREPARATION_APP_BINDINGS',
    'PREPARATION_APP_RUNTIME_ADAPTERS',
    'PREPARATION_APP_USAGE_LEDGER',
    'PREPARATION_APP_REMOTE_BINDINGS',
    'PREPARATION_APP_APPLICATIONS',
    'PREPARATION_APP_COMPOSITION',
    'PREPARATION_APP_NATIVE_GRAPH',
    'PREPARATION_APP_BRIDGE',
    'PREPARATION_APP_DELEGATION',
    'PREPARATION_APP_PLAN_POLICY',
    'PREPARATION_APP_HANDOFF',
    'PREPARATION_APP_SCHEDULING',
    'PREPARATION_APP_ROUTES',
    'PREPARATION_APP_RESOURCES',
    'PREPARATION_APP_PROCESS_RUNTIME',
    'PREPARATION_APP_RESEARCH_RUNTIME',
    'PREPARATION_APP_COMPARISONS',
    'PREPARATION_APP_AGENTOS',
    'PREPARATION_APP_ATTACH',
    'PREPARATION_APP_OBSERVER',
    'PREPARATION_APP_BROWSER_AUTH',

    'ARGUMENTS', 'CONFIG_READ', 'CONFIG_VALIDATE', 'WORKSPACE_INSPECT',
    'WORKSPACE_CREATE', 'PROGRESS_START', 'EXECUTE', 'PROGRESS_COMPLETE', 'PROGRESS_STOPPED',
    'EXECUTION_IMPORTS', 'EXECUTION_IDENTITY', 'DATABASE_CONFIG', 'UPSTREAM_READ',
    'UPSTREAM_VERIFY', 'TOKENIZER_READ', 'RESOURCE_LIMITS', 'DEVICE_OBSERVER',
    'DATABASE_PREFLIGHT', 'ASSEMBLY_DISPOSE', 'PREFLIGHT', 'PREPARATION_SETTINGS', 'PREPARATION_DATABASE', 'PREPARATION_DRIVER',
    'PREPARATION_PROCESS_SPEC', 'PREPARATION_PROVIDER', 'PREPARATION_TARGET',
    'PREPARATION_APPLICATION_SETTINGS', 'PREPARATION_CREATE_APP', 'PREPARATION_STORE',
    'PREPARATION_ASSEMBLY_CLEANUP', 'PREPARATION_ASSEMBLY', 'PREPARATION_STARTUP', 'PREPARATION_SHUTDOWN', 'PREPARATION_PUBLICATION',
    'PREPARATION_PROPOSAL', 'PREPARATION_PLAN', 'PREPARATION_REVIEW',
    'PREPARATION_APPROVAL', 'PREPARATION_SUBMIT', 'PREPARATION_RECEIPT',
    'PREPARATION_WAIT', 'PREPARATION_IMPORT', 'PREPARATION_CLEANUP',
    'ENVIRONMENT_INVENTORY', 'INTERPRETER_CONTRACT', 'ENVIRONMENT_PINS',
    'INPUT_CAPTURE', 'TRAINING_ASSEMBLY', 'TRAINING_STARTUP', 'TRAINING_PUBLICATION',
    'TRAINING_RUN', 'TRAINING_RECEIPT', 'TRAINING_SHUTDOWN', 'EVALUATION_ASSEMBLY', 'EVALUATION_STARTUP',
    'EVALUATION_PUBLICATION', 'EVALUATION_RUN', 'EVALUATION_RECEIPT', 'EVALUATION_SHUTDOWN', 'CLEANUP',
})


def exception_code(error):
    # Inspect only trusted types already imported; diagnostic handling must not
    # import more dependencies or inspect driver .orig / exception attributes.
    ancestry = type.__getattribute__(type(error), '__mro__')
    for module_name, class_name, code in (
        ('sqlalchemy.exc', 'IntegrityError', 'DATABASE_INTEGRITY'),
        ('sqlalchemy.exc', 'OperationalError', 'DATABASE_OPERATIONAL'),
        ('sqlalchemy.exc', 'SQLAlchemyError', 'DATABASE_ERROR'),
        ('httpx', 'TimeoutException', 'HTTP_TIMEOUT'),
        ('httpx', 'HTTPError', 'HTTP_ERROR'),
        ('starlette.exceptions', 'HTTPException', 'HTTP_REJECTED'),
        ('asyncio.exceptions', 'CancelledError', 'CANCELLED'),
    ):
        module = sys.modules.get(module_name)
        kind = vars(module).get(class_name) if type(module) is ModuleType else None
        if isinstance(kind, type) and any(base is kind for base in ancestry):
            return code
    for kind, code in (
        (KeyboardInterrupt, 'INTERRUPTED'), (SystemExit, 'SYSTEM_EXIT'),
        (ModuleNotFoundError, 'MODULE_NOT_FOUND'), (ImportError, 'IMPORT_ERROR'),
        (FileNotFoundError, 'FILE_NOT_FOUND'), (PermissionError, 'PERMISSION_DENIED'),
        (FileExistsError, 'ALREADY_EXISTS'), (TimeoutError, 'TIMEOUT'),
        (json.JSONDecodeError, 'CONFIG_JSON_INVALID'), (UnicodeError, 'ENCODING_INVALID'),
        (ValueError, 'VALIDATION_REJECTED'), (TypeError, 'TYPE_INVALID'),
        (KeyError, 'FIELD_MISSING'), (OSError, 'OS_ERROR'),
        (RuntimeError, 'RUNTIME_ERROR'), (AssertionError, 'INVARIANT_REJECTED'),
    ):
        if any(base is kind for base in ancestry):
            return code
    return 'UNEXPECTED_ERROR'


class Diagnostics:
    """One primary failure plus at most one secondary cleanup/journal code."""
    def __init__(self):
        self.stage = 'ARGUMENTS'
        self.failure = None
        self._error_identity = None

    def at(self, stage):
        require(type(stage) is str and stage in _STAGES)
        self.stage = stage

    def capture(self, error):
        if self.failure is None:
            self.failure = {'schema': 1, 'kind': 'RESEARCH_BASELINE_DIAGNOSTIC',
                            'stage': self.stage, 'errorCode': exception_code(error)}
            self._error_identity = id(error)
        elif id(error) != self._error_identity and 'secondaryErrorCode' not in self.failure:
            self.failure['secondaryErrorCode'] = exception_code(error)
            self.failure['secondaryStage'] = self.stage

    def emit(self):
        if self.failure is not None:
            print(json.dumps(self.failure, sort_keys=True, separators=(',', ':')), file=sys.stderr)


def require(value):
    if not value:
        raise ValueError(ERROR)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def read_private(path, maximum=2 * 1024**2, *, private=True):
    from bootstrap_research_control import _directory
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts)
    parent = _directory(str(path.parent))
    fd = None
    try:
        fd = os.open(path.name, os.O_RDONLY | getattr(os, 'O_NOFOLLOW') | getattr(os, 'O_NONBLOCK'), dir_fd=parent)
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == getattr(os, 'getuid')()
                and (stat.S_IMODE(before.st_mode) == 0o600 if private else not before.st_mode & 0o022)
                and 0 < before.st_size <= maximum)
        raw = bytearray()
        while len(raw) <= maximum:
            chunk = os.read(fd, min(1024**2, maximum + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        def stamp(info):
            return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)
        require(len(raw) == before.st_size and stamp(before) == stamp(os.fstat(fd))
                == stamp(os.stat(path.name, dir_fd=parent, follow_symlinks=False)))
        return bytes(raw)
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def config_from_bytes(raw) -> dict[str, Any]:
    require(type(raw) is bytes and len(raw) <= 2 * 1024**2)
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError(ERROR)))
    require(type(value) is dict and set(value) == _KEYS and type(value['schema']) is int and value['schema'] == 1
            and value['ackLocalDevelopment'] is True and value['ackTraining'] is True)
    value = cast(dict[str, Any], value)
    for key in ('databaseUrlFile', 'workspace', 'inputRoot', 'upstreamRoot', 'projectRoot', 'venvRoot', 'interpreterTarget'):
        path = value[key]
        require(type(path) is str and path.startswith('/') and str(Path(path)) == path and '..' not in Path(path).parts)
    require(type(value['approvedInterpreterRoots']) is list and 1 <= len(value['approvedInterpreterRoots']) <= 8)
    for path in value['approvedInterpreterRoots']:
        require(type(path) is str and path.startswith('/') and str(Path(path)) == path and '..' not in Path(path).parts)
    for key in ('interpreterSha256', 'receiverNamespaceSha256'):
        require(type(value[key]) is str and re.fullmatch('[a-f0-9]{64}', value[key]))
    require(type(value['requestId']) is str and re.fullmatch('[A-Za-z0-9_.:-]{8,40}', value['requestId']))
    require(type(value['deviceUuid']) is str and re.fullmatch('GPU-[a-fA-F0-9-]{8,80}', value['deviceUuid']))
    require(type(value['nvidiaSmi']) is dict and set(value['nvidiaSmi']) == {'executable', 'sha256'})
    value['nvidiaSmi'] = cast(dict[str, Any], value['nvidiaSmi'])
    require(type(value['nvidiaSmi']['executable']) is str and Path(value['nvidiaSmi']['executable']).is_absolute())
    require(type(value['nvidiaSmi']['sha256']) is str and re.fullmatch('[a-f0-9]{64}', value['nvidiaSmi']['sha256']))
    require(type(value['limits']) is dict and set(value['limits']) ==
            {'cpu_seconds', 'address_space_mb', 'file_size_bytes', 'wall_seconds', 'disk_bytes', 'output_bytes'})
    value['limits'] = cast(dict[str, Any], value['limits'])
    require(all(type(v) is int and v > 0 for v in value['limits'].values()))
    require(301 <= value['limits']['wall_seconds'] <= 86400)
    require(type(value['microbatch']) is int and 1 <= value['microbatch'] <= 128 and 128 % value['microbatch'] == 0)
    def name(v):
        return type(v) is str and re.fullmatch('[A-Za-z0-9_][A-Za-z0-9_.-]{0,119}', v) and v not in {'.', '..'}
    require(name(value['tokenizerBasename']) and type(value['shards']) is list and 2 <= len(value['shards']) <= 1024)
    require(all(type(row) is dict and set(row) == {'id', 'basename'} and name(row['id']) and name(row['basename'])
                for row in value['shards']))
    ids = [cast(dict[str, Any], row)['id'] for row in value['shards']]
    require(len(set(ids)) == len(ids) and type(value['validationIds']) is list
            and all(type(v) is str for v in value['validationIds'])
            and 0 < len(value['validationIds']) < len(ids) and set(value['validationIds']) <= set(ids))
    return value


def write_private(path, raw):
    from bootstrap_research_control import _directory
    require(type(raw) is bytes and len(raw) <= 16 * 1024**2)
    parent = _directory(str(path.parent))
    fd = None
    try:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW'), 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw); stream.flush(); os.fsync(fd)
        os.fsync(parent)
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def identity(path):
    from bootstrap_research_control import _directory
    fd = _directory(str(path))
    try:
        info = os.fstat(fd)
        require(info.st_uid == getattr(os, 'getuid')() and stat.S_IMODE(info.st_mode) == 0o700)
        return {'device': info.st_dev, 'inode': info.st_ino}
    finally:
        os.close(fd)


class Progress:
    def __init__(self, workspace, diagnostics=None):
        self.workspace, self.sequence = workspace, 0
        self.diagnostics = diagnostics if diagnostics is not None else Diagnostics()

    def at(self, stage):
        self.diagnostics.at(stage)

    def capture(self, error):
        self.diagnostics.capture(error)

    def record(self, stage, value):
        self.sequence += 1
        write_private(self.workspace / f'progress-{self.sequence:06d}.json',
                      canonical({'schema': 1, 'stage': stage, 'progress': value}))


def request_client(bundle, client):
    def request(method, path, body, *, owner):
        token = bundle['state']['auth']._issue_native_token(owner)
        response = client.request(method, path, json=body, timeout=30,
                                  headers={'Authorization': 'Bearer ' + token})
        require(response.is_success)
        return response.json()
    return request


def preparation_phase(bundle, client, request_id, progress):
    from bootstrap_research_control import ensure_task_development_reviewer
    from agent_factory.process_runtime_profile import publish_process_application
    state, store = bundle['state'], bundle['state']['store']
    progress.at('PREPARATION_PUBLICATION')
    reviewer = ensure_task_development_reviewer(state)
    app = publish_process_application(state, target_ref='preparation', author='manager', reviewer=reviewer)
    request = request_client(bundle, client)
    deadline, task_id, plan_id = time.monotonic() + 60, None, None
    def post(path, body, key, owner='alice'):
        return request('POST', '/api/factory' + path, {**body, 'requestId': request_id + ':prep:' + key}, owner=owner)
    try:
        progress.at('PREPARATION_PROPOSAL')
        proposal = post('/compositions/proposals', {'goal': 'Prepare source-bound tokenizer byte lengths',
            'mode': 'controlled-fixture', 'applicationRef': {k: app[k] for k in ('id', 'version', 'sha256')}}, 'proposal')
        progress.at('PREPARATION_PLAN')
        plan = post('/compositions/proposals/' + proposal['id'] + '/accept', {}, 'accept')
        plan_id = plan['id']
        progress.at('PREPARATION_REVIEW')
        review = post('/plan-reviews', {'planId': plan['id']}, 'review')
        progress.at('PREPARATION_APPROVAL')
        post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, 'decision', reviewer)
        try:
            progress.at('PREPARATION_SUBMIT')
            task = post('/instances', {'planId': plan['id']}, 'instance')
            task_id = task['id']
        except BaseException as error:
            progress.capture(error)
            progress.at('PREPARATION_RECEIPT')
            receipt = request('GET', '/api/factory/requests/' + request_id + ':prep:instance', None, owner='alice')
            require(receipt['planId'] == plan['id'] and receipt['requestId'] == request_id + ':prep:instance')
            task_id = receipt['taskId']
            raise
        progress.record('preparation', {'taskId': task_id, 'planId': plan['id'], 'phase': 'ACCEPTED'})
        progress.at('PREPARATION_WAIT')
        while True:
            require(time.monotonic() < deadline)
            detail = request('GET', '/api/factory/jobs/' + task_id, None, owner='alice')
            require(detail['job']['status'] not in {'failed', 'canceled', 'unknown'})
            if detail['job']['status'] == 'completed':
                break
            time.sleep(.1)
        progress.at('PREPARATION_IMPORT')
        original = store.process_runtime._original(task_id)
        require(original is not None)
        lease = store.process_runtime.resources.inspect('alice', original['lease_id'])
        require(lease['state'] == 'RECLAIMED' and lease['executionStatus'] == 'COMPLETED'
                and lease['capacityHeld'] is False and lease['stopEvidence']['allStopped'] is True)
        artifact = bundle['preparation'].import_completed('alice', lease['id'])
        pin = bundle['preparation'].input_pin('alice', task_id, artifact['id'])
        progress.record('preparation', {'phase': 'IMPORTED', 'taskId': task_id, 'nativeRunId': lease['nativeRunId'],
            'leaseId': lease['id'], 'providerJobId': lease['providerJobId'], 'artifactId': artifact['id']})
        return task_id, artifact['id'], pin
    except BaseException as error:
        progress.capture(error)
        progress.at('PREPARATION_CLEANUP')
        validated_original = False
        if task_id is not None:
            try:
                original_task = store.task(task_id, 'alice')
                require(original_task['id'] == task_id and original_task['owner_id'] == 'alice'
                        and plan_id is not None and original_task['plan_id'] == plan_id)
                validated_original = True
            except Exception:
                pass
        if validated_original:
            assert task_id is not None
            from agent_factory.research_bootstrap_controller import cleanup_original
            assert client.portal is not None
            cleanup = cleanup_original(state, 'alice', task_id, runtime=store.process_runtime,
                                       call_async=client.portal.call)
            progress.record('preparation', {'phase': 'STOPPED', 'taskId': task_id, **cleanup})
            try:
                request('POST', '/api/factory/jobs/' + task_id + '/cancel', {}, owner='alice')
            except Exception:
                pass
        raise


def launch_environment(config, program, cache):
    env = {key: str(cache) for key in ('HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR', 'HF_HOME')}
    # The guardian execs with this fresh environment. GCC/collect2 descendants
    # need a tool search path even when the compiler itself is absolute. Use only
    # the supported host's system tools, never the operator's PATH or workspace.
    env['PATH'] = '/usr/bin:/bin'
    env.update(CUDA_VISIBLE_DEVICES=config['deviceUuid'], HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1', PYTHONNOUSERSITE='1', PYTHONPYCACHEPREFIX=str(program),
        SETUPTOOLS_USE_DISTUTILS='local')
    return env


def environment_pins(config, evidence, inventory):
    from agent_factory.research_staging import RootIdentity, FilePin, InputPin
    # The observer binds uv.lock to the ORIGINAL project root and inode. Never
    # copy it into a different evidence root to satisfy private-file checks.
    project = Path(config['projectRoot'])
    lock = read_private(project / 'uv.lock', 8 * 1024**2)
    rows = (('environment-inventory', evidence, 'inventory.json', inventory['inventoryBytes']),
            ('environment-kernel', evidence, 'kernel.json', inventory['kernelBytes']),
            ('environment-lockfile', project, 'uv.lock', lock))
    return tuple(InputPin(label, 'environment', str(root), RootIdentity(**identity(root)),
        FilePin(name, hashlib.sha256(raw).hexdigest(), len(raw))) for label, root, name, raw in rows)


def runtime_identity(config):
    import agent_factory
    require(sys.dont_write_bytecode and Path(sys.prefix) == Path(config['venvRoot'])
            and Path(sys.executable).resolve() == Path(config['interpreterTarget']))
    site = Path(config['venvRoot']) / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
    require(Path(agent_factory.__file__).parent == site / 'agent_factory')


def database_report(config):
    """Existing authorized DB, read-only transaction; no Store or app construction."""
    from bootstrap_research_control import read_database_url
    from sqlalchemy import create_engine
    from agent_factory.config import Settings
    from agent_factory.research_bootstrap_policy import development_settings
    from agent_factory.research_bootstrap_database_preflight import database_preflight
    runtime_identity(config)
    url = read_database_url(config['databaseUrlFile'])
    settings = development_settings(Settings(db_url=url, workspace=Path(config['workspace']),
        max_workers=1, temporary_policy='admin-review'))
    engine = create_engine(url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        return database_preflight(engine, settings)
    finally:
        engine.dispose()


def assemble_only(config, workspace, progress):
    """One original application construction, without entering any lifespan."""
    from bootstrap_research_control import read_database_url
    from agent_factory.research_bootstrap_assembly import prepare_application
    progress.at('EXECUTION_IDENTITY')
    runtime_identity(config)
    progress.at('DATABASE_CONFIG')
    db = read_database_url(config['databaseUrlFile'])
    progress.at('TOKENIZER_READ')
    tokenizer = read_private(Path(config['inputRoot']) / config['tokenizerBasename'], 1024**2)
    progress.at('PREPARATION_ASSEMBLY')
    program, custody = workspace / 'preparation-program', workspace / 'preparation-custody'
    program.mkdir(mode=0o700); custody.mkdir(mode=0o700)
    bundle = None
    try:
        bundle = prepare_application(db_url=db, workspace=workspace, program_root=program,
            program_identity=identity(program), custody_root=custody,
            executable=config['interpreterTarget'], executable_sha256=config['interpreterSha256'],
            tokenizer_json=tokenizer, preparation_manifest_sha256=hashlib.sha256(canonical(
                {'schema': 1, 'purpose': 'tokenizer-preparation', 'tokenizerSha256': hashlib.sha256(tokenizer).hexdigest()})).hexdigest(),
            diagnostics=progress)
    except BaseException as error:
        progress.capture(error)
        raise
    finally:
        if bundle is not None:
            progress.at('ASSEMBLY_DISPOSE')
            # No lifespan was entered: dispose pools directly, never start a
            # worker or scheduler in order to shut it down.
            operations = []
            for store in (bundle['state']['store'], bundle['providerStore']):
                operations.extend((store.dispose_root_locks, store.engine.dispose))
                native = getattr(store, 'native_db', None)
                if native is not None:
                    operations.append(native.db_engine.dispose)
            schedules = bundle['state'].get('schedules')
            if schedules is not None:
                operations.extend((schedules.manager.close, schedules.lock_engine.dispose,
                                   schedules.diagnostics.engine.dispose))
            first = None
            for operation in operations:
                try:
                    operation()
                except BaseException as error:
                    progress.capture(error)
                    if first is None:
                        first = error
            if first is not None:
                raise first


def execute(config, workspace, progress):
    # Imports stay inside the explicitly acknowledged execution path. No Torch import.
    progress.at('EXECUTION_IMPORTS')
    from fastapi.testclient import TestClient
    from bootstrap_research_control import read_database_url, ensure_task_development_reviewer
    from agent_factory.research_bootstrap_assembly import prepare_application, research_application
    from agent_factory.research_bootstrap_inventory import build_inventory
    from agent_factory.research_bootstrap_inputs import capture_bootstrap_inputs
    from agent_factory.research_interpreter import capture_interpreter_contract
    from agent_factory.research_profile import SOURCE_SHA256, verify_upstream_source
    from agent_factory.gpu_custody import GpuBinding
    from agent_factory.research_device_observer import NvidiaSmiObserver
    from agent_factory.process_enforcement import ResearchProcessLimits, UvResearchProcessSpec
    from agent_factory.research_runtime_profile import publish_research_application
    from agent_factory.research_bootstrap_controller import ResearchBootstrapController
    progress.at('EXECUTION_IDENTITY')
    runtime_identity(config)
    progress.at('DATABASE_CONFIG')
    db = read_database_url(config['databaseUrlFile'])
    progress.at('UPSTREAM_READ')
    upstream = {name: read_private(Path(config['upstreamRoot']) / name, 8 * 1024**2, private=False) for name in SOURCE_SHA256}
    progress.at('UPSTREAM_VERIFY')
    verify_upstream_source(upstream)
    progress.at('TOKENIZER_READ')
    tokenizer = read_private(Path(config['inputRoot']) / config['tokenizerBasename'], 1024**2)
    progress.at('RESOURCE_LIMITS')
    limits = ResearchProcessLimits(**config['limits'])
    require(limits.disk_bytes >= 2 * limits.file_size_bytes + limits.output_bytes)
    def directory(name):
        path = workspace / name; path.mkdir(mode=0o700)
        return path
    progress.at('DEVICE_OBSERVER')
    gpu = GpuBinding(config['receiverNamespaceSha256'], hashlib.sha256(config['deviceUuid'].encode()).hexdigest())
    device = NvidiaSmiObserver(Path(config['nvidiaSmi']['executable']), config['nvidiaSmi']['sha256'],
                               config['deviceUuid'], gpu, 'task-local-real-observer-v1')
    bundles = []
    def retain(bundle):
        bundles.append(bundle)
        return bundle
    try:
        progress.at('PREPARATION_ASSEMBLY')
        program = directory('preparation-program')
        prep = retain(prepare_application(db_url=db, workspace=workspace, program_root=program, diagnostics=progress,
            program_identity=identity(program), custody_root=directory('preparation-custody'),
            executable=config['interpreterTarget'], executable_sha256=config['interpreterSha256'],
            tokenizer_json=tokenizer, preparation_manifest_sha256=hashlib.sha256(canonical(
                {'schema': 1, 'purpose': 'tokenizer-preparation', 'tokenizerSha256': hashlib.sha256(tokenizer).hexdigest()})).hexdigest()))
        progress.at('PREPARATION_STARTUP')
        with TestClient(prep['app']) as client:
            try:
                prep_task, prep_artifact, token_pin = preparation_phase(prep, client, config['requestId'], progress)
            except BaseException as error:
                progress.capture(error)
                raise
            finally:
                progress.at('PREPARATION_SHUTDOWN')
        progress.at('ENVIRONMENT_INVENTORY')
        evidence = directory('environment')
        inventory = build_inventory(project_root=config['projectRoot'], venv_root=config['venvRoot'],
            interpreter_target=config['interpreterTarget'], interpreter_sha256=config['interpreterSha256'],
            approved_interpreter_roots=config['approvedInterpreterRoots'], inventory_path=evidence / 'inventory.json',
            startup_profile='uv0117-setuptools82-local-v1')
        write_private(evidence / 'inventory.json', inventory['inventoryBytes'])
        write_private(evidence / 'kernel.json', inventory['kernelBytes'])
        progress.at('INTERPRETER_CONTRACT')
        contract = capture_interpreter_contract(**inventory['captureKwargs'])
        write_private(evidence / 'interpreter-contract.json', contract.encode())
        progress.at('ENVIRONMENT_PINS')
        pins = environment_pins(config, evidence, inventory)
        progress.at('INPUT_CAPTURE')
        captured = capture_bootstrap_inputs(input_root=Path(config['inputRoot']), tokenizer_basename=config['tokenizerBasename'],
            shards=tuple((row['id'], row['basename']) for row in config['shards']), validation_ids=tuple(config['validationIds']),
            upstream_files=upstream, environment_pins=pins, gpu_binding=gpu, limits=limits,
            token_bytes_pin=token_pin, microbatch=config['microbatch'])
        prior, training, training_store = prep, None, None
        results = {}
        for stage in ('training', 'evaluation'):
            progress.at(stage.upper() + '_ASSEMBLY')
            program, cache, custody = directory(stage + '-program'), directory(stage + '-cache'), directory(stage + '-custody')
            entry = 'train_baseline.py' if stage == 'training' else 'evaluate.py'
            env = launch_environment(config, program, cache)
            spec = UvResearchProcessSpec(str(Path(config['venvRoot']) / 'bin/python'), config['interpreterSha256'],
                ('-B', str(program / entry), '--config', str(program / 'run-config.json')), working_directory=str(program),
                working_directory_identity=(identity(program)['device'], identity(program)['inode']), environment=tuple(sorted(env.items())),
                interpreter_contract=contract)
            bundle = retain(research_application(db_url=db, workspace=workspace, upstream_files=upstream,
                captured_inputs=captured, environment_pins=pins, launch_spec=spec, program_identity=identity(program),
                cache_root=cache, cache_identity=identity(cache), custody_root=custody, limits=limits, gpu_binding=gpu,
                device_observer=device, preparation=prep['preparation'], preparation_task_id=prep_task,
                preparation_artifact_id=prep_artifact, prior_targets=prior['settings'].remote_targets,
                prior_adapters=prior['settings'].runtime_adapters, prior_pricing=prior['settings'].usage_pricing,
                training_store=training_store, training=training, microbatch=config['microbatch'],
                bounds_profile=inventory['captureKwargs']['bounds_profile']))
            progress.at(stage.upper() + '_STARTUP')
            with TestClient(bundle['app']) as client:
                try:
                    progress.at(stage.upper() + '_PUBLICATION')
                    reviewer = ensure_task_development_reviewer(bundle['state'])
                    app = publish_research_application(bundle['state'], target_ref=stage,
                        comparison_manifest=captured['comparisonManifest'], author='manager', reviewer=reviewer,
                        adapter_suffix='-evaluation' if stage == 'evaluation' else '')
                    assert client.portal is not None
                    portal = client.portal
                    def imported(owner, task, lease):
                        if stage == 'training':
                            artifact = bundle['checkpoints'].import_completed(owner, lease['id'])
                            _, checked = bundle['checkpoints'].identity(task['id'], artifact['id'], limits.file_size_bytes)
                            plan = bundle['state']['store'].plan(task['plan_id'], owner)
                            return {**{key: lease[field] for key, field in (('ownerId', 'ownerId'), ('taskId', 'localTaskId'),
                                ('nativeRunId', 'nativeRunId'), ('planId', 'planId'), ('leaseId', 'id'), ('providerJobId', 'providerJobId'))},
                                'planFingerprint': plan['fingerprint'], 'variantSha256': lease['executionGuard']['variantSha256'],
                                'checkpoint': {'artifactId': artifact['id'], **checked}}
                        return portal.call(bundle['state']['store'].research_evaluation.verify,
                            owner, bundle['pending']['evaluationContract'])
                    progress.at(stage.upper() + '_RUN')
                    result = ResearchBootstrapController(bundle['state'], request_client(bundle, client), portal.call).run(
                        owner='alice', reviewer=reviewer, application_ref={k: app[k] for k in ('id', 'version', 'sha256')},
                        goal='Source-bound baseline' if stage == 'training' else 'Independent checkpoint evaluation',
                        request_id=config['requestId'] + ':' + stage, timeout_seconds=int(min(86400, limits.wall_seconds + 120)),
                        after_reclaimed=imported, on_progress=lambda value: progress.record(stage, value))
                    progress.at(stage.upper() + '_RECEIPT')
                    results[stage] = result
                    write_private(workspace / (stage + '-receipt.json'), canonical(result))
                    if stage == 'training':
                        training, training_store = result['imported'], bundle['checkpoints']
                except BaseException as error:
                    progress.capture(error)
                    raise
                finally:
                    progress.at(stage.upper() + '_SHUTDOWN')
            prior = bundle
        return results
    except BaseException as error:
        progress.capture(error)
        raise
    finally:
        progress.at('CLEANUP')
        for bundle in reversed(bundles):
            for store in (bundle['state']['store'], bundle['providerStore']):
                store.dispose_root_locks(); store.engine.dispose()
                native = getattr(store, 'native_db', None)
                if native is not None:
                    native.db_engine.dispose()


def preparation_preflight(raw_config):
    """Read-only local checks. Never opens the DSN or constructs an application."""
    from agent_factory.research_config_preflight import config_preflight
    parsed = config_preflight(raw_config)
    checks = list(parsed['checks'])
    config = parsed['config'] or {}
    valid = parsed['validFields']
    def add(field, status, code):
        checks.append({'field': field, 'status': status, 'code': code})
    def check(field, action):
        try:
            action()
        except Exception as error:
            add(field, 'BLOCKED', exception_code(error))
        else:
            add(field, 'PASS', 'VALID')
    if {'inputRoot', 'tokenizerBasename'} <= valid:
        try:
            raw = read_private(Path(config['inputRoot']) / config['tokenizerBasename'], 1024**2)
        except Exception as error:
            add('TOKENIZER_FILE', 'BLOCKED', exception_code(error))
            add('TOKENIZER_CONTENT', 'NOT_CHECKED', 'DEPENDENCY_BLOCKED')
        else:
            add('TOKENIZER_FILE', 'PASS', 'VALID')
            try:
                from agent_factory.research_preparation_preflight import tokenizer_preflight
                checks.extend(tokenizer_preflight(raw)['checks'])
            except Exception as error:
                add('TOKENIZER_VALIDATOR', 'BLOCKED', exception_code(error))
    else:
        add('TOKENIZER_CONTENT', 'NOT_CHECKED', 'DEPENDENCY_BLOCKED')
    if {'workspace', 'interpreterTarget', 'interpreterSha256'} <= valid:
        def process_spec():
            from agent_factory.process_enforcement import ProcessSpec
            program = Path(config['workspace']) / 'preparation-program'
            ProcessSpec(config['interpreterTarget'], config['interpreterSha256'],
                        ('-I', '-B', str(program / 'prepare.py'), str(program / 'run-config.json')))
        check('PREPARATION_PROCESS_SPEC', process_spec)
    else:
        add('PREPARATION_PROCESS_SPEC', 'NOT_CHECKED', 'DEPENDENCY_BLOCKED')
    check('PLATFORM', lambda: require(sys.platform == 'linux'))
    try:
        from agent_factory.research_preparation_driver import _FILES
        import agent_factory
    except Exception as error:
        add('RUNTIME_SOURCE_CLOSURE', 'BLOCKED', exception_code(error))
    else:
        package = Path(agent_factory.__file__).parent
        for name in _FILES:
            # Fixed source names only. Bounded, nonblocking, nofollow file read.
            check('SOURCE_' + name.replace('.py', '').upper(),
                  lambda name=name: read_private(package / name, 2 * 1024**2, private=False))
    if 'workspace' in valid:
        for label, path in (('PROGRAM_DIRECTORY', Path(config['workspace']) / 'preparation-program'),
                            ('CUSTODY_DIRECTORY', Path(config['workspace']) / 'preparation-custody')):
            try:
                exists = path.exists() or path.is_symlink()
            except Exception as error:
                add(label, 'BLOCKED', exception_code(error))
                continue
            if exists:
                check(label, lambda path=path: identity(path))
            else:
                add(label, 'NOT_CHECKED', 'NOT_CREATED')
    else:
        for label in ('PROGRAM_DIRECTORY', 'CUSTODY_DIRECTORY'):
            add(label, 'NOT_CHECKED', 'DEPENDENCY_BLOCKED')
    # Check parity with the canonical schema without using it as an early gate.
    check('CANONICAL_CONFIG_AUTHORITY', lambda: config_from_bytes(raw_config))
    add('DATABASE_AND_APPLICATION', 'NOT_CHECKED', 'REQUIRES_EXECUTION')
    add('RUNTIME_ADMISSION', 'NOT_CHECKED', 'REQUIRES_EXECUTION')
    return {'schema': 1, 'kind': 'RESEARCH_PREPARATION_PREFLIGHT',
            'status': 'BLOCKED' if any(row['status'] == 'BLOCKED' for row in checks) else 'CHECKED_FIELDS_PASS',
            'executionVerified': False, 'checks': checks}


def main(argv=None, *, run=execute):
    old_logging = logging.root.manager.disable
    progress = None
    diagnostics = Diagnostics()
    try:
        args = sys.argv[1:] if argv is None else argv
        mode = args[0] if len(args) == 3 and args[0] in {'--preflight', '--database-preflight', '--assembly-only'} else None
        preflight = mode == '--preflight'
        if mode is not None:
            args = args[1:]
        require(len(args) == 2 and args[0] == '--config')
        diagnostics.at('CONFIG_READ')
        raw = read_private(args[1])
        diagnostics.at('CONFIG_VALIDATE')
        if preflight:
            diagnostics.at('PREFLIGHT')
            logging.disable(logging.CRITICAL)
            with warnings.catch_warnings(), open(os.devnull, 'w') as sink, \
                    redirect_stdout(sink), redirect_stderr(sink):
                warnings.simplefilter('ignore')
                report = preparation_preflight(raw)
            print(json.dumps(report, sort_keys=True, separators=(',', ':')))
            return 2 if report['status'] == 'BLOCKED' else 0
        config = config_from_bytes(raw)
        if mode == '--database-preflight':
            diagnostics.at('DATABASE_PREFLIGHT')
            logging.disable(logging.CRITICAL)
            with warnings.catch_warnings(), open(os.devnull, 'w') as sink, \
                    redirect_stdout(sink), redirect_stderr(sink):
                warnings.simplefilter('ignore')
                report = database_report(config)
            print(json.dumps(report, sort_keys=True, separators=(',', ':')))
            return 2 if report['status'] == 'BLOCKED' else 0
        if mode == '--assembly-only':
            diagnostics.at('EXECUTION_IDENTITY')
            logging.disable(logging.CRITICAL)
            with warnings.catch_warnings(), open(os.devnull, 'w') as sink, \
                    redirect_stdout(sink), redirect_stderr(sink):
                warnings.simplefilter('ignore')
                runtime_identity(config)
        from bootstrap_research_control import _workspace
        diagnostics.at('WORKSPACE_INSPECT')
        workspace = Path(config['workspace'])
        if workspace.exists() or workspace.is_symlink():
            require(mode != '--assembly-only')
            identity(workspace)  # Read-only recovery; never create/restart another batch.
            print('RESEARCH_BASELINE_EXISTING_INSPECT_ONLY')
            return 0
        diagnostics.at('WORKSPACE_CREATE')
        _workspace(str(workspace), create=True)
        progress = Progress(workspace, diagnostics)
        diagnostics.at('PROGRESS_START')
        progress.record('controller', {'phase': 'STARTED', 'requestId': config['requestId']})
        logging.disable(logging.CRITICAL)
        diagnostics.at('EXECUTE')
        # Import warnings can include source paths; keep the public failure
        # channel limited to the fixed diagnostic below. No dependency import here.
        with warnings.catch_warnings(), open(os.devnull, 'w') as sink, \
                redirect_stdout(sink), redirect_stderr(sink):
            warnings.simplefilter('ignore')
            if mode == '--assembly-only':
                assemble_only(config, workspace, progress)
            else:
                run(config, workspace, progress)
        if mode == '--assembly-only':
            diagnostics.at('PROGRESS_COMPLETE')
            progress.record('controller', {'phase': 'ASSEMBLY_CHECKED', 'executionVerified': False})
            print('RESEARCH_PREPARATION_ASSEMBLED_NO_EXECUTION')
            return 0
        diagnostics.at('PROGRESS_COMPLETE')
        progress.record('controller', {'phase': 'COMPLETED', 'scientificConclusionVerified': False})
        print('RESEARCH_BASELINE_COMPLETED_PRIVATE_EVIDENCE')
        return 0
    except BaseException as error:
        diagnostics.capture(error)
        if progress is not None:
            try:
                diagnostics.at('PROGRESS_STOPPED')
                progress.record('controller', {'phase': 'STOPPED', 'cleanupConfirmed': False})
            except BaseException as journal_error:
                diagnostics.capture(journal_error)
        print(ERROR, file=sys.stderr)
        diagnostics.emit()
        return 2
    finally:
        logging.disable(old_logging)


if __name__ == '__main__':
    raise SystemExit(main())
