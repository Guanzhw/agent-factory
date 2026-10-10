"""Versioned original-ORX runtime entry; importing or building does not launch.

Only an ephemeral local broker capability enters the container. Real provider
credentials remain in the host Factory broker. No Docker socket is mounted.
"""
from dataclasses import dataclass, field
from contextlib import closing
from copy import deepcopy
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sqlite3
import time
import subprocess
import sys
from uuid import UUID, uuid4
from typing import Any, cast

ERROR = 'PLATFORM_ORX_RUNTIME_UNCONFIRMED'
BUILTINS = ('bash', 'edit', 'write', 'read', 'glob', 'grep', 'list', 'task', 'skill', 'lsp',
            'webfetch', 'websearch', 'codesearch', 'question', 'todowrite', 'todoread',
            'external_directory', 'doom_loop', 'apply_patch', 'multiedit', 'batch')
LOCAL_TOOLS = ('bash', 'edit', 'write', 'read', 'glob', 'grep', 'list', 'apply_patch', 'multiedit')
PERMISSIONS = {'*': 'deny', **{name: 'deny' for name in BUILTINS}, **{name: 'allow' for name in LOCAL_TOOLS}}


def require(value):
    if not value:
        raise ValueError(ERROR)


def private_directory(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == getattr(os, 'getuid')())
    return path


@dataclass(frozen=True)
class BinaryPin:
    path: str
    sha256: str

    def verify(self):
        require(re.fullmatch('[a-f0-9]{64}', self.sha256) is not None)
        path = Path(self.path)
        require(path.is_absolute() and path.resolve() == path)
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 1024**3
                and info.st_mode & 0o111 and not info.st_mode & 0o022)
        with path.open('rb') as handle:
            before = os.fstat(handle.fileno())
            actual = hashlib.file_digest(handle, 'sha256').hexdigest()
            after = os.fstat(handle.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                and actual == self.sha256 and path.stat().st_ino == before.st_ino)


@dataclass(frozen=True)
class RuntimeConfig:
    session_root: str
    image: str
    orx: BinaryPin
    opencode: BinaryPin
    cpus: int = 1
    memory_mb: int = 1024
    pids: int = 64
    wall_seconds: int = 300
    max_output_tokens: int = 512
    project_id: str = field(default_factory=lambda: str(uuid4()))

    def validate(self):
        require(sys.platform == 'linux')
        private_directory(self.session_root)
        require(getattr(os, 'getuid')() > 0 and getattr(os, 'getgid')() > 0)
        require(re.fullmatch(r'sha256:[a-f0-9]{64}', self.image) is not None)
        require(type(self.cpus) is int and 1 <= self.cpus <= 4
                and type(self.memory_mb) is int and 256 <= self.memory_mb <= 4096
                and type(self.pids) is int and 16 <= self.pids <= 256
                and type(self.wall_seconds) is int and 1 <= self.wall_seconds <= 3600)
        require(type(self.max_output_tokens) is int and 1 <= self.max_output_tokens <= 4096)
        require(str(UUID(self.project_id)) == self.project_id)
        self.orx.verify(); self.opencode.verify()


def opencode_config(capability, max_output_tokens=512):
    require(type(max_output_tokens) is int and 1 <= max_output_tokens <= 4096)
    require(type(capability) is str and re.fullmatch('[A-Za-z0-9_-]{24,128}', capability) is not None)
    # The pinned harness translates legacy tools into permissions before merging.
    # Repeating those keys can move '*' behind the specific allow rules and
    # disable every tool. Use the native permission contract only.
    agent = {'model': 'factory/owner-model', 'permission': PERMISSIONS}
    return {'$schema': 'https://opencode.ai/config.json', 'model': 'factory/owner-model', 'small_model': 'factory/owner-model',
        'default_agent': 'factory', 'enabled_providers': ['factory'], 'autoupdate': False, 'share': 'disabled',
        'plugin': [], 'lsp': False, 'formatter': False, 'permission': PERMISSIONS,
        'agent': {'factory': {**agent, 'mode': 'primary'}, 'build': agent, 'plan': agent,
                  'explore': {'disable': True}, 'general': {'disable': True}, 'title': {'disable': True}},
        'provider': {'factory': {'npm': '@ai-sdk/openai-compatible', 'name': 'Owner model broker',
            'options': {'baseURL': 'http://127.0.0.1:4801/v1', 'apiKey': capability},
            'models': {'owner-model': {'name': 'Owner selected model', 'limit': {'context': 32768, 'output': max_output_tokens}}}}},
        'mcp': {}}


