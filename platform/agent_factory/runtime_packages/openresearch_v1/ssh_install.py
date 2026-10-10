"""Fixed stdin installer; never executes owner input or discovers credentials."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

FILES = {'__init__.py', 'entry.py', 'bridge.py', 'supervisor.py', 'ssh_agent.py', 'orx', 'opencode', 'image.tar',
    'ORX-LICENSE.txt', 'OPENCODE-LICENSE.txt', 'FACTORY-LICENSE.txt', 'THIRD_PARTY_NOTICES.md'}


def require(value):
    if not value: raise ValueError('SSH_INSTALL_UNCONFIRMED')


def directory(root, path):
    root, path = Path(root), Path(path)
    require(root.is_absolute() and root.resolve() == root and path.is_absolute()
        and '..' not in path.parts and path.is_relative_to(root))
    current = root
    for component in (None, *path.relative_to(root).parts):
        if component is not None:
            current = current / component
            if not current.exists(): current.mkdir(mode=0o700)
        info = current.lstat()
        require(stat.S_ISDIR(info.st_mode) and not current.is_symlink()
            and info.st_uid == getattr(os, 'getuid')() and not info.st_mode & 0o077)
    return current


def install():
    os.umask(0o077)
    manifest = json.loads(sys.stdin.buffer.readline(65537))
    require(sys.platform == 'linux' and os.uname().machine == 'x86_64'
        and sys.version_info >= (3, 12) and getattr(os, 'getuid')() > 0)
    require(set(manifest['files']) == FILES)
    root = directory(manifest['allowedRoot'], manifest['directory'])
    package = directory(str(root), str(root / 'factory_package'))
    for name, pin in manifest['files'].items():
        require(type(pin['size']) is int and 0 <= pin['size'] <= 1024**3)
        path = package / name
        mode = 0o700 if name in {'orx', 'opencode', 'bridge.py'} else 0o600
        # Pending bytes are independent from installed files. A lost install
        # acknowledgement can verify/reuse the exact complete package later.
        temporary = package / (name + '.pending')
        if temporary.exists():
            info = temporary.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == getattr(os, 'getuid')() and info.st_nlink == 1)
            temporary.unlink()
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW'), 0o600)
        digest = hashlib.sha256(); remaining = pin['size']
        with os.fdopen(descriptor, 'wb') as output:
            while remaining:
                chunk = sys.stdin.buffer.read(min(remaining, 1024**2))
                require(chunk); remaining -= len(chunk); digest.update(chunk); output.write(chunk)
            output.flush(); os.fsync(output.fileno())
        require(digest.hexdigest() == pin['sha256'])
        if path.exists() or path.is_symlink():
            info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == getattr(os, 'getuid')()
                and not info.st_mode & 0o022)
            with path.open('rb') as existing: require(hashlib.file_digest(existing, 'sha256').hexdigest() == pin['sha256'])
            path.chmod(mode)
            temporary.unlink()
        else:
            temporary.chmod(mode); temporary.replace(path)
    require(not sys.stdin.buffer.read(1))
    # Existing Docker access is a prerequisite, never gained through sudo or
    # daemon/system changes. The exact cached image is checked before launch.
    inventory = subprocess.run(['docker', 'image', 'ls', '--no-trunc', '--quiet'],
        capture_output=True, timeout=15, check=False)
    require(inventory.returncode == 0)
    if manifest['image'] not in inventory.stdout.decode().splitlines():
        loaded = subprocess.run(['docker', 'load', '--input', str(package / 'image.tar')],
            capture_output=True, timeout=120, check=False)
        require(loaded.returncode == 0)
    result = subprocess.run(['docker', 'image', 'inspect', manifest['image'], '--format', '{{.Id}}'],
        capture_output=True, timeout=15, check=False)
    require(result.returncode == 0 and result.stdout.decode().strip() == manifest['image'])
    control = directory(str(root), str(root / 'connections'))
    directory(str(control), str(control / manifest['nonce']))
    print(json.dumps({'installed': True, 'package': str(package), 'control': str(control)}), flush=True)


if __name__ == '__main__': install()
