"""Offline consistency audit, NOT issuer authentication or runtime reconciliation.

Inputs are operator-created nonsecret JSON exports. `evidence` keys: schema,
lease (af_leases.body), provider (af_process_allocations.body), mapping
(af_process_runs row), task (af_tasks row), plan (af_plans row), ticket (exact
native queue job), nativeSession (explicit null if absent, otherwise normalized
user_id, agent_id, runs containing run_id/agent_id, session_data). JSON DB bodies must already be decoded. Export these together
using the existing read-only DB procedure; do not initialize an application.

`pins` keys: schema, taskId, ownerId, planId, planHash, requestId, nativeRunId,
leaseId, providerRoot, rootIdentity [device,inode], spec, limits, gpuBinding,
sourceSha256, manifestSha256, observerSha256, requiredIsolation (list).
These MUST come from independently retained original configuration/admission
receipts, NOT from the evidence being checked. This helper cannot authenticate
that provenance. It reads no credential files or environment variables.

Default strict mode reconstructs historical configuration as a separate forensic
check. Explicit --released-never-dispatched mode accepts selection pins only:
schema, taskId, ownerId, requestId, leaseId (optional nativeRunId). These identify the
original attempt from retained progress/admission records. It cross-checks the
original persisted plan hash, task fingerprint, native envelope, binding, journal
identity and release proofs. It does NOT reconstruct historical driver config or
require artifacts from stages that never ran. Current root physical identity must
reproduce the original binding namespace. Trusted read-only exports and original
journal provenance remain operator responsibilities. Neither mode checks the
complete descendant closure; that is a separate read-only gate.

Only already-released cooperative never-dispatched custody is supported. ACKs
are intentionally neither interpreted as fresh release authority nor replayed.
No attempt is made to authenticate the exported DB issuer, verify global GPU
idleness, or certify readiness of a new attempt. Run with python -I -B.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

MAX_JSON = 16 * 1024 * 1024
MAX_JOURNAL = 32 * 1024 * 1024
BINDINGS = ('id', 'ownerId', 'fingerprint', 'localTaskId', 'planId', 'nativeRunId',
            'requestId', 'connectionRef', 'planHash', 'targetFingerprint', 'poolId',
            'poolFingerprint', 'providerNamespace', 'limits', 'executionEffect',
            'executionGuard', 'gpuBinding')
IDENTITY = ('schema', 'id', 'ownerId', 'taskId', 'requestId', 'spec', 'limits',
            'bootId', 'rootPin', 'specSha256')
PROCESS_PIN = ('id', 'specSha256', 'identitySha256', 'rootPin')


class Rejected(Exception):
    pass


def need(ok):
    if not ok:
        raise Rejected()


def digest(value, *, ascii=False):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=ascii, allow_nan=False).encode()).hexdigest()


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result)
        result[key] = value
    return result


def decode(raw):
    need(len(raw) <= MAX_JSON)
    return json.loads(raw, object_pairs_hook=no_duplicates,
                      parse_constant=lambda _: (_ for _ in ()).throw(Rejected()))


def open_regular(path, maximum):
    """Traverse all ancestors without following symlinks; caller closes fd."""
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts)
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= maximum)
        except BaseException:
            os.close(fd)
            raise
        return fd
    finally:
        os.close(parent)


def load_json(path):
    fd = open_regular(path, MAX_JSON)
    with os.fdopen(fd, 'rb') as stream:
        return decode(stream.read(MAX_JSON + 1))


def journal_read(path):
    """DELETE-mode only: refuse WAL/SHM/recovery journals, no immutable shortcut."""
    fd = open_regular(path, MAX_JOURNAL)
    try:
        before = os.fstat(fd)
        need(stat.S_IMODE(before.st_mode) == 0o600)
        header = os.pread(fd, 100, 0)
        need(header[:16] == b'SQLite format 3\x00' and header[18:20] == b'\x01\x01')
        need(not any(os.path.lexists(str(path) + tail) for tail in ('-wal', '-shm', '-journal')))
        # Original path remains necessary to inspect exact custody rootPin.
        with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=1)) as conn:
            conn.set_progress_handler(lambda: 1, 100_000)
            conn.execute('PRAGMA query_only=ON')
            conn.execute('PRAGMA trusted_schema=OFF')
            need(conn.execute('PRAGMA journal_mode').fetchone()[0] == 'delete')
            conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_JSON)
            need(conn.execute("SELECT type FROM sqlite_schema WHERE name='custody'").fetchall() == [('table',)])
            rows = conn.execute('SELECT singleton,body FROM custody LIMIT 2').fetchall()
            need(len(rows) == 1 and rows[0][0] == 1)
            body = decode(rows[0][1])
        after = os.stat(path, follow_symlinks=False)
        need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
             (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
        return body, before
    finally:
        os.close(fd)


def audit(evidence, pins, journal, *, mode='strict'):
    """Return finite safe output only. Missing evidence or mismatch is UNKNOWN."""
    result = {'schema': 1, 'code': 'UNKNOWN', 'releasedCustodyConsistent': False,
              'identityConsistent': False, 'replayRequired': False,
              'issuerAuthenticated': False, 'newAttemptReady': False}
    phase = 'INPUT'
    result.update(mode=mode if mode in ('strict', 'released-never-dispatched') else 'INVALID',
                  historicalConfigReconstructed=False, historicalConfigValidated=False,
                  releaseIdentityConsistent=False, descendantsChecked=False,
                  scope='NEVER_DISPATCHED_RELEASE' if mode == 'released-never-dispatched' else 'STRICT_FORENSIC',
                  historicalConfigStatus='NOT_REQUIRED_FOR_NEVER_DISPATCHED_RELEASE'
                  if mode == 'released-never-dispatched' else 'UNKNOWN')
    try:
        need(mode in ('strict', 'released-never-dispatched'))
        minimal = mode == 'released-never-dispatched'
        need(type(evidence['schema']) is int and evidence['schema'] == 1
             and type(pins['schema']) is int and pins['schema'] == 1)
        lease, record, mapping, task, plan_row, ticket = (
            evidence[key] for key in ('lease', 'provider', 'mapping', 'task', 'plan', 'ticket'))
        plan = plan_row['body']
        phase = 'ORIGINAL_PLAN_AND_TASK'
        if minimal:
            # Selection pins identify the original task; persisted plan hash is
            # cross-checked below, never invented from mutable allocation fields.
            selectors = {'schema', 'taskId', 'ownerId', 'requestId', 'leaseId'}
            need(set(pins) in (selectors, selectors | {'nativeRunId'}))
            need('nativeRunId' not in pins or pins['nativeRunId'] == task['run_id'])
            pins = {**pins, 'planId': task['plan_id'], 'planHash': plan_row['hash'],
                    'nativeRunId': task['run_id']}
            need(type(pins['leaseId']) is str and bool(pins['leaseId']))
            need(task['terminal'] is True and ticket['status'] in ('cancelled', 'completed', 'failed'))
        for key, task_key in (('taskId', 'id'), ('ownerId', 'owner_id'), ('planId', 'plan_id'),
                              ('requestId', 'request_id'), ('nativeRunId', 'run_id')):
            need(type(pins[key]) is str and bool(pins[key]) and task[task_key] == pins[key])
        need(plan['id'] == plan_row['id'] == pins['planId']
             and plan['ownerId'] == plan_row['owner_id'] == pins['ownerId']
             and digest(plan) == plan_row['hash'] == pins['planHash'])
        need(task['fingerprint'] == digest({'planId': pins['planId'], 'planHash': pins['planHash']}))
        phase = 'NATIVE_ENVELOPE'
        expected_ticket = {'id': pins['nativeRunId'], 'session_id': pins['taskId'],
                           'user_id': pins['ownerId'], 'component_type': 'agent', 'component_id': 'factory-executor'}
        need(all(ticket[key] == value for key, value in expected_ticket.items())
             and ticket.get('job_type', 'run') == 'run')
        need(ticket['idempotency_key'] == digest({'owner': pins['ownerId'], 'task': pins['taskId'],
                                                 'request': pins['requestId']}, ascii=True))
        session = evidence['nativeSession']
        if session is not None:
            need(session['user_id'] == pins['ownerId'] and session['agent_id'] == 'factory-executor')
            matches = [run for run in session['runs'] if run['run_id'] == pins['nativeRunId']
                       and run['agent_id'] == 'factory-executor']
            need(len(matches) == 1)
        state = ticket['payload']['kwargs'].get('session_state')
        if state is None and session is not None:
            state = session['session_data']['session_state']
        if isinstance(state, str):
            state = decode(state)
        need(state['factory_envelope'] == {'plan_ref': pins['planId'], 'user_id': pins['ownerId'],
                                           'task_id': pins['taskId'], 'request_id': pins['requestId']})
        phase = 'LEASE_MAPPING'
        binding = {key: lease[key] for key in BINDINGS}
        need(record['binding'] == binding and record['bindingHash'] == digest(binding)
             and binding['executionEffect'] == 'research-process-run-v1')
        for key, pin_key in (('id', 'leaseId'), ('ownerId', 'ownerId'), ('localTaskId', 'taskId'),
                             ('planId', 'planId'), ('nativeRunId', 'nativeRunId'), ('planHash', 'planHash')):
            need(binding[key] == pins[pin_key])
        need(mapping['task_id'] == pins['taskId'] and mapping['owner_id'] == pins['ownerId']
             and mapping['native_run_id'] == pins['nativeRunId'] and mapping['lease_id'] == pins['leaseId']
             and mapping['effect_key'] == 'research-process-run-v1')
        need(mapping['body'] == {'taskId': pins['taskId'], 'nativeRunId': pins['nativeRunId'],
             'planId': pins['planId'], 'ownerId': pins['ownerId'], 'leaseId': pins['leaseId'],
             'targetRef': binding['connectionRef'], 'planHash': pins['planHash'],
             'requestId': binding['requestId'], 'leaseFingerprint': binding['fingerprint']})
        need(not any(key.startswith('aggregate') for key in record))
        phase = 'JOURNAL_NAMESPACE'
        root = Path(journal).parent.parent if minimal else Path(pins['providerRoot'])
        path = root / pins['leaseId'] / 'custody.sqlite'
        need(path == Path(journal) and path.is_absolute() and '..' not in path.parts)
        body, info = journal_read(path)
        need(not any(key.startswith('aggregate') for key in body))
        root_info, directory = root.lstat(), path.parent.lstat()
        need(stat.S_ISDIR(root_info.st_mode) and stat.S_ISDIR(directory.st_mode)
             and stat.S_IMODE(directory.st_mode) & 0o077 == 0)
        if minimal:
            # Current physical identity must reproduce the namespace committed in
            # the ORIGINAL binding; it is not labelled independently retained history.
            pins = {**pins, 'rootIdentity': [root_info.st_dev, root_info.st_ino],
                    'spec': body['spec'], 'limits': body['limits'],
                    'gpuBinding': binding['gpuBinding']}
        need(pins['rootIdentity'] == [root_info.st_dev, root_info.st_ino])
        namespace = digest({'namespace': 'process-custody-v1', 'root': digest({
            'namespace': 'local-workspace-v1', 'root': str(root), 'rootIdentity': pins['rootIdentity']})})
        need(binding['providerNamespace'] == namespace)
        phase = 'HISTORICAL_CONFIGURATION'
        if not minimal:
            base = {'namespace': namespace, 'spec': pins['spec'], 'limits': pins['limits'],
                    'revision': 'process-provider-v1'}
            need(type(pins['requiredIsolation']) is list)
            if pins['requiredIsolation']:
                base['requiredIsolation'] = sorted(set(pins['requiredIsolation']))
            config = digest({'base': digest(base), 'revision': 'research-local-provider-v1',
                             'gpuBinding': pins['gpuBinding'], 'sourceSha256': pins['sourceSha256'],
                             'manifestSha256': pins['manifestSha256'], 'observerSha256': pins['observerSha256']})
        gpu_binding = pins['gpuBinding']
        need(set(gpu_binding) == {'schema', 'receiverNamespace', 'deviceId', 'policy',
                                  'quotaEnforced', 'deviceIsolationEnforced'}
             and type(gpu_binding['schema']) is int and gpu_binding['schema'] == 1
             and gpu_binding['policy'] == 'exclusive-factory-lease'
             and gpu_binding['quotaEnforced'] is False and gpu_binding['deviceIsolationEnforced'] is False)
        hashes = [gpu_binding['receiverNamespace'], gpu_binding['deviceId']]
        if not minimal:
            hashes += [pins[key] for key in ('sourceSha256', 'manifestSha256', 'observerSha256')]
        for value in hashes:
            need(type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None)
        if not minimal:
            need(record['configurationFingerprint'] == config and binding['gpuBinding'] == pins['gpuBinding']
                 and binding['executionGuard']['manifestSha256'] == pins['manifestSha256'])
            result.update(historicalConfigReconstructed=True, historicalConfigValidated=True,
                          historicalConfigStatus='VALIDATED')
        phase = 'JOURNAL_IDENTITY'
        root_pin = {'directoryDevice': directory.st_dev, 'directoryInode': directory.st_ino,
                    'fileDevice': info.st_dev, 'fileInode': info.st_ino, 'path': str(path)}
        need(body['rootPin'] == root_pin and body['schema'] == 1
             and body['ownerId'] == pins['ownerId'] and body['taskId'] == pins['taskId']
             and body['requestId'] == binding['requestId']
             and body['spec'] == pins['spec'] and body['limits'] == pins['limits'])
        need(body['specSha256'] == digest({'spec': body['spec'], 'limits': body['limits']}, ascii=True)
             and body['identitySha256'] == digest({key: body[key] for key in IDENTITY}, ascii=True))
        need(record['directoryIdentity'] == [directory.st_dev, directory.st_ino]
             and record['journalIdentity'] == [info.st_dev, info.st_ino]
             and record['processPin'] == {key: body[key] for key in PROCESS_PIN})
        need(body['bootId'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip())
        phase = 'NEVER_DISPATCHED_STOP'
        receipt = {'kind': 'never-dispatched', 'journalId': body['id'],
                   'identitySha256': body['identitySha256'], 'bootId': body['bootId'],
                   'guardian': None, 'child': None, 'exitCode': None, 'groupStopped': True}
        need(body['stopReceipt'] == receipt and body['guardian'] is None and body['child'] is None
             and body['state'] == 'CANCELLED' and body['stoppedProof'] is True and body['capacityHeld'] is False)
        phase = 'RELEASED_CUSTODY'
        need(lease['processBinding'] == {'taskId': pins['taskId'], 'nativeRunId': pins['nativeRunId'],
             'planId': pins['planId'], 'bindingFingerprint': record['bindingHash']}
             and lease['providerJobId'] == body['id']
             and lease['stopEvidence'] == {'allStopped': True, 'kind': 'never-dispatched'}
             and lease['stopEvidence']['allStopped'] is True
             and record['executionStatus'] == lease['executionStatus'] == 'CANCELLED')
        need(record['state'] == lease['state'] == 'RECLAIMED' and record['released'] is True
             and record['allStopped'] is True and record['stopKind'] == 'never-dispatched'
             and lease['capacityHeld'] is False)
        phase = 'GPU_RELEASE_PROOF'
        observation = digest({'neverDispatched': True, 'processPin': record['processPin'],
                              'stopReceipt': receipt, 'binding': record['bindingHash']})
        need(record['gpuReleaseObservationSha256'] == observation)
        gpu_keys = ('id', 'ownerId', 'localTaskId', 'nativeRunId', 'planId', 'fingerprint', 'gpuBinding')
        gpu = {'schema': 1, 'bindingFingerprint': digest({key: binding[key] for key in gpu_keys}),
               'state': 'RELEASED', 'releaseProof': {'kind': 'never-dispatched',
               'processBindingFingerprint': record['bindingHash'], 'deviceObservationSha256': observation}}
        need(lease['gpuEvidence'] == gpu)
        result.update(code='RELEASED_CUSTODY_CONSISTENT', releasedCustodyConsistent=True,
                      identityConsistent=not minimal, releaseIdentityConsistent=True)
        phase = 'COMPLETE'
    except Exception:
        pass
    result['phase'] = phase
    return result


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    # No argparse error echo: paths/identifiers must never reach stdout/stderr.
    result = {'schema': 1, 'code': 'UNKNOWN', 'releasedCustodyConsistent': False,
              'identityConsistent': False, 'replayRequired': False,
              'issuerAuthenticated': False, 'newAttemptReady': False}
    try:
        need(sys.flags.isolated == 1 and sys.dont_write_bytecode)
        mode = 'strict'
        if len(args) == 4 and args[0] == '--released-never-dispatched':
            mode, args = 'released-never-dispatched', args[1:]
        need(len(args) == 3)
        result = audit(load_json(args[0]), load_json(args[1]), args[2], mode=mode)
    except Exception:
        pass
    print(json.dumps(result, sort_keys=True))
    return 0 if result['releasedCustodyConsistent'] else 2


if __name__ == '__main__':
    sys.exit(main())