def verify_effective_config(value, expected):
    """Fail closed on permission merges, provider fallbacks, plugins or extra MCP."""
    require(type(value) is dict)
    require(expected == opencode_config(expected['provider']['factory']['options']['apiKey'],
        expected['provider']['factory']['models']['owner-model']['limit']['output']))
    value = deepcopy(value)
    # Pinned OpenCode 1.18.35 debug config redacts the local capability as ***.
    # This checks routing/policy; actual capability authentication is broker-owned.
    current = value.get('provider', {}).get('factory', {}).get('options', {})
    if current.get('apiKey') == '***':
        current['apiKey'] = expected['provider']['factory']['options']['apiKey']
    for key in ('model', 'small_model', 'default_agent', 'enabled_providers', 'autoupdate', 'share',
                'plugin', 'lsp', 'formatter', 'provider', 'mcp'):
        require(value.get(key) == expected[key])
    def permissions(rules):
        require(type(rules) is dict and rules.get('*') == 'deny')
        require(all(action == ('allow' if name in LOCAL_TOOLS else 'deny') for name, action in rules.items()))
        require(all(rules.get(name) == ('allow' if name in LOCAL_TOOLS else 'deny') for name in BUILTINS))
    permissions(value.get('permission'))
    # ORX adds a legacy question:false entry. It may only remove capability.
    require(all(enabled is False for enabled in value.get('tools', {}).values()))
    agents = value.get('agent')
    require(type(agents) is dict and 'factory' in agents)
    configured_agents = cast(dict[str, Any], agents)
    # OpenCode 1.18.35 otherwise forks its own title generation (with retries),
    # independently of the outer ORX session title. Require explicit disable in
    # debug config: an absent override would leave the built-in title agent active.
    title = configured_agents.get('title')
    require(type(title) is dict and title.get('disable') is True)
    for agent in configured_agents.values():
        require(type(agent) is dict)
        if agent.get('disable') is True:
            continue
        permissions(agent.get('permission'))
        require(agent.get('model', 'factory/owner-model') == 'factory/owner-model')
    return {'schema': 1, 'effectiveConfigVerified': True, 'localToolsOnly': True,
            'externalToolsDenied': True, 'titleAgentDisabled': True}


def verify_effective_agent(value, name):
    """Check final ordered rules and executable tools, not just config values."""
    require(type(value) is dict and value.get('name') == name
        and value.get('model') == {'providerID': 'factory', 'modelID': 'owner-model'})
    rules, tools = value.get('permission'), value.get('tools')
    require(type(rules) is list and type(tools) is dict)
    rules = cast(list[dict[str, Any]], rules)
    tools = cast(dict[str, bool], tools)
    def allowed(permission):
        matching = [rule for rule in rules if type(rule) is dict
            and type(rule.get('permission')) is str and fnmatchcase(permission, rule['permission'])]
        return bool(matching and matching[-1].get('pattern') == '*' and matching[-1].get('action') == 'allow')
    require(not allowed('unlisted-runtime-tool'))
    require(all(allowed(tool) is (tool in LOCAL_TOOLS) for tool in BUILTINS))
    require(all(type(enabled) is bool and (not enabled or tool in LOCAL_TOOLS and allowed(tool))
        for tool, enabled in tools.items()))
    require(all(tools.get(tool) is True for tool in ('bash', 'read', 'glob', 'grep', 'edit', 'write')))
    return {'agent': name, 'effectiveToolsVerified': True,
        'enabledTools': sorted(tool for tool, enabled in tools.items() if enabled)}


def opencode_wrapper(argv):
    binary = '/trusted/opencode-real'
    if argv == ['--version']:
        os.execv(binary, [binary, '--version'])
    require(bool(argv) and argv[0] == 'serve')
    expected = json.loads(os.environ['OPENCODE_CONFIG_CONTENT'])
    # debug config runs with the exact cwd/env ORX supplies to its actual child,
    # including its generated permissive config. No prompt/model call occurs.
    result = subprocess.run([binary, 'debug', 'config'], capture_output=True, timeout=30, check=False)
    require(result.returncode == 0 and len(result.stdout) <= 2 * 1024**2)
    proof = verify_effective_config(json.loads(result.stdout), expected)
    proof['agents'] = []
    for name in ('factory', 'build', 'plan'):
        agent = subprocess.run([binary, 'debug', 'agent', name], capture_output=True, timeout=30, check=False)
        require(agent.returncode == 0 and len(agent.stdout) <= 2 * 1024**2)
        proof['agents'].append(verify_effective_agent(json.loads(agent.stdout), name))
    directory = private_directory('/session/proofs')
    with (directory / (uuid4().hex + '.json')).open('x') as handle:
        json.dump(proof, handle, sort_keys=True)
    os.execv(binary, [binary, *argv])


