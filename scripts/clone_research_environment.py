#!/usr/bin/env python3
"""Private FICLONE-only regular-file tree clone; not environment admission.

Only a single symlink-free tree (for example site-packages) is supported. Source
hardlinks are read, never adopted. Failure retains an unsealed private directory.
No source files, shared caches, permissions, or credentials are modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
from typing import Any, cast
from uuid import uuid4

FICLONE = 0x40049409
MAX_FILES = 32768
MAX_ENTRIES = 65536
MAX_BYTES = 8 * 1024**3
MAX_FILE_BYTES = 1024**3
MAX_DEPTH = 20
MAX_RECEIPT_BYTES = 16 * 1024**2
TIMEOUT_SECONDS = 120
KILL_SECONDS = 5
RECEIPT = 'clone-receipt.json'
PENDING = '.clone-receipt.pending'
ERRORS = frozenset({'PLATFORM_UNSUPPORTED', 'INPUT_INVALID', 'SOURCE_UNSAFE',
    'SOURCE_CHANGED', 'LIMIT_EXCEEDED', 'REFLINK_UNAVAILABLE', 'DESTINATION_INVALID',
    'TIMEOUT', 'CLONE_FAILED'})


class CloneError(ValueError):
    pass


def require(value, code='INPUT_INVALID'):
    if not value:
        raise CloneError(code)


def result(code=None, *, files=0, size=0, fingerprint=None):
    return {'schema': 1, 'status': 'SEALED' if code is None else 'FAILED',
        'errorCode': code, 'fileCount': files, 'sizeBytes': size,
        'sourceTreeSha256': fingerprint, 'receiptBasename': RECEIPT if code is None else None,
        'reflinkOnly': True, 'interpreterVerified': False, 'environmentAdmitted': False}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def flags():
    require(sys.platform == 'linux' and callable(getattr(os, 'getuid', None)), 'PLATFORM_UNSUPPORTED')
    values = [getattr(os, name, None) for name in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK')]
    require(all(type(value) is int and value != 0 for value in values), 'PLATFORM_UNSUPPORTED')
    return cast(tuple[int, int, int], tuple(values))


def absolute(path):
    value = os.fspath(path)
    require(type(value) is str and 1 < len(value) <= 4096 and '\x00' not in value
            and str(Path(value)) == value and Path(value).is_absolute()
            and '..' not in Path(value).parts)
    return Path(value)


def open_directory(path):
    nofollow, directory, _ = flags()
    fd = os.open('/', os.O_RDONLY | directory | nofollow)
    try:
        for name in path.parts[1:]:
            new = os.open(name, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd)
            fd = new
        return fd
    except BaseException:
        os.close(fd)
        raise


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
        info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def identity(info):
    return info.st_dev, info.st_ino


def check_time(deadline):
    require(time.monotonic() < deadline, 'TIMEOUT')


def file_hash(fd, info, deadline):
    require(stat.S_ISREG(info.st_mode) and 0 <= info.st_size <= MAX_FILE_BYTES, 'SOURCE_UNSAFE')
    os.lseek(fd, 0, os.SEEK_SET)
    remaining = info.st_size
    digest = hashlib.sha256()
    while remaining:
        check_time(deadline)
        piece = os.read(fd, min(1024**2, remaining))
        require(bool(piece), 'SOURCE_CHANGED')
        digest.update(piece)
        remaining -= len(piece)
    require(os.read(fd, 1) == b'' and stamp(os.fstat(fd)) == stamp(info), 'SOURCE_CHANGED')
    return digest.hexdigest()


def names(fd):
    # No follow of entries; every later open uses this same directory descriptor.
    with os.scandir(fd) as items:
        found = []
        for entry in items:
            require(len(found) < MAX_ENTRIES, 'LIMIT_EXCEEDED')
            require(entry.name not in {'.', '..'} and len(entry.name) <= 255, 'SOURCE_UNSAFE')
            found.append(entry.name)
    return sorted(found)


def scan(root_fd, deadline, *, private=False, hash_files=True, ignored=frozenset()):
    nofollow, directory, nonblock = flags()
    records = []
    total = 0
    count = 0

    def walk(fd, prefix, depth):
        nonlocal total, count
        check_time(deadline)
        require(depth <= MAX_DEPTH, 'LIMIT_EXCEEDED')
        before = os.fstat(fd)
        require(stat.S_ISDIR(before.st_mode), 'SOURCE_UNSAFE')
        if private:
            require(stat.S_IMODE(before.st_mode) == 0o700 and before.st_uid == getattr(os, 'getuid')(), 'DESTINATION_INVALID')
        listed = names(fd)
        for name in listed:
            if prefix + name in ignored:
                continue
            check_time(deadline)
            relative = prefix + name
            require(len(relative) <= 2048 and len(records) < MAX_ENTRIES, 'LIMIT_EXCEEDED')
            observed = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(observed.st_mode):
                child = os.open(name, os.O_RDONLY | nofollow | directory, dir_fd=fd)
                try:
                    require(stamp(os.fstat(child)) == stamp(observed), 'SOURCE_CHANGED')
                    records.append({'path': relative, 'kind': 'directory', 'stamp': stamp(observed)})
                    walk(child, relative + '/', depth + 1)
                    require(stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) == stamp(observed), 'SOURCE_CHANGED')
                finally:
                    os.close(child)
            else:
                require(stat.S_ISREG(observed.st_mode), 'SOURCE_UNSAFE')
                count += 1
                total += observed.st_size
                require(count <= MAX_FILES and total <= MAX_BYTES and observed.st_size <= MAX_FILE_BYTES, 'LIMIT_EXCEEDED')
                child = os.open(name, os.O_RDONLY | nofollow | nonblock, dir_fd=fd)
                try:
                    require(stamp(os.fstat(child)) == stamp(observed), 'SOURCE_CHANGED')
                    if private:
                        require(observed.st_nlink == 1 and stat.S_IMODE(observed.st_mode) in {0o600, 0o700}
                                and observed.st_uid == getattr(os, 'getuid')(), 'DESTINATION_INVALID')
                    digest = file_hash(child, observed, deadline) if hash_files else None
                    require(stamp(os.stat(name, dir_fd=fd, follow_symlinks=False)) == stamp(observed), 'SOURCE_CHANGED')
                    records.append({'path': relative, 'kind': 'file', 'stamp': stamp(observed),
                        'sizeBytes': observed.st_size, 'sha256': digest})
                finally:
                    os.close(child)
        require(names(fd) == listed and stamp(os.fstat(fd)) == stamp(before), 'SOURCE_CHANGED')
    walk(root_fd, '', 0)
    return records, count, total


def parent_fd(root_fd, relative):
    nofollow, directory, _ = flags()
    parts = relative.split('/')
    fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | directory | nofollow, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def reflink(destination_fd, source_fd):
    import fcntl
    try:
        getattr(fcntl, 'ioctl')(destination_fd, FICLONE, source_fd)
    except OSError:
        raise CloneError('REFLINK_UNAVAILABLE') from None


def clone(source, destination_parent):
    """Synchronous primitive. CLI adds a hard supervisor deadline; no retries."""
    source, destination_parent = absolute(source), absolute(destination_parent)
    require(source != destination_parent and source not in destination_parent.parents)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    source_fd, parent, destination = None, None, None
    try:
        source_fd = open_directory(source)
        source_root = os.fstat(source_fd)
        parent = open_directory(destination_parent)
        parent_info = os.fstat(parent)
        require(stat.S_IMODE(parent_info.st_mode) == 0o700 and parent_info.st_uid == getattr(os, 'getuid')(), 'DESTINATION_INVALID')
        records, count, size = scan(source_fd, deadline)
        require(not any(item['path'] in {RECEIPT, PENDING} for item in records), 'SOURCE_UNSAFE')
        name = 'clone-' + str(uuid4())
        os.mkdir(name, 0o700, dir_fd=parent)
        nofollow, directory, nonblock = flags()
        destination = os.open(name, os.O_RDONLY | directory | nofollow, dir_fd=parent)
        destination_info = os.fstat(destination)
        require(stat.S_IMODE(destination_info.st_mode) == 0o700, 'DESTINATION_INVALID')
        for record in records:
            check_time(deadline)
            out_parent, basename = parent_fd(destination, record['path'])
            try:
                if record['kind'] == 'directory':
                    os.mkdir(basename, 0o700, dir_fd=out_parent)
                    created = os.open(basename, os.O_RDONLY | directory | nofollow, dir_fd=out_parent)
                    try:
                        os.fsync(created)
                    finally:
                        os.close(created)
                    os.fsync(out_parent)
                    continue
                src_parent, src_name = parent_fd(source_fd, record['path'])
                try:
                    source_file = os.open(src_name, os.O_RDONLY | nofollow | nonblock, dir_fd=src_parent)
                    try:
                        before = os.fstat(source_file)
                        require(stamp(before) == record['stamp'], 'SOURCE_CHANGED')
                        output = os.open(basename, os.O_RDWR | os.O_CREAT | os.O_EXCL | nofollow, 0o600, dir_fd=out_parent)
                        try:
                            reflink(output, source_file)
                            after = os.fstat(output)
                            require(after.st_nlink == 1 and identity(after) != identity(before), 'DESTINATION_INVALID')
                            require(after.st_size == record['sizeBytes'] and file_hash(output, after, deadline) == record['sha256'], 'SOURCE_CHANGED')
                            require(stamp(os.fstat(source_file)) == record['stamp']
                                    and file_hash(source_file, before, deadline) == record['sha256'], 'SOURCE_CHANGED')
                            getattr(os, 'fchmod')(output, 0o700 if before.st_mode & 0o111 else 0o600)
                            os.fsync(output)
                        finally:
                            os.close(output)
                    finally:
                        os.close(source_file)
                finally:
                    os.close(src_parent)
                os.fsync(out_parent)
            finally:
                os.close(out_parent)
        copied, copied_count, copied_size = scan(destination, deadline, private=True)
        def strip(rows):
            return [{key: value for key, value in row.items() if key != 'stamp'} for row in rows]
        require(strip(copied) == strip(records) and (copied_count, copied_size) == (count, size), 'DESTINATION_INVALID')
        require(scan(source_fd, deadline) == (records, count, size)
                and stamp(os.fstat(source_fd)) == stamp(source_root), 'SOURCE_CHANGED')
        for path, expected in ((source, source_root), (destination_parent, parent_info)):
            reopened = open_directory(path)
            try:
                require(identity(os.fstat(reopened)) == identity(expected), 'SOURCE_CHANGED')
            finally:
                os.close(reopened)
        require(identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == identity(destination_info), 'DESTINATION_INVALID')
        check_time(deadline)
        fingerprint = hashlib.sha256(canonical(records)).hexdigest()
        receipt = canonical({'schema': 1, 'kind': 'private-reflink-clone-v1', 'sourceRoot': str(source),
            'destinationRoot': str(destination_parent / name), 'sourceRootIdentity': identity(source_root),
            'destinationRootIdentity': identity(destination_info), 'sourceTreeSha256': fingerprint,
            'files': strip(records), 'fileCount': count, 'sizeBytes': size,
            'symlinks': 'rejected', 'environmentAdmitted': False})
        require(len(receipt) <= MAX_RECEIPT_BYTES and size + len(receipt) <= MAX_BYTES, 'LIMIT_EXCEEDED')
        seal = os.open(PENDING, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600, dir_fd=destination)
        try:
            offset = 0
            while offset < len(receipt):
                check_time(deadline)
                written = os.write(seal, receipt[offset:offset + 1024**2])
                require(written > 0, 'CLONE_FAILED')
                offset += written
            os.fsync(seal)
            sealed_info = os.fstat(seal)
        finally:
            os.close(seal)
        # Hash passes take time. Close the observation window with metadata and
        # namespace passes on BOTH trees after receipt I/O, before publication.
        # This remains an observed snapshot, not a hostile-writer filesystem lock.
        def metadata(rows):
            return [{key: value for key, value in row.items() if key != 'sha256'} for row in rows]
        final_source, final_count, final_size = scan(source_fd, deadline, hash_files=False)
        final_destination, final_dest_count, final_dest_size = scan(destination, deadline,
            private=True, hash_files=False, ignored=frozenset({PENDING}))
        require(metadata(final_source) == metadata(records) and (final_count, final_size) == (count, size)
                and stamp(os.fstat(source_fd)) == stamp(source_root), 'SOURCE_CHANGED')
        require(metadata(final_destination) == metadata(copied)
                and (final_dest_count, final_dest_size) == (count, size), 'DESTINATION_INVALID')
        pending = os.stat(PENDING, dir_fd=destination, follow_symlinks=False)
        require(stamp(pending) == stamp(sealed_info) and stat.S_ISREG(pending.st_mode) and pending.st_nlink == 1
                and pending.st_size == len(receipt) and stat.S_IMODE(pending.st_mode) == 0o600
                and pending.st_uid == getattr(os, 'getuid')(), 'DESTINATION_INVALID')
        for path, expected in ((source, source_root), (destination_parent, parent_info)):
            reopened = open_directory(path)
            try:
                require(identity(os.fstat(reopened)) == identity(expected), 'SOURCE_CHANGED')
            finally:
                os.close(reopened)
        require(identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) == identity(destination_info), 'DESTINATION_INVALID')
        os.rename(PENDING, RECEIPT, src_dir_fd=destination, dst_dir_fd=destination)
        os.fsync(destination)
        os.fsync(parent)
        return result(files=count, size=size, fingerprint=fingerprint)
    finally:
        for fd in (destination, parent, source_fd):
            if fd is not None:
                os.close(fd)


def worker(source, parent):
    try:
        return clone(source, parent)
    except CloneError as error:
        code = error.args[0] if error.args and error.args[0] in ERRORS else 'CLONE_FAILED'
        return result(code)
    except Exception:
        return result('CLONE_FAILED')


def validate_result(value):
    require(type(value) is dict and set(value) == set(result()), 'CLONE_FAILED')
    value = cast(dict[str, Any], value)
    require(type(value['schema']) is int and value['schema'] == 1
            and type(value['fileCount']) is int and type(value['sizeBytes']) is int, 'CLONE_FAILED')
    if value['status'] == 'FAILED':
        require(type(value['errorCode']) is str and value['errorCode'] in ERRORS
                and value == result(value['errorCode']), 'CLONE_FAILED')
    else:
        require(value['status'] == 'SEALED' and type(value['fileCount']) is int
                and 0 <= value['fileCount'] <= MAX_FILES and type(value['sizeBytes']) is int
                and 0 <= value['sizeBytes'] <= MAX_BYTES, 'CLONE_FAILED')
        fingerprint = value['sourceTreeSha256']
        require(type(fingerprint) is str and len(fingerprint) == 64
                and all(c in '0123456789abcdef' for c in fingerprint), 'CLONE_FAILED')
        require(value == result(files=value['fileCount'], size=value['sizeBytes'], fingerprint=fingerprint), 'CLONE_FAILED')
    require(value['reflinkOnly'] is True and value['interpreterVerified'] is False
            and value['environmentAdmitted'] is False, 'CLONE_FAILED')
    return value


def supervise(source, parent):
    process = None
    try:
        process = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).absolute()),
            '--worker', '--source-root', source, '--destination-parent', parent],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'PATH': os.defpath, 'LANG': 'C.UTF-8'}, start_new_session=True)
        output, _ = process.communicate(timeout=TIMEOUT_SECONDS)
        require(process.returncode == 0 and len(output) <= 4096, 'CLONE_FAILED')
        decoded = json.loads(output)
        return validate_result(decoded)
    except subprocess.TimeoutExpired:
        return result('TIMEOUT')
    except Exception:
        return result('CLONE_FAILED')
    finally:
        if process is not None and process.poll() is None:
            try:
                getattr(os, 'killpg')(process.pid, getattr(signal, 'SIGKILL'))
                process.wait(timeout=KILL_SECONDS)
            except (OSError, subprocess.TimeoutExpired):
                pass


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise CloneError('INPUT_INVALID')


def main(argv=None):
    try:
        parser = Arguments(description=__doc__)
        parser.add_argument('--source-root', required=True)
        parser.add_argument('--destination-parent', required=True)
        parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
        args = parser.parse_args(argv)
        require(sys.platform == 'linux', 'PLATFORM_UNSUPPORTED')
        value = worker(args.source_root, args.destination_parent) if args.worker else supervise(args.source_root, args.destination_parent)
    except CloneError as error:
        code = error.args[0] if error.args and error.args[0] in ERRORS else 'INPUT_INVALID'
        value = result(code)
    except Exception:
        value = result('INPUT_INVALID')
    print(json.dumps(value, separators=(',', ':'), allow_nan=False))
    return 0 if value['status'] == 'SEALED' or ('args' in locals() and args.worker) else 1


if __name__ == '__main__':
    raise SystemExit(main())
