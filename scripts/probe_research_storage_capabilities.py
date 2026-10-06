#!/usr/bin/env python3
"""Bounded private-scratch FICLONE diagnostic; never clones or edits a package cache.

Linux FICLONE requires source/destination on the same filesystem:
https://man7.org/linux/man-pages/man2/ioctl_ficlonerange.2.html
A positive result covers only two private 16 KiB files, not a complete inventory.
No namespace is created. A positive sysctl observation is not userns permission.
Only the clone worker has a deadline (5 s plus 1 s stop confirmation); filesystem
opens/cleanup can still block on an unhealthy mount. Use an operator outer timeout
for such mounts. STOP_UNCONFIRMED retains files; it never proves process cleanup.
A supported scratch probe is only a prerequisite: source and destination must be
on the same supported filesystem, with private independent inodes and complete
inventory byte verification after cloning. No full-copy fallback is performed.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
from pathlib import Path
import select
import signal
import stat
import sys
import time
import uuid

SIZE = 16384
FICLONE = 0x40049409  # Linux UAPI _IOW(0x94, 9, int), supported architectures below.
TIMEOUT = 5.0
FILESYSTEMS = {'ext4', 'xfs', 'btrfs', 'overlay', 'tmpfs', '9p', 'virtiofs', 'ntfs3', 'fuseblk'}


def _read(path: str, maximum: int = 1048576) -> str:
    with open(path, 'rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('BOUNDED_INPUT')
    return raw.decode('ascii', errors='strict')


def mount_facts(text: str, path: str) -> dict:
    best: tuple[int, str, bool] | None = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 10 or '-' not in parts:
            continue
        split = parts.index('-')
        if split + 3 >= len(parts):
            continue
        mount = parts[4]
        for encoded, decoded in [('\\040', ' '), ('\\011', '\t'), ('\\012', '\n'), ('\\134', '\\')]:
            mount = mount.replace(encoded, decoded)
        if path == mount or path.startswith(mount.rstrip('/') + '/'):
            row = (len(mount), parts[split + 1], 'ro' in parts[5].split(',') or 'ro' in parts[split + 3].split(','))
            if best is None or row[0] > best[0]:
                best = row
    return {'filesystem': best[1] if best and best[1] in FILESYSTEMS else 'UNKNOWN',
            'mountReadOnly': best[2] if best else None}


def _root(path: str) -> int:
    if not path.startswith('/') or any(p in ('.', '..') for p in path.split('/')):
        raise ValueError('PRIVATE_ROOT_REQUIRED')
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY') | getattr(os, 'O_NOFOLLOW')
    fd = os.open('/', flags)
    try:
        for part in path.split('/'):
            if part:
                new = os.open(part, flags, dir_fd=fd)
                os.close(fd)
                fd = new
        value = os.fstat(fd)
        if value.st_uid != getattr(os, 'getuid')() or stat.S_IMODE(value.st_mode) != 0o700:
            raise ValueError('PRIVATE_ROOT_REQUIRED')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _clone(source: int, destination: int) -> str:
    import fcntl
    try:
        getattr(fcntl, 'ioctl')(destination, FICLONE, source)
        return 'CLONED'
    except OSError as error:
        return 'UNSUPPORTED' if error.errno in {errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTTY, errno.EINVAL} else 'DENIED_OR_FAILED'


def _bounded_clone(source: int, destination: int) -> str:
    read_fd, write_fd = os.pipe()
    try:
        pid = getattr(os, 'fork')()
    except BaseException:
        os.close(read_fd)
        os.close(write_fd)
        raise
    if pid == 0:
        os.close(read_fd)
        try:
            os.write(write_fd, _clone(source, destination).encode('ascii'))
        except BaseException:
            pass
        finally:
            os._exit(0)
    os.close(write_fd)
    reaped = False
    try:
        ready, _, _ = select.select([read_fd], [], [], TIMEOUT)
        if not ready:
            return 'TIMEOUT'
        value = os.read(read_fd, 64).decode('ascii')
        _, status = os.waitpid(pid, 0)
        reaped = True
        return value if status == 0 and value in {'CLONED', 'UNSUPPORTED', 'DENIED_OR_FAILED'} else 'FAILED'
    finally:
        os.close(read_fd)
        if not reaped:
            os.kill(pid, getattr(signal, 'SIGKILL'))
            # A stuck kernel syscall cannot be promised stopped on a deadline.
            end = time.monotonic() + 1.0
            while time.monotonic() < end:
                if os.waitpid(pid, getattr(os, 'WNOHANG'))[0] == pid:
                    reaped = True
                    break
                time.sleep(0.01)
            if not reaped:
                raise RuntimeError('STOP_UNCONFIRMED')


def _file(directory: int, name: str) -> int:
    return os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW'), 0o600, dir_fd=directory)


def private_probe(root: int) -> dict:
    name = 'factory-cow-probe-' + uuid.uuid4().hex
    os.mkdir(name, mode=0o700, dir_fd=root)
    directory = os.open(name, os.O_RDONLY | getattr(os, 'O_DIRECTORY') | getattr(os, 'O_NOFOLLOW'), dir_fd=root)
    pin = os.fstat(directory)
    opened: dict[str, int] = {}
    stopped = True
    result = {'status': 'FAILED', 'copyOnWriteVerified': False, 'cleanupComplete': False}
    try:
        opened['source'] = _file(directory, 'source')
        opened['destination'] = _file(directory, 'destination')
        payload = b'A' * SIZE
        if os.write(opened['source'], payload) != SIZE:
            raise ValueError('SHORT_WRITE')
        try:
            result['status'] = _bounded_clone(opened['source'], opened['destination'])
        except RuntimeError:
            stopped = False
            result['status'] = 'STOP_UNCONFIRMED'
        if result['status'] == 'CLONED':
            source, destination = opened['source'], opened['destination']
            cloned = getattr(os, 'pread')(destination, SIZE + 1, 0) == payload
            getattr(os, 'pwrite')(destination, b'B', 0)
            independent = getattr(os, 'pread')(source, SIZE + 1, 0) == payload
            result['copyOnWriteVerified'] = cloned and independent and getattr(os, 'pread')(destination, 1, 0) == b'B'
            if not result['copyOnWriteVerified']:
                result['status'] = 'ISOLATION_FAILED'
    finally:
        try:
            current = os.stat(name, dir_fd=root, follow_symlinks=False)
            same = (current.st_dev, current.st_ino) == (pin.st_dev, pin.st_ino)
            expected = set(opened)
            safe = stopped and same and set(os.listdir(directory)) == expected
            for filename, fd in opened.items():
                actual = os.stat(filename, dir_fd=directory, follow_symlinks=False)
                original = os.fstat(fd)
                safe = safe and actual.st_nlink == 1 and (actual.st_dev, actual.st_ino) == (original.st_dev, original.st_ino)
            if safe:
                for filename in opened:
                    os.unlink(filename, dir_fd=directory)
                os.rmdir(name, dir_fd=root)
                result['cleanupComplete'] = True
        finally:
            for fd in opened.values():
                os.close(fd)
            os.close(directory)
    return result


def probe(path: str) -> dict:
    start = time.monotonic()
    report = {'schema': 1, 'scope': 'private-scratch-filesystem-only',
              'packageFilesystemVerified': False, 'completeInventoryCloneVerified': False,
              'userNamespaceUsableVerified': False, 'minimumScratchAvailable': False,
              'status': 'UNSUPPORTED_PLATFORM', 'copyOnWriteVerified': False, 'cleanupComplete': True}
    if sys.platform != 'linux' or os.uname().machine not in {'x86_64', 'aarch64'}:
        return report
    fd = _root(path)
    try:
        space = os.fstatvfs(fd)
        report['minimumScratchAvailable'] = space.f_bavail * space.f_frsize >= 1048576
        report.update(mount_facts(_read('/proc/self/mountinfo'), path))
        release = os.uname().release.split('.')
        report['kernelMajorMinor'] = [min(int(x), 999) for x in release[:2]] if len(release) >= 2 and all(x.isdecimal() for x in release[:2]) else None
        try:
            value = _read('/proc/sys/user/max_user_namespaces', 32).strip()
            report['userNamespaceLimitPositive'] = int(value) > 0 if value.isdecimal() else None
        except (OSError, ValueError):
            report['userNamespaceLimitPositive'] = None
        report['userNamespaceInterfacePresent'] = Path('/proc/self/ns/user').exists()
        report.update(private_probe(fd) if report['minimumScratchAvailable'] else {'status': 'INSUFFICIENT_SCRATCH'})
    finally:
        os.close(fd)
    report['elapsedMilliseconds'] = min(2147483647, int((time.monotonic() - start) * 1000))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch-root', required=True, help='Existing private owner0700 directory; never a shared cache')
    args = parser.parse_args()
    try:
        result = probe(args.scratch_root)
    except (OSError, ValueError):
        result = {'schema': 1, 'status': 'PROBE_REJECTED', 'copyOnWriteVerified': False}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result.get('copyOnWriteVerified') and result.get('cleanupComplete') else 2


if __name__ == '__main__':
    raise SystemExit(main())
