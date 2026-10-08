"""Private bounded candidate invocation journal and original-custody cleanup.

This external operator helper never constructs a provider or dispatches work.
Reopening permits evidence updates and stop-only recovery, never new stages.
The journal is operator-owned evidence, not a replacement for native receipts.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

try:
    import fcntl
except ImportError:  # Importable for skipped test discovery; execution remains Linux-only.
    fcntl = None
import time
import uuid

ERROR = 'RESEARCH_CANDIDATE_CUSTODY_UNCONFIRMED'
IDENTITY = frozenset({'configSha256', 'candidateSha256', 'baselineManifestSha256'})
PROGRESS_IDS = ('requestId', 'taskId', 'planId', 'nativeRunId', 'leaseId', 'providerJobId', 'artifactId')
STAGES = ('preparation', 'training', 'evaluation')
PHASES = frozenset({'STARTED', 'PLAN_APPROVED', 'TASK_ACCEPTED', 'NATIVE_PAUSED',
    'PROCESS_SUBMITTED', 'PRELAUNCH_REJECTED', 'PROCESS_RECLAIMED', 'EVIDENCE_IMPORTED',
    'COMPLETED', 'STOPPED', 'ACCEPTED', 'IMPORTED'})
MAXIMUM = 32768


def _require(ok):
    if not ok:
        raise ValueError(ERROR)


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _boot():
    value = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    _require(re.fullmatch(r'[a-f0-9-]{36}', value) is not None)
    return value


def _directory(path):
    _require(path.is_absolute() and '..' not in path.parts)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        info = os.fstat(fd)
        _require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _file(info):
    _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)


def _object(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


class CandidateJournal:
    """Exclusive, fsynced evidence in an existing private directory.

    `total_seconds` is required only for creation (0 < value <= 86400). A
    retained same-boot monotonic deadline cannot be renewed by reopen. Calling
    begin_stage consumes its attempt durably before any external effect; a
    crash between consumption and dispatch is intentionally not retried.
    """
    def __init__(self, path, *, identity, total_seconds=None):
        self.path = Path(path)
        _require(self.path.is_absolute() and '..' not in self.path.parts and self.path.name not in {'', '.', '..'})
        _require(type(identity) is dict and set(identity) == IDENTITY
                 and all(type(v) is str and re.fullmatch('[a-f0-9]{64}', v) for v in identity.values()))
        if total_seconds is not None:
            _require(_number(total_seconds) and 0 < total_seconds <= 86400)
        self.identity = deepcopy(identity)
        self.total_seconds = total_seconds
        self._directory_fd = self._lock_fd = None
        self._body = None
        self._current = None
        self.fresh = False

    def __enter__(self):
        _require(sys.platform == 'linux' and fcntl is not None
                 and self._directory_fd is None and self._body is None)
        try:
            self._directory_fd = _directory(self.path.parent)
            self._directory_pin = os.fstat(self._directory_fd)
            self._lock_name = self.path.name + '.lock'
            try:
                self._lock_fd = os.open(self._lock_name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                        0o600, dir_fd=self._directory_fd)
                new_lock = True
            except FileExistsError:
                self._lock_fd = os.open(self._lock_name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                        dir_fd=self._directory_fd)
                new_lock = False
            _file(os.fstat(self._lock_fd))
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_pin = _stamp(os.fstat(self._lock_fd))
            self._guard()
            try:
                self._body = self._read()
            except FileNotFoundError:
                _require(new_lock and self.total_seconds is not None)
                started = time.monotonic()
                self._body = {'schema': 1, 'identity': deepcopy(self.identity), 'bootId': _boot(),
                    'startedMonotonic': started, 'deadlineMonotonic': started + self.total_seconds,
                    'totalSeconds': self.total_seconds,
                    'stages': {stage: {'consumed': False, 'progress': {}, 'result': None}
                               for stage in STAGES}}
                self._write(self._body)
                self.fresh = True
            self._validate(self._body)
            _require(self._body['identity'] == self.identity)
            if self.total_seconds is not None:
                _require(self.total_seconds == self._body['totalSeconds'])
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_):
        self.close()

    def close(self):
        for field in ('_lock_fd', '_directory_fd'):
            fd = getattr(self, field)
            if fd is not None:
                os.close(fd)
                setattr(self, field, None)

    def _guard(self):
        _require(self._directory_fd is not None and self._lock_fd is not None)
        current = os.stat(self.path.parent, follow_symlinks=False)
        _require((current.st_dev, current.st_ino) == (self._directory_pin.st_dev, self._directory_pin.st_ino)
                 and current.st_uid == os.getuid() and stat.S_IMODE(current.st_mode) == 0o700)
        lock = os.stat(self._lock_name, dir_fd=self._directory_fd, follow_symlinks=False)
        _require(_stamp(lock) == self._lock_pin)

    def _read(self):
        fd = os.open(self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._directory_fd)
        try:
            before = os.fstat(fd)
            _file(before)
            _require(0 < before.st_size <= MAXIMUM)
            raw = os.read(fd, MAXIMUM + 1)
            current = os.stat(self.path.name, dir_fd=self._directory_fd, follow_symlinks=False)
            _require(len(raw) == before.st_size and _stamp(before) == _stamp(os.fstat(fd)) == _stamp(current))
            body = json.loads(raw, object_pairs_hook=_object)
            self._validate(body)
            self._current = _stamp(current)
            return body
        finally:
            os.close(fd)

    def _validate(self, body):
        _require(type(body) is dict and set(body) == {'schema', 'identity', 'bootId', 'startedMonotonic',
                 'deadlineMonotonic', 'totalSeconds', 'stages'} and type(body['schema']) is int and body['schema'] == 1)
        _require(type(body['identity']) is dict and set(body['identity']) == IDENTITY
                 and all(type(v) is str and re.fullmatch('[a-f0-9]{64}', v) for v in body['identity'].values()))
        _require(type(body['bootId']) is str and re.fullmatch(r'[a-f0-9-]{36}', body['bootId']) is not None)
        _require(all(_number(body[k]) for k in ('startedMonotonic', 'deadlineMonotonic', 'totalSeconds'))
                 and body['startedMonotonic'] >= 0 and 0 < body['totalSeconds'] <= 86400
                 and body['deadlineMonotonic'] == body['startedMonotonic'] + body['totalSeconds'])
        _require(type(body['stages']) is dict and set(body['stages']) == set(STAGES))
        for row in body['stages'].values():
            _require(type(row) is dict and set(row) == {'consumed', 'progress', 'result'}
                     and type(row['consumed']) is bool and type(row['progress']) is dict)
            self._progress(row['progress'])
            _require(row['consumed'] or (row['progress'] == {} and row['result'] is None))
            if row['result'] is not None:
                self._result(row['result'])

    @staticmethod
    def _progress(value):
        _require(set(value) <= set(PROGRESS_IDS) | {'phase', 'cancelRequested', 'cleanupConfirmed'})
        for key in PROGRESS_IDS:
            if key in value:
                _require(type(value[key]) is str and 0 < len(value[key]) <= 256
                         and all(ord(c) >= 32 and ord(c) != 127 for c in value[key]))
        if 'phase' in value:
            _require(type(value['phase']) is str and value['phase'] in PHASES)
        for key in ('cancelRequested', 'cleanupConfirmed'):
            if key in value:
                _require(type(value[key]) is bool)

    @staticmethod
    def _result(value):
        _require(type(value) is dict and set(value) == {'status', 'cleanupConfirmed'}
                 and value['status'] in {'COMPLETED', 'STOPPED', 'UNKNOWN'}
                 and type(value['cleanupConfirmed']) is bool)
        _require(value['status'] != 'COMPLETED' or value['cleanupConfirmed'])

    def _write(self, body):
        self._guard()
        self._validate(body)
        try:
            current = os.stat(self.path.name, dir_fd=self._directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            _require(self._current is None)
        else:
            _require(self._current is not None and _stamp(current) == self._current)
        raw = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        _require(len(raw) <= MAXIMUM)
        name = '.' + self.path.name + '.' + uuid.uuid4().hex + '.tmp'
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                     dir_fd=self._directory_fd)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path.name, src_dir_fd=self._directory_fd, dst_dir_fd=self._directory_fd)
            os.fsync(self._directory_fd)
            self._current = _stamp(os.stat(self.path.name, dir_fd=self._directory_fd, follow_symlinks=False))
            self._body = deepcopy(body)
        finally:
            try:
                os.unlink(name, dir_fd=self._directory_fd)
            except FileNotFoundError:
                pass

    def snapshot(self):
        self._guard()
        _require(self._body is not None)
        _require(_stamp(os.stat(self.path.name, dir_fd=self._directory_fd, follow_symlinks=False)) == self._current)
        return deepcopy(self._body)

    def remaining(self):
        body = self.snapshot()
        now = time.monotonic()
        _require(body['bootId'] == _boot() and body['startedMonotonic'] <= now < body['deadlineMonotonic'])
        return body['deadlineMonotonic'] - now

    def begin_stage(self, stage):
        _require(stage in STAGES and self.fresh)
        self.remaining()
        body = self.snapshot()
        _require(not body['stages'][stage]['consumed'])
        if stage == 'evaluation':
            _require(body['stages']['training']['result'] == {'status': 'COMPLETED', 'cleanupConfirmed': True})
        body['stages'][stage]['consumed'] = True
        self._write(body)

    def record_progress(self, stage, value):
        """Keep only finite controller fields; never retain output/error/config text.

        Known IDs cannot disappear or change. Null/absent IDs in early controller
        callbacks do not erase prior evidence. Flags are monotonic positive facts.
        """
        _require(stage in STAGES and type(value) is dict)
        selected = {k: value[k] for k in (*PROGRESS_IDS, 'phase', 'cancelRequested', 'cleanupConfirmed')
                    if k in value and value[k] is not None}
        self._progress(selected)
        body = self.snapshot()
        row = body['stages'][stage]
        _require(row['consumed'])
        progress = row['progress']
        for key in PROGRESS_IDS:
            _require(key not in progress or key not in selected or progress[key] == selected[key])
        for key in ('cancelRequested', 'cleanupConfirmed'):
            if progress.get(key) is True:
                selected[key] = True
        if progress.get('phase') in {'COMPLETED', 'STOPPED'} and 'phase' in selected:
            _require(selected['phase'] == progress['phase'])
        row['progress'] = {**progress, **selected}
        self._write(body)

    def finish_stage(self, stage, result):
        _require(stage in STAGES)
        self._result(result)
        body = self.snapshot()
        row = body['stages'][stage]
        _require(row['consumed'])
        previous = row['result']
        if previous is not None:
            _require(previous['status'] == result['status']
                     and (not previous['cleanupConfirmed'] or result['cleanupConfirmed']))
        if result['status'] == 'COMPLETED':
            ids = ('taskId', 'planId', 'nativeRunId', 'leaseId', 'providerJobId')
            if stage == 'preparation':
                _require(row['progress'].get('phase') == 'IMPORTED'
                         and all(key in row['progress'] for key in (*ids, 'artifactId')))
            else:
                _require(row['progress'].get('phase') == 'COMPLETED'
                         and row['progress'].get('cleanupConfirmed') is True
                         and all(key in row['progress'] for key in (*ids, 'requestId')))
        row['result'] = deepcopy(result)
        self._write(body)


async def recover_original(state, runtime, owner, task_id, budget_seconds):
    """Use existing original-custody cleanup, never submit, replay or reset ACK.

    SQL retains its configured timeout; this is the existing bounded async
    observation budget, not a hard timeout on synchronous database operations.
    The caller verifies its retained full identity set before calling. Expired
    experiment deadlines do not prohibit this separate stop-only cleanup grace.
    """
    _require(type(owner) is str and owner and type(task_id) is str and task_id
             and _number(budget_seconds) and 0 < budget_seconds <= 5)
    from agent_factory.research_bootstrap_controller import cleanup_original
    loop = asyncio.get_running_loop()

    def call_async(function):
        return asyncio.run_coroutine_threadsafe(function(), loop).result()

    cleanup = asyncio.create_task(asyncio.to_thread(cleanup_original, state, owner, task_id,
        runtime=runtime, call_async=call_async, timeout_seconds=budget_seconds))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(cleanup)
            break
        except asyncio.CancelledError:
            # Every caller cancellation is deferred, including repeated cancel().
            # The original helper retains its one deadline; no grace is renewed.
            cancelled = True
            if cleanup.done():
                # A genuinely cancelled cleanup cannot supply positive evidence.
                # Retrieving it also avoids spinning on an already-done future.
                result = cleanup.result()
                break
    if cancelled:
        raise asyncio.CancelledError
    return result
