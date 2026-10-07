"""Task-private ORX/OpenCode Docker wiring; importing or building does not launch.

Only an ephemeral local broker capability enters the container. Real provider
credentials remain in the host Factory broker. No Docker socket is mounted.
"""
from dataclasses import dataclass, field
from copy import deepcopy
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
import threading
from uuid import UUID, uuid4
from typing import Any, cast

ERROR = 'ORX_RESEARCH_RUNTIME_UNCONFIRMED'
BUILTINS = ('bash', 'edit', 'write', 'read', 'glob', 'grep', 'list', 'task', 'skill', 'lsp',
            'webfetch', 'websearch', 'codesearch', 'question', 'todowrite', 'todoread',
            'external_directory', 'doom_loop', 'apply_patch', 'multiedit', 'batch')
PERMISSIONS = {'*': 'deny', **{name: 'deny' for name in BUILTINS}, 'factory_*': 'allow'}


def require(value):
    if not value:
        raise ValueError(ERROR)


def private_directory(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid())
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
        private_directory(self.session_root)
        require(os.getuid() > 0 and os.getgid() > 0)
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
    agent = {'model': 'factory/deepseek-flash', 'permission': PERMISSIONS, 'tools': {name: False for name in BUILTINS}}
    return {'$schema': 'https://opencode.ai/config.json', 'model': 'factory/deepseek-flash', 'small_model': 'factory/deepseek-flash',
        'default_agent': 'factory', 'enabled_providers': ['factory'], 'autoupdate': False, 'share': 'disabled',
        'plugin': [], 'lsp': False, 'formatter': False, 'permission': PERMISSIONS,
        'tools': {name: False for name in BUILTINS},
        'agent': {'factory': {**agent, 'mode': 'primary'}, 'build': agent, 'plan': agent,
                  'explore': {'disable': True}, 'general': {'disable': True}, 'title': {'disable': True}},
        'provider': {'factory': {'npm': '@ai-sdk/openai-compatible', 'name': 'Factory bounded broker',
            'options': {'baseURL': 'http://127.0.0.1:4801/v1', 'apiKey': capability},
            'models': {'deepseek-flash': {'name': 'Factory bounded model', 'limit': {'context': 32768, 'output': max_output_tokens}}}}},
        'mcp': {'factory': {'type': 'remote', 'url': 'http://127.0.0.1:4801/mcp', 'oauth': False,
                            'headers': {'Authorization': 'Bearer ' + capability}}}}


def verify_effective_config(value, expected):
    """Fail closed on permission merges, provider fallbacks, plugins or extra MCP."""
    require(type(value) is dict)
    require(expected == opencode_config(expected['provider']['factory']['options']['apiKey'],
        expected['provider']['factory']['models']['deepseek-flash']['limit']['output']))
    value = deepcopy(value)
    # Pinned OpenCode 1.18.35 debug config redacts these two secrets as ***.
    # This checks routing/policy; actual capability authentication is broker-owned.
    for group, section, name in (('provider', 'options', 'apiKey'), ('mcp', 'headers', 'Authorization')):
        current = value.get(group, {}).get('factory', {}).get(section, {})
        if current.get(name) == '***':
            current[name] = expected[group]['factory'][section][name]
    for key in ('model', 'small_model', 'default_agent', 'enabled_providers', 'autoupdate', 'share',
                'plugin', 'lsp', 'formatter', 'provider', 'mcp'):
        require(value.get(key) == expected[key])
    def permissions(rules):
        require(type(rules) is dict and rules.get('*') == 'deny' and rules.get('factory_*') == 'allow')
        require(all(action == 'deny' or name == 'factory_*' and action == 'allow' for name, action in rules.items()))
        require(all(rules.get(name) == 'deny' for name in BUILTINS))
    permissions(value.get('permission'))
    require(all(value.get('tools', {}).get(name) is False for name in BUILTINS))
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
        require(agent.get('model', 'factory/deepseek-flash') == 'factory/deepseek-flash')
    return {'schema': 1, 'effectiveConfigVerified': True, 'builtinsDenied': True,
            'factoryMcpOnly': True, 'titleAgentDisabled': True}


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
        '--user', str(os.getuid()) + ':' + str(os.getgid()), '--cpus', str(config.cpus),
        '--memory', str(config.memory_mb) + 'm', '--memory-swap', str(config.memory_mb) + 'm',
        '--pids-limit', str(config.pids), '--ulimit', 'nofile=1024:1024',
        '--log-driver', 'local', '--log-opt', 'max-size=1m', '--log-opt', 'max-file=2',
        '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777', '--workdir', '/session/work']
    for source, destination, readonly in ((config.session_root, '/session', False),
            (config.orx.path, '/trusted/orx', True), (config.opencode.path, '/trusted/opencode-real', True),
            (str(base / 'orx_research_socket_bridge.py'), '/trusted/opencode', True),
            (str(base / 'orx_research_socket_bridge.py'), '/trusted/orx_research_socket_bridge.py', True),
            (str(base / 'orx_research_runtime.py'), '/trusted/orx_research_runtime.py', True)):
        require(',' not in source and '\n' not in source)
        command += ['--mount', f'type=bind,src={source},dst={destination}' + (',readonly' if readonly else '')]
    for key in (*environment(capability), 'ORX_FACTORY_PROJECT_ID'):
        command += ['--env', key]  # Values passed privately through subprocess environment, never argv.
    return command + [config.image, '/usr/local/bin/python3', '-I', '-B', '/trusted/orx_research_runtime.py', '--container']


