"""Fixed bounded remote probe. Only explicit prepare may create one private root.

No sudo, chmod, system installation, credentials, model access or app startup.
"""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


def run(body):
    def fail(code): return {'nonce': body['nonce'], 'ok': False, 'code': code}
    if sys.platform != 'linux' or os.uname().machine != 'x86_64': return fail('SSH_LINUX_ARCH_REQUIRED')
    if getattr(os, 'getuid')() == 0: return fail('SSH_NON_ROOT_REQUIRED')
    if sys.version_info < (3, 12): return fail('SSH_PYTHON_VERSION_REQUIRED')
    if shutil.which('docker') is None: return fail('SSH_DOCKER_MISSING')
    try:
        result = subprocess.run(['docker', 'version', '--format', '{{.Server.Version}}'],
            capture_output=True, timeout=10, check=False)
    except Exception: return fail('SSH_DOCKER_UNAVAILABLE')
    if result.returncode:
        return fail('SSH_DOCKER_PERMISSION' if b'permission denied' in result.stderr.lower() else 'SSH_DOCKER_UNAVAILABLE')
    root = Path(body['root'])
    if not root.is_absolute() or '..' in root.parts or root.resolve() != root: return fail('SSH_DIRECTORY_UNSAFE')
    if root.exists() or root.is_symlink():
        info = root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != getattr(os, 'getuid')()
                or stat.S_IMODE(info.st_mode) != 0o700 or root.is_symlink()): return fail('SSH_DIRECTORY_UNSAFE')
    else:
        try: info = root.parent.lstat()
        except OSError: return fail('SSH_DIRECTORY_PARENT_REQUIRED')
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != getattr(os, 'getuid')()
                or info.st_mode & 0o022 or not info.st_mode & 0o200 or root.parent.is_symlink()):
            return fail('SSH_DIRECTORY_PARENT_REQUIRED')
        if body['action'] == 'prepare':
            try: root.mkdir(mode=0o700)
            except FileExistsError: return run(body)
            return run(body)
    return {'nonce': body['nonce'], 'ok': True, 'code': 'SSH_PREREQUISITES_READY',
        'directoryExists': root.exists()}


if __name__ == '__main__':
    body = None
    try:
        body = json.loads(sys.stdin.buffer.readline(4097))
        assert set(body) == {'action', 'root', 'nonce'} and body['action'] in {'inspect', 'prepare'}
        result = run(body)
    except Exception:
        result = {'nonce': body.get('nonce') if isinstance(body, dict) else None,
            'ok': False, 'code': 'SSH_CHECK_UNCONFIRMED'}
    print(json.dumps(result), flush=True)
