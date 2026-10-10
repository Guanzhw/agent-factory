"""Stdlib supervisor RPC over an authenticated SSH channel, no model secrets."""
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time

from .entry import build_command, private_directory, require
from .supervisor import OpenResearchSupervisor, PlatformOpenResearchConfig


class ForwardedBroker:
    def __init__(self, capability, path, ttl):
        require(re.fullmatch('[A-Za-z0-9_-]{24,128}', capability))
        self.capability, self.path = capability, Path(path)
        self.deadline = time.monotonic() + ttl
        self.handle = self
    def check(self): require(self.authorized(self.capability))
    def authorized(self, capability): return capability == self.capability and time.monotonic() < self.deadline
    def start(self):
        private_directory(self.path.parent)
        info = self.path.lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600)
    def close(self): self.deadline = 0


class SSHSupervisor(OpenResearchSupervisor):
    def __init__(self, config, root, version, broker):
        self.version, self.forwarded = version, broker
        super().__init__(config, root)
    def _new_broker(self, path, handle, *, ttl): return self.forwarded
    def _command(self, config, name, capability):
        command = build_command(config, name, capability)
        position = command.index('--network')
        command[position:position] = ['--mount', f'type=bind,src={self.forwarded.path},dst=/trusted/model-broker.sock,readonly',
            '--env', 'ORX_FACTORY_BROKER_SOCKET=/trusted/model-broker.sock']
        return command
    def _inspect(self, receipt, root):
        value = super()._inspect(receipt, root)
        mount = [item for item in value['Mounts'] if item['Destination'] == '/trusted/model-broker.sock']
        saved = Path(receipt['brokerSocket'])
        require(saved.parent.parent == self.forwarded.path.parent.parent
            and re.fullmatch('[a-f0-9]{24}', saved.parent.name) and saved.name == 'broker.sock')
        require(len(mount) == 1 and mount[0]['Source'] == str(saved) and mount[0]['RW'] is False)
        return value
    def _save(self, root, value):
        value.setdefault('brokerSocket', str(self.forwarded.path))
        super()._save(root, value)


def run():
    os.umask(0o077)
    value = json.loads(sys.stdin.buffer.readline(65537))
    config = PlatformOpenResearchConfig(**value['config'])
    broker = ForwardedBroker(value['capability'], value['brokerSocket'], config.max_active_seconds)
    supervisor = SSHSupervisor(config, value['root'], value['version'], broker)
    def disconnected(signum, frame): raise SystemExit(1)
    signal.signal(signal.SIGHUP, disconnected)
    signal.signal(signal.SIGTERM, disconnected)
    try:
        while line := sys.stdin.buffer.readline(1048577):
            require(len(line) <= 1048576)
            command = json.loads(line); body = command['body']
            try:
                action = command['action']
                if action == 'prepare': result = supervisor.prepare(body, broker)
                elif action == 'check': result = supervisor.check(body)
                elif action == 'stop': result = supervisor.stop(body)
                elif action == 'request':
                    result = supervisor.request(body, command['method'], command['path'], command.get('payload'))
                else: raise ValueError('SSH_ACTION_DENIED')
                response = {'id': command['id'], 'ok': True, 'result': result}
            except Exception:
                response = {'id': command['id'], 'ok': False, 'error': 'SSH_RUNTIME_UNCONFIRMED'}
            encoded = json.dumps(response)
            require(len(encoded.encode()) <= 1048576)
            print(encoded, flush=True)
    finally: supervisor.close()
