"""Factory resource-provider transport; the remote host owns only process custody."""
import asyncio
import base64
from dataclasses import asdict
import hashlib
from inspect import isawaitable, iscoroutine
import json
import os
from pathlib import Path
import selectors
import shlex
from tempfile import TemporaryDirectory
import time
import threading

from .ssh_identity import pinned_ssh
from .process_runtime import process_reservation
from .ssh_process_contract import (PROTOCOL, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, OUTPUT_BYTES,
                                   binding, encoded, request, require, specification)
from .store import digest

EFFECT = 'ssh-process-run-v1'


class SSHProcessTransport:
    def __init__(self, server, lease_for, *, interpreter):
        server.validate()
        require(type(interpreter) is str and interpreter.startswith('/')
                and all(c.isprintable() for c in interpreter))
        self.server, self.lease_for, self.interpreter = server, lease_for, interpreter

    def __call__(self, value, *, before_effect=None):
        value = request(value)
        raw = encoded(value, MAX_REQUEST_BYTES)
        lease = self.lease_for(value['action'])
        lease.validate()
        command = shlex.quote(self.interpreter) + ' -I -B -m agent_factory.ssh_process_helper'
        with TemporaryDirectory(prefix='af-ssh-process-') as folder:
            if before_effect is not None:
                before_effect()
            process = pinned_ssh(self.server, lease, Path(folder), command)
            try:
                assert process.stdin is not None and process.stdout is not None
                os.set_blocking(process.stdin.fileno(), False)
                os.set_blocking(process.stdout.fileno(), False)
                pending, output, eof = memoryview(raw), bytearray(), False
                deadline = time.monotonic() + 30
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdin, selectors.EVENT_WRITE)
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while not eof:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError('SSH_PROCESS_UNCONFIRMED')
                        for key, _ in selector.select(remaining):
                            if key.fileobj is process.stdin:
                                if before_effect is not None:
                                    before_effect()
                                sent = os.write(process.stdin.fileno(), pending[:4096])
                                pending = pending[sent:]
                                if not pending:
                                    if before_effect is not None:
                                        before_effect()
                                    selector.unregister(process.stdin)
                                    process.stdin.close()
                            else:
                                chunk = os.read(process.stdout.fileno(), 65536)
                                if not chunk:
                                    eof = True
                                    break
                                output.extend(chunk)
                                require(len(output) <= MAX_RESPONSE_BYTES)
                require(process.wait(timeout=max(.01, deadline - time.monotonic())) == 0)
                lease.validate()
                return json.loads(output)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if process.stdin is not None:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()


