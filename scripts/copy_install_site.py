"""Explicit full-copy materialization into a NEW private installation directory.

No reflink, hardlink, installer, interpreter execution, network, or existing-tree mutation.
The fresh destination is exclusively owned; concurrent same-UID writers are unsupported.
The operator supplies only task-owned paths; this does not authorize execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import PurePosixPath
import shutil
import stat
import sys
from uuid import uuid4
from typing import cast

MAX_FILES = 32768
MAX_BYTES = 8 * 1024**3
MAX_FILE_BYTES = 1024**3
HEADROOM = 2 * 1024**3
CHUNK = 1024**2


class CopyRejected(Exception):
    pass


def require(condition, code='INSTALL_COPY_INVALID'):
    if not condition:
        raise CopyRejected(code)


def flags():
    values = [getattr(os, name, None) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')]
    require(os.name == 'posix' and all(type(v) is int and v > 0 for v in values)
            and callable(getattr(os, 'fchmod', None)), 'INSTALL_COPY_UNSUPPORTED')
    return cast(tuple[int, int, int], tuple(values))


def absolute(path):
    value = os.fspath(path)
    require(type(value) is str and value.startswith('/') and not value.startswith('//')
            and len(value) <= 4096 and '\x00' not in value and '..' not in value.split('/')
            and value == str(PurePosixPath(value)) and value != '/')
    return value


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def pin(info):
    return (info.st_dev, info.st_ino)


def owned(info, directory=False):
    require(info.st_uid == getattr(os, 'getuid', lambda: -1)() and not info.st_mode & 0o7022)
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    if not directory:
        require(info.st_nlink == 1 and 0 <= info.st_size <= MAX_FILE_BYTES)


def open_directory(path):
    nofollow, directory, _ = flags()
    fd = os.open('/', os.O_RDONLY | directory | nofollow)
    try:
        for part in PurePosixPath(absolute(path)).parts[1:]:
            next_fd = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd); fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def below(root_fd, parts):
    nofollow, directory, _ = flags()
    fd = os.dup(root_fd)
    try:
        for part in parts:
            next_fd = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd); fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def scan(root_fd):
    result = {}
    total = count = 0
    def visit(fd, prefix):
        nonlocal total, count
        before = os.fstat(fd); owned(before, True)
        result[prefix] = stamp(before)
        require(len(result) <= MAX_FILES * 2, 'INSTALL_COPY_BOUND')
        names = sorted(os.listdir(fd))
        require(len(names) <= MAX_FILES * 2, 'INSTALL_COPY_BOUND')
        for name in names:
            require(name not in ('.', '..') and '/' not in name and len(os.fsencode(name)) <= 255)
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            relative = (*prefix, name)
            if stat.S_ISDIR(info.st_mode):
                child = below(fd, (name,))
                try:
                    require(pin(os.fstat(child)) == pin(info))
                    visit(child, relative)
                finally: os.close(child)
            else:
                owned(info)
                count += 1; total += info.st_size
                require(count <= MAX_FILES and total <= MAX_BYTES, 'INSTALL_COPY_BOUND')
                result[relative] = stamp(info)
                require(len(result) <= MAX_FILES * 2, 'INSTALL_COPY_BOUND')
        require(stamp(os.fstat(fd)) == stamp(before), 'INSTALL_COPY_SOURCE_CHANGED')
    visit(root_fd, ())
    return result, count, total


def hash_fd(fd, maximum):
    digest = hashlib.sha256(); size = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while block := os.read(fd, min(CHUNK, maximum - size + 1)):
        size += len(block); require(size <= maximum, 'INSTALL_COPY_SOURCE_CHANGED')
        digest.update(block)
    return digest.hexdigest(), size


def cleanup(root_fd, parent_fd, name, identities):
    """Remove only original known entries; replacement/unknown entries stay held."""
    for parts, expected in sorted(identities.items(), key=lambda item: len(item[0]), reverse=True):
        if not parts: continue
        parent = None
        try:
            parent = below(root_fd, parts[:-1])
            info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if pin(info) != expected: continue
            if stat.S_ISDIR(info.st_mode): os.rmdir(parts[-1], dir_fd=parent)
            else: os.unlink(parts[-1], dir_fd=parent)
        except OSError: pass
        finally:
            if parent is not None: os.close(parent)
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if pin(info) == identities[()]: os.rmdir(name, dir_fd=parent_fd)
    except OSError: pass


def copy_site(source_root, destination_root, *, disk_usage=None):
    disk_usage = shutil.disk_usage if disk_usage is None else disk_usage
    source, destination = absolute(source_root), absolute(destination_root)
    require(source != destination and not destination.startswith(source + '/')
            and not source.startswith(destination + '/'))
    source_fd = parent_fd = destination_fd = None
    identities = {}; success = False
    try:
        source_fd = open_directory(source)
        snapshot, count, total = scan(source_fd)
        parent_path, name = str(PurePosixPath(destination).parent), PurePosixPath(destination).name
        parent_fd = open_directory(parent_path)
        parent_info = os.fstat(parent_fd); owned(parent_info, True)
        require(stat.S_IMODE(parent_info.st_mode) == 0o700)
        try: os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError: pass
        else: raise CopyRejected('INSTALL_COPY_DESTINATION_EXISTS')
        # The staged source already exists and is reflected in free space.
        require(disk_usage(parent_path).free >= total + HEADROOM, 'INSTALL_COPY_INSUFFICIENT_SPACE')
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        destination_fd = below(parent_fd, (name,)); identities[()] = pin(os.fstat(destination_fd))
        receipts = []
        nofollow, _, nonblock = flags()
        for parts, expected in sorted(snapshot.items()):
            if not parts: continue
            destination_parent = below(destination_fd, parts[:-1])
            try:
                if stat.S_ISDIR(expected[2]):
                    os.mkdir(parts[-1], mode=0o700, dir_fd=destination_parent)
                    identities[parts] = pin(os.stat(parts[-1], dir_fd=destination_parent, follow_symlinks=False))
                    continue
                source_parent = below(source_fd, parts[:-1])
                input_fd = output_fd = None
                temporary = '.copy-' + uuid4().hex
                try:
                    input_fd = os.open(parts[-1], os.O_RDONLY | nofollow | nonblock, dir_fd=source_parent)
                    require(stamp(os.fstat(input_fd)) == expected, 'INSTALL_COPY_SOURCE_CHANGED')
                    output_fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow,
                                        0o600, dir_fd=destination_parent)
                    identities[(*parts[:-1], temporary)] = pin(os.fstat(output_fd))
                    digest = hashlib.sha256(); size = 0
                    while block := os.read(input_fd, CHUNK):
                        size += len(block); require(size <= expected[6], 'INSTALL_COPY_SOURCE_CHANGED')
                        digest.update(block)
                        pending = memoryview(block)
                        while pending:
                            written = os.write(output_fd, pending); require(written > 0)
                            pending = pending[written:]
                    require(size == expected[6] and stamp(os.fstat(input_fd)) == expected, 'INSTALL_COPY_SOURCE_CHANGED')
                    require(stamp(os.stat(parts[-1], dir_fd=source_parent, follow_symlinks=False)) == expected,
                            'INSTALL_COPY_SOURCE_CHANGED')
                    getattr(os, 'fchmod')(output_fd, 0o700 if expected[2] & stat.S_IXUSR else 0o600)
                    os.fsync(output_fd)
                    require(hash_fd(output_fd, size) == (digest.hexdigest(), size), 'INSTALL_COPY_CONTENT_CHANGED')
                    # The fresh 0700 tree has one writer. Never replace an existing entry.
                    require(pin(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) == identities[()])
                    try: os.stat(parts[-1], dir_fd=destination_parent, follow_symlinks=False)
                    except FileNotFoundError: pass
                    else: raise CopyRejected('INSTALL_COPY_DESTINATION_EXISTS')
                    os.rename(temporary, parts[-1], src_dir_fd=destination_parent, dst_dir_fd=destination_parent)
                    identities[parts] = pin(os.fstat(output_fd))
                    identities.pop((*parts[:-1], temporary))
                    info = os.stat(parts[-1], dir_fd=destination_parent, follow_symlinks=False)
                    owned(info); require(pin(info) == identities[parts] and info.st_size == size)
                    os.fsync(destination_parent)
                    receipts.append({'path': list(parts), 'size': size, 'sha256': digest.hexdigest()})
                finally:
                    if input_fd is not None: os.close(input_fd)
                    if output_fd is not None: os.close(output_fd)
                    os.close(source_parent)
            finally: os.close(destination_parent)
        require(scan(source_fd)[0] == snapshot, 'INSTALL_COPY_SOURCE_CHANGED')
        reopened = open_directory(source)
        try: require(pin(os.fstat(reopened)) == pin(os.fstat(source_fd)), 'INSTALL_COPY_SOURCE_CHANGED')
        finally: os.close(reopened)
        destination_snapshot, destination_count, destination_bytes = scan(destination_fd)
        require(set(destination_snapshot) == set(snapshot) and destination_count == count
                and destination_bytes == total, 'INSTALL_COPY_CONTENT_CHANGED')
        require(all(pin_value == destination_snapshot[parts][:2] for parts, pin_value in identities.items()),
                'INSTALL_COPY_CONTENT_CHANGED')
        for record in receipts:
            parts = tuple(record['path']); parent = below(destination_fd, parts[:-1])
            try:
                fd = os.open(parts[-1], os.O_RDONLY | nofollow | nonblock, dir_fd=parent)
                try:
                    info = os.fstat(fd); owned(info)
                    require(pin(info) == identities[parts] and hash_fd(fd, record['size']) ==
                            (record['sha256'], record['size']), 'INSTALL_COPY_CONTENT_CHANGED')
                finally: os.close(fd)
            finally: os.close(parent)
        # Close the multi-file hashing window: neither earlier outputs nor source
        # entries may change while later destination files are being verified.
        require(scan(source_fd)[0] == snapshot, 'INSTALL_COPY_SOURCE_CHANGED')
        require(scan(destination_fd)[0] == destination_snapshot, 'INSTALL_COPY_CONTENT_CHANGED')
        for path, held_fd in ((source, source_fd), (destination, destination_fd)):
            reopened = open_directory(path)
            try: require(pin(os.fstat(reopened)) == pin(os.fstat(held_fd)), 'INSTALL_COPY_ROOT_CHANGED')
            finally: os.close(reopened)
        require(pin(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)) == identities[()])
        os.fsync(destination_fd); os.fsync(parent_fd)
        success = True
        return {'schema': 1, 'kind': 'INSTALL_FULL_COPY', 'files': count, 'bytes': total,
                'treeSha256': hashlib.sha256(json.dumps(receipts, sort_keys=True, separators=(',', ':'),
                                                       ensure_ascii=True).encode()).hexdigest()}
    finally:
        if destination_fd is not None and not success:
            cleanup(destination_fd, parent_fd, PurePosixPath(destination).name, identities)
        for fd in (destination_fd, parent_fd, source_fd):
            if fd is not None: os.close(fd)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CopyRejected('INSTALL_COPY_ARGUMENTS_INVALID')


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--source-root', required=True)
        parser.add_argument('--destination-root', required=True)
        parser.add_argument('--receipt')
        args = parser.parse_args(argv)
        if args.receipt:
            receipt_path = absolute(args.receipt)
            require(all(receipt_path != root and not receipt_path.startswith(root + '/')
                        for root in (absolute(args.source_root), absolute(args.destination_root))))
        result = copy_site(args.source_root, args.destination_root)
        if args.receipt:
            receipt = absolute(args.receipt)
            parent_fd = open_directory(str(PurePosixPath(receipt).parent))
            fd = None
            try:
                info = os.fstat(parent_fd); owned(info, True)
                require(stat.S_IMODE(info.st_mode) == 0o700)
                fd = os.open(PurePosixPath(receipt).name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | flags()[0],
                             0o600, dir_fd=parent_fd)
                data = memoryview(json.dumps(result, sort_keys=True, separators=(',', ':')).encode())
                while data:
                    written = os.write(fd, data); require(written > 0); data = data[written:]
                os.fsync(fd); os.fsync(parent_fd)
            finally:
                if fd is not None: os.close(fd)
                os.close(parent_fd)
        print('INSTALL_FULL_COPY_COMPLETED')
        return 0
    except BaseException:
        print('INSTALL_FULL_COPY_FAILED', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