def environment(capability, max_output_tokens=512):
    return {'PATH': '/trusted:/usr/local/bin:/usr/bin:/bin', 'HOME': '/session/home',
        'XDG_CONFIG_HOME': '/session/xdg/config', 'XDG_DATA_HOME': '/session/xdg/data',
        'XDG_CACHE_HOME': '/session/xdg/cache', 'XDG_STATE_HOME': '/session/xdg/state',
        'ORX_DATA_DIR': '/session/orx', 'ORX_CACHE_DIR': '/session/cache', 'ORX_NO_UPDATE_CHECK': '1',
        'ORX_TELEMETRY_ENV': 'off', 'OPENCODE_CONFIG_CONTENT': json.dumps(opencode_config(capability, max_output_tokens), separators=(',', ':')),
        **{key: '1' for key in ('OPENCODE_DISABLE_AUTOUPDATE', 'OPENCODE_DISABLE_MODELS_FETCH',
            'OPENCODE_DISABLE_DEFAULT_PLUGINS', 'OPENCODE_DISABLE_LSP_DOWNLOAD', 'OPENCODE_DISABLE_AUTOCOMPACT',
            'OPENCODE_DISABLE_CLAUDE_CODE', 'OPENCODE_DISABLE_EXTERNAL_SKILLS', 'OPENCODE_DISABLE_PROJECT_CONFIG',
            'OPENCODE_CONFIG_PROJECT_DISABLE')}, 'NO_COLOR': '1', 'DO_NOT_TRACK': '1'}


def build_command(config, name, capability):
    config.validate()
    require(re.fullmatch('factory-orx-[a-f0-9]{32}', name) is not None)
    base = Path(__file__).resolve().parent
    command = ['docker', 'create', '--pull', 'never', '--name', name, '--label', 'factory.orx.runtime=' + name,
        '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--user', str(getattr(os, 'getuid')()) + ':' + str(getattr(os, 'getgid')()), '--cpus', str(config.cpus),
        '--memory', str(config.memory_mb) + 'm', '--memory-swap', str(config.memory_mb) + 'm',
        '--pids-limit', str(config.pids), '--ulimit', 'nofile=1024:1024',
        '--log-driver', 'local', '--log-opt', 'max-size=1m', '--log-opt', 'max-file=2',
        '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777', '--workdir', '/session/work']
    for source, destination, readonly in ((config.session_root, '/session', False),
            (config.orx.path, '/trusted/orx', True), (config.opencode.path, '/trusted/opencode-real', True),
            (str(base / 'bridge.py'), '/trusted/opencode', True),
            (str(base / 'bridge.py'), '/trusted/bridge.py', True),
            (str(base / 'entry.py'), '/trusted/entry.py', True)):
        require(',' not in source and '\n' not in source)
        command += ['--mount', f'type=bind,src={source},dst={destination}' + (',readonly' if readonly else '')]
    for key in (*environment(capability), 'ORX_FACTORY_PROJECT_ID'):
        command += ['--env', key]  # Values passed privately through subprocess environment, never argv.
    return command + [config.image, '/usr/local/bin/python3', '-I', '-B', '/trusted/entry.py', '--container']