class Runtime:
    def __init__(self, config):
        self.config, self.name, self.container_id = config, 'factory-orx-' + uuid4().hex, None
        self.timer = None
        self._reclaim_receipt = None
        self._lock = threading.Lock()

    def start(self, capability):
        require(self.container_id is None)
        root = private_directory(self.config.session_root)
        require(set(path.name for path in root.iterdir()) <= {'sockets'})
        sockets = private_directory(root / 'sockets')
        socket = sockets / 'broker.sock'
        info = socket.lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600)
        for name in ('home', 'work', 'orx', 'cache', 'proofs', 'xdg'):
            (root / name).mkdir(mode=0o700)
        for name in ('config', 'data', 'cache', 'state'):
            (root / 'xdg' / name).mkdir(mode=0o700)
        command = build_command(self.config, self.name, capability)
        env = environment(capability, self.config.max_output_tokens)
        env['ORX_FACTORY_PROJECT_ID'] = self.config.project_id
        env['PATH'] = '/usr/local/bin:/usr/bin:/bin'
        # Container PATH remains the declared value via an explicit env option.
        index = command.index('PATH', command.index('--env'))
        command[index] = 'PATH=' + environment(capability)['PATH']
        result = subprocess.run(command, env=env, capture_output=True, timeout=60, check=False)
        require(result.returncode == 0)
        identifier = result.stdout.decode().strip()
        require(re.fullmatch('[a-f0-9]{64}', identifier) is not None)
        self.container_id = identifier
        self.timer = threading.Timer(self.config.wall_seconds, self.stop)
        self.timer.daemon = True
        self.timer.start()
        try:
            started = subprocess.run(['docker', 'start', identifier], env=self._docker_env(), capture_output=True, timeout=30, check=False)
            require(started.returncode == 0)
        except BaseException:
            self.stop()
            raise
        return {'containerId': identifier, 'orxSocket': str(root / 'sockets/orx.sock'), 'projectId': self.config.project_id, 'liveVerified': False}

    def _docker_env(self):
        return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(Path(self.config.session_root) / 'home')}

    def stop(self):
        with self._lock:
            if self.timer is not None:
                self.timer.cancel()
            if self.container_id is None:
                return {'stopped': False, 'status': 'UNKNOWN'}
            try:
                subprocess.run(['docker', 'stop', '--time', '5', self.container_id],
                               env=self._docker_env(), capture_output=True, timeout=15, check=False)
                result = subprocess.run(['docker', 'inspect', self.container_id], env=self._docker_env(), capture_output=True, timeout=10, check=False)
                require(result.returncode == 0)
                rows = json.loads(result.stdout)
                require(len(rows) == 1 and rows[0]['Id'] == self.container_id
                        and rows[0]['Config']['Labels']['factory.orx.runtime'] == self.name)
                state = rows[0]['State']
                require(state['Running'] is False and state['Paused'] is False and state['Dead'] is False
                        and state['Status'] == 'exited' and type(state['ExitCode']) is int
                        and state['FinishedAt'] not in ('', '0001-01-01T00:00:00Z'))
                return {'stopped': True, 'status': 'STOPPED', 'containerId': self.container_id,
                        'exitCode': state['ExitCode'], 'finishedAt': state['FinishedAt'], 'proofKind': 'docker-state-exited'}
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
                return {'stopped': False, 'status': 'UNKNOWN', 'containerId': self.container_id}

    def reclaim(self):
        """Remove only this exact stopped owned container, after caller saves stop proof."""
        with self._lock:
            if self._reclaim_receipt is not None:
                return dict(self._reclaim_receipt)
            unknown = {'reclaimed': False, 'containerId': self.container_id, 'status': 'UNKNOWN'}
            if self.container_id is None:
                return unknown
            try:
                result = subprocess.run(['docker', 'inspect', self.container_id], env=self._docker_env(),
                                        capture_output=True, timeout=10, check=False)
                require(result.returncode == 0)
                rows = json.loads(result.stdout)
                require(len(rows) == 1 and rows[0]['Id'] == self.container_id
                        and rows[0]['Config']['Labels']['factory.orx.runtime'] == self.name)
                state = rows[0]['State']
                require(state['Running'] is False and state['Paused'] is False and state['Dead'] is False)
                require(state['Status'] == 'exited' and type(state['ExitCode']) is int
                        and state['FinishedAt'] not in ('', '0001-01-01T00:00:00Z')
                        or state['Status'] == 'created' and state['StartedAt'] == '0001-01-01T00:00:00Z'
                        and state['FinishedAt'] == '0001-01-01T00:00:00Z')
                removed = subprocess.run(['docker', 'rm', self.container_id], env=self._docker_env(),
                                         capture_output=True, timeout=60, check=False)
                require(removed.returncode == 0 and removed.stdout.decode().strip() == self.container_id)
                receipt = {'reclaimed': True, 'containerId': self.container_id,
                           'status': 'RECLAIMED', 'proofKind': 'docker-rm-exact-owned-container'}
                self._reclaim_receipt = receipt
                return dict(receipt)
            except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
                return unknown


