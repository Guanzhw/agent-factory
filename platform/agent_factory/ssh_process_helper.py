"""One SSH request over original local process custody; no queue or allocator."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from .process_enforcement import BoundedProcessAdapter, ProcessEnforcementError
from .ssh_process_contract import (PROTOCOL, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES,
                                   OUTPUT_BYTES, encoded, request, require, specification)


@contextmanager
def directory(path):
    """Traverse absolute paths without following directory symlinks."""
    if sys.platform != 'linux':
        raise ProcessEnforcementError('SSH_PROCESS_PLATFORM_UNSUPPORTED')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in Path(path).parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def read_file(fd, name, maximum):
    if sys.platform != 'linux':
        raise ProcessEnforcementError('SSH_PROCESS_PLATFORM_UNSUPPORTED')
    item = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(item)
        require(stat.S_ISREG(before.st_mode) and before.st_size <= maximum)
        chunks, total = [], 0
        while chunk := os.read(item, min(65536, maximum + 1 - total)):
            chunks.append(chunk)
            total += len(chunk)
            require(total <= maximum)
        after = os.fstat(item)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
        return b''.join(chunks)
    finally:
        os.close(item)


def original(observation, binding, value):
    require(observation['ownerId'] == binding['ownerId']
            and observation['taskId'] == binding['taskId']
            and observation['requestId'] == binding['requestId']
            and observation['specSha256'] == hashlib.sha256(encoded(
                {'spec': value['spec'], 'limits': value['limits']}, MAX_REQUEST_BYTES)).hexdigest())


def handle(value):
    if sys.platform != 'linux':
        raise ProcessEnforcementError('SSH_PROCESS_PLATFORM_UNSUPPORTED')
    value = request(value)
    if value['action'] == 'capabilities':
        with directory(Path(value['root'])) as root_fd:
            info = os.fstat(root_fd)
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0)
        try:
            import resource
            rlimits = all(hasattr(resource, name) for name in ('setrlimit', 'RLIMIT_CPU', 'RLIMIT_AS', 'RLIMIT_FSIZE'))
        except ImportError:
            rlimits = False
        fork, proc = hasattr(os, 'fork'), Path('/proc/self/stat').is_file()
        return {'protocol': PROTOCOL, 'platform': sys.platform, 'rootReady': True,
                'fork': fork, 'proc': proc, 'rlimits': rlimits,
                'processCustody': sys.platform == 'linux' and fork and proc and rlimits,
                'isolation': {'aggregateQuota': False, 'hostileCodeSandbox': False, 'networkIsolation': False},
                'scheduler': False, 'gpuAllocation': False, 'automaticInstallation': False}
    import fcntl
    binding, root, action = value['binding'], Path(value['root']), value['action']
    descriptor = {key: value[key] for key in ('protocol', 'binding', 'root', 'spec', 'limits')}
    descriptor_raw = encoded(descriptor, MAX_REQUEST_BYTES)
    with directory(root) as root_fd:
        info = os.fstat(root_fd)
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0)
        # Lock the existing root inode; read/cancel do not create lock files.
        fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        created = False
        try:
            if action == 'submit':
                try:
                    os.mkdir(binding['leaseId'], 0o700, dir_fd=root_fd)
                    created = True
                    os.fsync(root_fd)
                except FileExistsError:
                    pass
            with directory(root / binding['leaseId']) as run_fd:
                run_info = os.fstat(run_fd)
                require(run_info.st_uid == os.getuid() and stat.S_IMODE(run_info.st_mode) & 0o077 == 0)
                if created:
                    fd = os.open('binding.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=run_fd)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(descriptor_raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.fsync(run_fd)
                require(read_file(run_fd, 'binding.json', MAX_REQUEST_BYTES) == descriptor_raw)
                path = root / binding['leaseId'] / 'custody.sqlite'
                if created:
                    spec, limits = specification(value['spec'], value['limits'])
                    adapter = BoundedProcessAdapter.create(path, owner_id=binding['ownerId'],
                        task_id=binding['taskId'], request_id=binding['requestId'], spec=spec, limits=limits)
                    # The authenticated caller committed admission before this single submit.
                    # Only the create instance has launch authority; reopened journals never do.
                    observation = adapter.launch(owner_id=binding['ownerId'], before_effect=lambda: None)
                else:
                    adapter = BoundedProcessAdapter(path)
                    observation = adapter.inspect(owner_id=binding['ownerId'])
                    original(observation, binding, value)
                    if action == 'cancel':
                        observation = adapter.cancel(owner_id=binding['ownerId'])
                original(observation, binding, value)
                result = {'protocol': PROTOCOL, 'binding': binding, 'observation': observation}
                if action == 'output':
                    require(observation['stoppedProof'] is True
                            and observation['state'] in {'COMPLETED', 'FAILED', 'CANCELLED', 'LIMIT_STOPPED'})
                    raw = read_file(run_fd, 'custody.output', OUTPUT_BYTES)
                    result['output'] = {'base64': base64.b64encode(raw).decode(), 'bytes': len(raw),
                                        'sha256': hashlib.sha256(raw).hexdigest()}
                encoded(result, MAX_RESPONSE_BYTES)
                return result
        finally:
            fcntl.flock(root_fd, fcntl.LOCK_UN)


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        require(len(raw) <= MAX_REQUEST_BYTES)
        result = handle(json.loads(raw))
    except (ValueError, TypeError, KeyError, OSError, ProcessEnforcementError):
        result = {'protocol': PROTOCOL, 'error': 'SSH_PROCESS_UNCONFIRMED'}
    sys.stdout.buffer.write(encoded(result, MAX_RESPONSE_BYTES) + b'\n')


if __name__ == '__main__':
    main()