def bootstrap_project(root, project_id):
    """Initialize only a fresh pinned native store without a paid warmup.

    ORX f336b121's POST projects unconditionally starts a model warmup; its CLI
    has no create-project command. Initialize native schema through projects,
    then insert its exact LocalProject shape before the API starts. Never adopt
    an existing database or fabricate experiment/session/run history.
    """
    require(str(UUID(project_id)) == project_id)
    root = private_directory(root)
    database = root / 'orx/orx.db'
    work = private_directory(root / 'work')
    if not database.exists():
        initialized = subprocess.run(['/trusted/orx', 'projects', '--json'],
                                     capture_output=True, timeout=30, check=False)
        require(initialized.returncode == 0 and json.loads(initialized.stdout) == [])
    require(database.is_file() and not database.is_symlink())
    expected = ['id', 'name', 'slug', 'github_owner', 'github_repo', 'github_sync_enabled',
                'baseline_branch', 'repo_path', 'run_command', 'paper_id', 'created_at',
                'updated_at', 'workspace_state_json']
    with closing(sqlite3.connect(database)) as connection, connection:
        require([row[1] for row in connection.execute('PRAGMA table_info(local_projects)')] == expected)
        projects = connection.execute('SELECT id, repo_path FROM local_projects').fetchall()
        if projects:
            require(projects == [(project_id, str(work))])
            return project_id
        require(connection.execute('SELECT COUNT(*) FROM local_experiments').fetchone()[0] == 0)
        # Recover only this package's blank initialization, including interruption
        # between native schema creation, git init and project insertion. Never
        # truncate a database/repository or adopt an unrelated native project.
        require(set(path.name for path in work.iterdir()) <= {'.git'})
        if not (work / '.git').exists():
            result = subprocess.run(['git', 'init', '--initial-branch=main', str(work)],
                                    capture_output=True, timeout=15, check=False)
            require(result.returncode == 0)
        require(not (work / '.git').is_symlink())
        top = subprocess.run(['git', '-C', str(work), 'rev-parse', '--show-toplevel'],
                             capture_output=True, timeout=15, check=False)
        require(top.returncode == 0 and top.stdout.decode().strip() == str(work))
        head = subprocess.run(['git', '-C', str(work), 'rev-parse', '--verify', 'HEAD'],
                              capture_output=True, timeout=15, check=False)
        if head.returncode != 0:
            committed = subprocess.run(['git', '-C', str(work), '-c', 'user.name=Factory',
                '-c', 'user.email=factory@localhost.invalid', 'commit', '--allow-empty', '--no-gpg-sign',
                '-m', 'Factory isolated research workspace'], capture_output=True, timeout=15, check=False)
            require(committed.returncode == 0)
        now = int(time.time() * 1000)
        connection.execute('INSERT INTO local_projects (' + ','.join(expected[:12])
                           + ') VALUES (' + ','.join('?' for _ in range(12)) + ')',
                           (project_id, 'Factory isolated research', 'factory-research', '', '',
                            0, 'main', str(work), None, None, now, now))
    return project_id


def verify_no_startup_dispatch(database):
    """Pinned ORX up resumes queues/runs. Inspect only; never clear their custody."""
    database = Path(database)
    if not database.exists(): return
    require(database.is_file() and not database.is_symlink())
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        required = {'chat_queued_messages': {'id', 'session_id', 'payload_json'},
            'chat_turns': {'id', 'state'},
            'runs': {'id', 'status'}, 'chat_run_wakeups': {'run_id', 'state'},
            'chat_spawns': {'session_id', 'state'}}
        for table, columns in required.items():
            require(columns <= {row[1] for row in connection.execute('PRAGMA table_info(' + table + ')')})
        require(connection.execute('SELECT COUNT(*) FROM chat_queued_messages').fetchone()[0] == 0)
        require(connection.execute("SELECT COUNT(*) FROM chat_turns WHERE state NOT IN ('completed','failed','cancelled')").fetchone()[0] == 0)
        require(connection.execute("SELECT COUNT(*) FROM runs WHERE status NOT IN ('done','failed','cancelled')").fetchone()[0] == 0)
        require(connection.execute("SELECT COUNT(*) FROM chat_run_wakeups WHERE state != 'delivered'").fetchone()[0] == 0)
        require(connection.execute("SELECT COUNT(*) FROM chat_spawns WHERE state != 'done'").fetchone()[0] == 0)


def container_main():
    os.umask(0o077)
    root = Path('/session')
    bootstrap_project(root, os.environ['ORX_FACTORY_PROJECT_ID'])
    verify_no_startup_dispatch(root / 'orx/orx.db')
    bridge = subprocess.Popen(['/usr/local/bin/python3', '-I', '-B', '/trusted/bridge.py', '--bridge'])
    try:
        result = subprocess.run(['/trusted/orx', 'up', '--no-browser', '--port', '4791', '--model', 'factory/owner-model'], check=False)
        return result.returncode
    finally:
        bridge.terminate()
        try:
            bridge.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bridge.kill(); bridge.wait(timeout=5)


if __name__ == '__main__':
    require(sys.argv[1:] == ['--container'])
    raise SystemExit(container_main())