def bootstrap_project(root, project_id):
    """Only a fresh, pinned ORX store: create a blank local project without warmup.

    ORX f336b121's POST projects unconditionally starts a model warmup; its CLI
    has no create-project command. Initialize native schema through projects,
    then insert its exact LocalProject shape before the API starts. Never adopt
    an existing database or fabricate experiment/session/run history.
    """
    require(str(UUID(project_id)) == project_id)
    root = private_directory(root)
    database = root / 'orx/orx.db'
    work = private_directory(root / 'work')
    require(not database.exists() and not any(work.iterdir()))
    initialized = subprocess.run(['/trusted/orx', 'projects', '--json'],
                                 capture_output=True, timeout=30, check=False)
    require(initialized.returncode == 0 and json.loads(initialized.stdout) == [])
    require(database.is_file() and not database.is_symlink())
    # Empty commit supports ORX's own later private worktree creation.
    for command in (['git', 'init', '--initial-branch=main', str(work)],
                    ['git', '-C', str(work), '-c', 'user.name=Factory',
                     '-c', 'user.email=factory@localhost.invalid', 'commit',
                     '--allow-empty', '--no-gpg-sign', '-m', 'Factory isolated research workspace']):
        result = subprocess.run(command, capture_output=True, timeout=15, check=False)
        require(result.returncode == 0)
    expected = ['id', 'name', 'slug', 'github_owner', 'github_repo', 'github_sync_enabled',
                'baseline_branch', 'repo_path', 'run_command', 'paper_id', 'created_at',
                'updated_at', 'workspace_state_json']
    with sqlite3.connect(database) as connection:
        require([row[1] for row in connection.execute('PRAGMA table_info(local_projects)')] == expected)
        for table in ('local_projects', 'local_experiments'):
            require(connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0)
        now = int(time.time() * 1000)
        connection.execute('INSERT INTO local_projects (' + ','.join(expected[:12])
                           + ') VALUES (' + ','.join('?' for _ in range(12)) + ')',
                           (project_id, 'Factory isolated research', 'factory-research', '', '',
                            0, 'main', str(work), None, None, now, now))
    return project_id


def container_main():
    os.umask(0o077)
    bootstrap_project(Path('/session'), os.environ['ORX_FACTORY_PROJECT_ID'])
    bridge = subprocess.Popen(['/usr/local/bin/python3', '-I', '-B', '/trusted/orx_research_socket_bridge.py', '--bridge'])
    try:
        result = subprocess.run(['/trusted/orx', 'up', '--no-browser', '--port', '4791', '--model', 'factory/deepseek-flash'], check=False)
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
