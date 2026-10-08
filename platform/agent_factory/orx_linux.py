"""Task-owned Linux PID namespace/cgroup boundary for the reviewed ORX recipe.

An already configured local Docker daemon is required; this installs nothing,
opens no network, and changes no host security configuration. Container identity
and limits are immutable. A missing/replaced container never means stopped.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from .openresearch import OpenResearchError

RUNTIME_IMAGE = 'python:3.12.14-trixie@sha256:4d1caded1f729ae443eb803f26ffde7b61e696aeaef62f099abb6dd6b14257c7'
BINARY_SHA256 = 'a847d07e8c4c3f2efc47c3549fd27f52c9999b46a21451d4c07ec12de292b8cd'
PYTHON_BINARY = '/usr/local/bin/python3.12'
PYTHON_SHA256 = '479e8cf2dd15299ec38ebb17ac195b44b94beb82530dd7873fb663013a5ba4ee'
PROCESS_LIMIT = 64  # cgroup pids counts native threads as well as processes.


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class TaskLinuxContainer:
    def __init__(self, task_id: str, owner: str, scope: Path, binary: Path,
                 limits: dict[str, Any], *, cleanup_only: bool = False, profile: str = 'experiment-v1'):
        if not sys.platform.startswith('linux'):
            raise OpenResearchError('CONTAINMENT_UNAVAILABLE', 'Linux task containers require Linux')
        self.scope, self.limits = scope.resolve(), dict(limits)
        if profile not in {'experiment-v1', 'public-retrieval-v1'}:
            raise OpenResearchError('CONTAINMENT_UNAVAILABLE', 'Unapproved container profile')
        # Only the explicit public retrieval profile uses the daemon's existing
        # bridge. No ports, host networking, network creation or host changes.
        self.network = 'bridge' if profile == 'public-retrieval-v1' else 'none'
        docker = shutil.which('docker')
        if not docker or ',' in str(self.scope) or ',' in str(binary):
            raise OpenResearchError('CONTAINMENT_UNAVAILABLE', 'A local Docker daemon and exact task paths are required')
        self.docker = docker
        guardian = Path(__file__).with_name('orx_linux_guardian.py' if profile == 'experiment-v1' else 'orx_retrieval_guardian.py').resolve()
        self.guardian_command = [PYTHON_BINARY, '-I', '/opt/factory-guardian.py', str(limits['cpuSeconds'])]
        if profile != 'experiment-v1':
            self.guardian_command.append(str(limits['timeoutSeconds']))
        self.mounts = [(str(self.scope), str(self.scope), False),
                       (str(binary), '/opt/factory-orx', True),
                       (str(guardian), '/opt/factory-guardian.py', True)]
        spec = {'schema': 1, 'owner': owner, 'task': task_id, 'scope': str(self.scope),
                'image': RUNTIME_IMAGE, 'binarySha256': BINARY_SHA256, 'limits': limits,
                'guardianSha256': hashlib.sha256(guardian.read_bytes()).hexdigest(), 'mounts': self.mounts}
        if profile != 'experiment-v1':
            spec.update(profile=profile, network=self.network)
        self.spec_sha = _digest(spec)
        self.name = 'af-orx-' + hashlib.sha256((owner + ':' + task_id).encode()).hexdigest()[:32]
        if profile != 'experiment-v1':
            self.name = 'af-orx-read-' + hashlib.sha256((owner + ':' + task_id + ':' + str(self.scope)).encode()).hexdigest()[:32]
        marker = self.scope / 'factory-linux-container.json'
        saved = None
        if marker.exists():
            if marker.is_symlink() or marker.stat().st_size > 4096:
                raise OpenResearchError('CONTAINMENT_CHANGED', 'Invalid original container receipt')
            saved = json.loads(marker.read_text())
            if saved.get('specSha256') != self.spec_sha:
                raise OpenResearchError('CONTAINMENT_CHANGED', 'Original container specification changed')
        elif cleanup_only:
            raise OpenResearchError('CLEANUP_UNCONFIRMED', 'No original container identity is available')
        found = self._command(['inspect', self.name], allow_failure=True)
        if found.returncode:
            if saved is not None:
                raise OpenResearchError('CLEANUP_UNCONFIRMED', 'Original container is missing; stop cannot be inferred')
            self._command(['image', 'inspect', RUNTIME_IMAGE])  # Setup must preload the exact image.
            args = ['create', '--name', self.name, '--label', 'agent-factory.orx-spec=' + self.spec_sha,
                    '--network', self.network, '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--user', f'{getattr(os, "getuid")()}:{getattr(os, "getgid")()}', '--pids-limit', str(limits['maxProcesses']),
                    '--memory', str(limits['memoryBytes']), '--memory-swap', str(limits['memoryBytes']),
                    '--cpus', str(limits['cpuPercent'] / 100)]
            for source, target, readonly in self.mounts:
                args.extend(['--mount', f'type=bind,source={source},target={target}' + (',readonly' if readonly else '')])
            args += [RUNTIME_IMAGE, *self.guardian_command]
            self._command(args, allow_failure=True)  # A same-task competing creator is validated below.
        value = self._inspect()
        self.cid = value['Id']
        if saved is not None and saved.get('containerId') != self.cid:
            raise OpenResearchError('CONTAINMENT_CHANGED', 'Original container was replaced')
        if saved is None:
            try:
                with marker.open('x') as stream:
                    json.dump({'containerId': self.cid, 'specSha256': self.spec_sha}, stream)
                    stream.flush(); os.fsync(stream.fileno())
            except FileExistsError:
                if json.loads(marker.read_text()) != {'containerId': self.cid, 'specSha256': self.spec_sha}:
                    raise OpenResearchError('CONTAINMENT_CHANGED', 'Concurrent container identity differs')
        self._validate(value)

    def _command(self, args, *, allow_failure=False):
        # Do not inherit Docker contexts, provider/proxy credentials or personal config.
        env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(self.scope / 'home')}
        try:
            result = subprocess.run([self.docker, '--host', 'unix:///var/run/docker.sock', *args],
                env=env, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise OpenResearchError('CONTAINMENT_UNAVAILABLE', 'Exact task-container operation could not be confirmed') from error
        if result.returncode and not allow_failure:
            raise OpenResearchError('CONTAINMENT_UNAVAILABLE', 'Task-owned container operation failed')
        return result

    def _inspect(self):
        result = self._command(['inspect', self.name])
        values = json.loads(result.stdout)
        if len(values) != 1:
            raise OpenResearchError('CONTAINMENT_CHANGED', 'Exact container identity is unavailable')
        return values[0]

    def _validate(self, value):
        config, host = value['Config'], value['HostConfig']
        mounts = sorted((item['Source'], item['Destination'], not item['RW']) for item in value['Mounts'])
        if (getattr(self, 'cid', value['Id']) != value['Id']
                or config.get('Labels', {}).get('agent-factory.orx-spec') != self.spec_sha
                or config['Image'] != RUNTIME_IMAGE or host['NetworkMode'] != self.network or host['Privileged']
                or host.get('PortBindings') or host.get('Binds') or host.get('Devices')
                or not host['ReadonlyRootfs'] or host.get('CapAdd') or host.get('CapDrop') != ['ALL']
                or 'no-new-privileges' not in host.get('SecurityOpt', [])
                or config['User'] != f'{getattr(os, "getuid")()}:{getattr(os, "getgid")()}'
                or host['Memory'] != self.limits['memoryBytes'] or host['MemorySwap'] != self.limits['memoryBytes']
                or host['PidsLimit'] != self.limits['maxProcesses']
                or host['NanoCpus'] != self.limits['cpuPercent'] * 10_000_000
                or mounts != sorted(self.mounts)
                or config['Cmd'] != self.guardian_command):
            raise OpenResearchError('CONTAINMENT_CHANGED', 'Task container identity, mounts or resource boundary changed')

    def exec_argv(self, argv, env):
        value = self._inspect(); self._validate(value)
        if not value['State']['Running']:
            self._command(['start', self.cid])
        args = [self.docker, '--host', 'unix:///var/run/docker.sock', 'exec', '--workdir', str(self.scope)]
        for key, value in {**env, 'PATH': '/usr/local/bin:/usr/bin:/bin', 'TOKIO_WORKER_THREADS': '1'}.items():
            args.extend(['--env', key + '=' + value])
        return [*args, self.cid, '/opt/factory-orx', *argv]

    def process_ids(self):
        value = self._inspect(); self._validate(value)
        if not value['State']['Running']:
            if value['State']['Pid'] != 0:
                raise OpenResearchError('CLEANUP_UNCONFIRMED', 'Container kernel PID remains assigned')
            return []
        result = self._command(['top', self.cid, '-eo', 'pid'])
        pids = [int(line.strip()) for line in result.stdout.splitlines()[1:] if line.strip()]
        return [pid for pid in pids if pid != value['State']['Pid']]

    def evidence(self):
        pids = self.process_ids()
        return {'kind': 'linux_task_container', 'containerId': self.cid, 'specSha256': self.spec_sha,
                'activeProcesses': len(pids), 'allStopped': not pids, 'limits': self.limits,
                'enforced': ['aggregate_memory', 'aggregate_cpu_time_guardian', 'cpu_rate', 'kernel_tasks',
                             *(['wall_time_guardian'] if self.network == 'bridge' else [])],
                'pidLimitIncludesThreads': True, 'network': self.network, 'securitySandbox': False}

    def terminate(self):
        value = self._inspect(); self._validate(value)
        if value['State']['Running']:
            self._command(['kill', self.cid])
        if self.process_ids():
            raise OpenResearchError('CLEANUP_UNCONFIRMED', 'Container still has task processes')

    def close(self):
        # Retain immutable stopped-container identity for later positive proof.
        # Never destroy a detached run merely because a Factory handle closes.
        if not self.process_ids():
            self.terminate()
