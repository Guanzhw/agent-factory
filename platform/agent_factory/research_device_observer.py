"""Operator-pinned NVIDIA CLI observation; no quota or isolation enforcement.

An empty compute-apps query corroborates original process stop, never replaces
it. Driver failure, unsupported output, or ambiguous identity remains UNKNOWN.
"""
import hashlib
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import time
from typing import cast

from .gpu_custody import GpuBinding
from .store import digest


def _require(value):
    if not value:
        raise ValueError("RESEARCH_DEVICE_OBSERVATION_INVALID")


class NvidiaSmiObserver:
    def __init__(self, executable: Path, sha256: str, device_uuid: str, gpu_binding: GpuBinding, revision: str):
        _require(type(executable) is type(Path()) and executable.is_absolute()
                 and type(sha256) is str and re.fullmatch('[a-f0-9]{64}', sha256)
                 and type(device_uuid) is str and re.fullmatch('GPU-[a-fA-F0-9-]{8,80}', device_uuid)
                 and type(gpu_binding) is GpuBinding
                 and type(revision) is str and re.fullmatch('[A-Za-z0-9_.-]{1,64}', revision))
        self._executable, self._sha256, self._uuid = executable, sha256, device_uuid
        self._binding = gpu_binding.to_dict()
        self.configuration_fingerprint = digest({'executable': str(executable), 'sha256': sha256,
            'device': device_uuid, 'gpuBinding': self._binding, 'revision': revision})

    def _query(self, field):
        # Execute the verified open inode, not a path which can be replaced after hashing.
        nofollow = getattr(os, 'O_NOFOLLOW', None)
        _require(type(nofollow) is int and nofollow > 0)
        descriptor = os.open(self._executable, os.O_RDONLY | cast(int, nofollow))
        try:
            info = os.fstat(descriptor)
            _require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 64 * 1024**2)
            checksum = hashlib.sha256()
            while chunk := os.read(descriptor, 65536):
                checksum.update(chunk)
            _require(checksum.hexdigest() == self._sha256)
            args = [f'/proc/self/fd/{descriptor}', f'--id={self._uuid}', field, '--format=csv,noheader,nounits']
            with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'LC_ALL': 'C'},
                                  pass_fds=(descriptor,), close_fds=True) as process:
                try:
                    assert process.stdout is not None
                    output = bytearray()
                    deadline = time.monotonic() + 5
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        while True:
                            left = deadline - time.monotonic()
                            _require(left > 0)
                            _require(selector.select(left))
                            chunk = os.read(process.stdout.fileno(), min(4096, 65537 - len(output)))
                            if not chunk:
                                break
                            output.extend(chunk)
                            _require(len(output) <= 65536)
                    _require(process.wait(timeout=max(.001, deadline-time.monotonic())) == 0)
                    return bytes(output)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=1)
        finally:
            os.close(descriptor)

    def __call__(self, request):
        request_hash = digest(request)
        result = {'schema': 1, 'requestFingerprint': request_hash, 'status': 'UNKNOWN',
                  'observationSha256': digest({'request': request_hash, 'status': 'UNKNOWN'})}
        try:
            _require(type(request) is dict and request.get('gpuBinding') == self._binding
                     and request.get('operation') in ('launch', 'release'))
            if request['operation'] == 'release':
                _require(request.get('originalStopped') is True and type(request.get('stopReceiptSha256')) is str
                         and re.fullmatch('[a-f0-9]{64}', cast(str, request['stopReceiptSha256'])))
            identity = self._query('--query-gpu=uuid')
            _require(identity.decode('ascii').strip() == self._uuid)
            apps = self._query('--query-compute-apps=gpu_uuid,pid')
            lines = apps.decode('ascii').strip().splitlines()
            pids = set()
            for line in lines:
                parts = [part.strip() for part in line.split(',')]
                _require(len(parts) == 2 and parts[0] == self._uuid and re.fullmatch('[1-9][0-9]{0,9}', parts[1]))
                _require(parts[1] not in pids)
                pids.add(parts[1])
            status = 'BUSY' if pids else 'RELEASED' if request['operation'] == 'release' else 'AVAILABLE'
            result.update(status=status, observationSha256=digest({'request': request_hash,
                'identitySha256': hashlib.sha256(identity).hexdigest(), 'appsSha256': hashlib.sha256(apps).hexdigest(),
                'observer': self.configuration_fingerprint, 'status': status}))
        except Exception:
            pass
        return result