class SSHProcessProvider:
    effect_key = EFFECT
    preflight_seconds = 30

    def __init__(self, server, *, target_ref, spec, limits, exchange, read_lease):
        server.validate()
        self.server, self.target_ref = server, target_ref
        self.spec, self.limits = specification(asdict(spec), asdict(limits))
        self.exchange, self.read_lease = exchange, read_lease

    @property
    def capacity_namespace(self):
        return digest({'protocol': PROTOCOL, 'sshRoot': self.server.scope_pin()})

    @property
    def configuration_fingerprint(self):
        return digest({'protocol': PROTOCOL, 'server': self.server.pin(),
                       'spec': asdict(self.spec), 'limits': asdict(self.limits)})

    def _binding(self, lease):
        require(lease['connectionRef'] == self.target_ref
                and lease['providerNamespace'] == self.capacity_namespace
                and lease.get('executionEffect') == EFFECT and lease.get('gpuBinding') is None)
        guard = lease.get('executionGuard')
        require(type(guard) is dict and set(guard) == {'operationId'})
        reservation = process_reservation(self)
        require(type(lease.get('limits')) is dict and all(
            type(lease['limits'].get(key)) is int and lease['limits'][key] >= needed
            for key, needed in reservation.items()))
        return binding({'leaseId': lease['id'], 'operationId': guard['operationId'],
            'ownerId': lease['ownerId'], 'taskId': lease['localTaskId'], 'runId': lease['nativeRunId'],
            'planId': lease['planId'], 'planHash': lease['planHash'], 'requestId': lease['requestId'],
            'targetFingerprint': lease['targetFingerprint']})

    def _request(self, lease, action):
        return request({'protocol': PROTOCOL, 'action': action, 'binding': self._binding(lease),
                        'root': self.server.allowed_root, 'spec': asdict(self.spec), 'limits': asdict(self.limits)})

    def _observe(self, lease, action, before_effect=None):
        sent = self._request(lease, action)
        result = self.exchange(sent, before_effect=before_effect)
        encoded(result, MAX_RESPONSE_BYTES)
        require(type(result) is dict and result.get('protocol') == PROTOCOL
                and result.get('binding') == sent['binding'] and 'error' not in result)
        observed = result['observation']
        require(type(observed) is dict and observed.get('ownerId') == lease['ownerId']
                and observed.get('taskId') == lease['localTaskId'] and observed.get('requestId') == lease['requestId']
                and observed.get('specSha256') == hashlib.sha256(encoded(
                    {'spec': sent['spec'], 'limits': sent['limits']}, MAX_REQUEST_BYTES)).hexdigest())
        require(type(observed.get('identitySha256')) is str and len(observed['identitySha256']) == 64)
        job = observed['id']
        original_binding = {'taskId': lease['localTaskId'], 'nativeRunId': lease['nativeRunId'],
            'planId': lease['planId'], 'bindingFingerprint': digest({'binding': sent['binding'],
                'processIdentity': observed['identitySha256'], 'rootPin': observed['rootPin']})}
        require(lease.get('providerJobId') in (None, job)
                and lease.get('processBinding') in (None, original_binding))
        stop = observed.get('stopReceipt') or {}
        stopped = (observed.get('stoppedProof') is True and observed.get('state')
                   in {'COMPLETED', 'FAILED', 'CANCELLED', 'LIMIT_STOPPED'}
                   and stop.get('kind') in {'original-group-stopped', 'never-dispatched'})
        status = observed['state'] if stopped else 'RUNNING' if observed['state'] == 'RUNNING' else 'UNKNOWN'
        state = {'CANCELLED': 'CANCEL_CONFIRMED', 'LIMIT_STOPPED': 'FAILED'}.get(status, status)
        released = stopped and action == 'reclaim'
        receipt = {'leaseId': lease['id'], 'ownerId': lease['ownerId'], 'fingerprint': lease['fingerprint'],
            'providerJobId': job, 'processBinding': original_binding,
            'state': 'RECLAIMED' if released else state, 'released': released,
            'allStopped': stopped, 'executionStatus': status,
            'exitCode': observed.get('exitCode') if stopped else None,
            'enforcement': observed['enforcement'], 'stopEvidence': None}
        if stopped:
            receipt['stopEvidence'] = {'allStopped': True, 'kind': 'never-dispatched'
                if stop['kind'] == 'never-dispatched' else 'original-root-reaped-and-no-live-process-group-members'}
        return receipt, result

    async def allocate(self, lease_id, owner, fingerprint, limits):
        raise ValueError('SSH_PROCESS_LEASE_CONTEXT_REQUIRED')

    async def allocate_bound(self, lease, *, before_effect):
        self._binding(lease)
        cancelled = threading.Event()
        def fresh():
            if cancelled.is_set():
                raise ValueError('SSH_PROCESS_SUBMIT_CANCELLED')
            outcome = before_effect()
            if isawaitable(outcome):
                if iscoroutine(outcome):
                    outcome.close()
                raise ValueError('SSH_PROCESS_SYNC_AUTHORITY_REQUIRED')
            if cancelled.is_set():
                raise ValueError('SSH_PROCESS_SUBMIT_CANCELLED')
        try:
            return (await asyncio.to_thread(self._observe, lease, 'submit', fresh))[0]
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def _original(self, lease_id, owner, action):
        lease = self.read_lease(owner, lease_id)
        require(lease['id'] == lease_id and lease['ownerId'] == owner)
        return (await asyncio.to_thread(self._observe, lease, action))[0]

    async def inspect(self, lease_id, owner):
        return await self._original(lease_id, owner, 'inspect')

    async def cancel(self, lease_id, owner):
        return await self._original(lease_id, owner, 'cancel')

    async def reclaim(self, lease_id, owner):
        return await self._original(lease_id, owner, 'reclaim')

    def read_completed_output(self, lease_id, owner):
        lease = self.read_lease(owner, lease_id)
        require(lease['id'] == lease_id and lease['ownerId'] == owner)
        receipt, result = self._observe(lease, 'output')
        require(receipt['allStopped'])
        output = result['output']
        raw = base64.b64decode(output['base64'], validate=True)
        require(len(raw) <= OUTPUT_BYTES and output['bytes'] == len(raw)
                and output['sha256'] == hashlib.sha256(raw).hexdigest())
        return raw
