"""Factory resource-provider transport; the remote host owns only process custody."""
import asyncio
import base64
from dataclasses import asdict
import hashlib
from inspect import isawaitable, iscoroutine
import json
from pathlib import Path
import shlex
from tempfile import TemporaryDirectory
import time
import threading

from .ssh_exchange import SSHExchangeCancelled, exchange as pipe_exchange
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

    def __call__(self, value, *, before_effect=None, cancelled=None):
        deadline = time.monotonic() + 30
        value = request(value)
        raw = encoded(value, MAX_REQUEST_BYTES)
        lease = self.lease_for(value['action'])

        def fresh():
            lease.validate()
            if before_effect is not None:
                before_effect()

        command = shlex.quote(self.interpreter) + ' -I -B -m agent_factory.ssh_process_helper'
        with TemporaryDirectory(prefix='af-ssh-process-') as folder:
            fresh()
            if time.monotonic() >= deadline:
                raise TimeoutError('SSH_PROCESS_UNCONFIRMED')
            process = pinned_ssh(self.server, lease, Path(folder), command)
            output = pipe_exchange(process, raw, deadline=deadline, max_output=MAX_RESPONSE_BYTES,
                                   before_write=fresh, cancelled=cancelled)
            lease.validate()
            return json.loads(output)


class SSHProcessProvider:
    effect_key = EFFECT
    preflight_seconds = 30

    def __init__(self, server, *, target_ref, spec, limits, exchange, read_lease, archive_original=None):
        server.validate()
        self.server, self.target_ref = server, target_ref
        self.spec, self.limits = specification(asdict(spec), asdict(limits))
        self.exchange, self.read_lease = exchange, read_lease
        self.archive_original = archive_original

    @property
    def capacity_namespace(self):
        return digest({'protocol': PROTOCOL, 'hostKey': self.server.host_key})

    @property
    def configuration_fingerprint(self):
        return digest({'protocol': PROTOCOL, 'server': self.server.pin(),
                       'spec': asdict(self.spec), 'limits': asdict(self.limits)})

    async def preflight(self, *, before_effect):
        try:
            result = await asyncio.to_thread(lambda: self.exchange(
                {'protocol': PROTOCOL, 'action': 'capabilities', 'root': self.server.allowed_root},
                before_effect=before_effect))
            encoded(result, MAX_REQUEST_BYTES)
            require(type(result) is dict and result.get('protocol') == PROTOCOL
                    and result.get('platform') == 'linux'
                    and all(result.get(key) is True for key in ('rootReady', 'fork', 'proc', 'rlimits', 'processCustody'))
                    and all(result.get(key) is False for key in ('scheduler', 'gpuAllocation', 'automaticInstallation'))
                    and result.get('isolation') == {'aggregateQuota': False,
                        'hostileCodeSandbox': False, 'networkIsolation': False})
        except (ValueError, TypeError, KeyError, OSError):
            raise ValueError('SSH_PROCESS_PREFLIGHT_UNAVAILABLE') from None

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

    def _observe(self, lease, action, before_effect=None, cancelled=None):
        sent = self._request(lease, action)
        result = self.exchange(sent, before_effect=before_effect, cancelled=cancelled)
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
        released = stopped and (action == 'reclaim' or
                               action == 'inspect' and lease.get('releaseAck') in {'unknown', 'accepted'})
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
                raise SSHExchangeCancelled('SSH_PROCESS_SUBMIT_CANCELLED')
            outcome = before_effect()
            if isawaitable(outcome):
                if iscoroutine(outcome):
                    outcome.close()
                raise ValueError('SSH_PROCESS_SYNC_AUTHORITY_REQUIRED')
            if cancelled.is_set():
                raise SSHExchangeCancelled('SSH_PROCESS_SUBMIT_CANCELLED')
        worker = asyncio.create_task(asyncio.to_thread(self._observe, lease, 'submit', fresh, cancelled))
        try:
            return (await asyncio.shield(worker))[0]
        except asyncio.CancelledError:
            cancelled.set()
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    cancelled.set()
                except SSHExchangeCancelled:
                    break
            try:
                worker.result()
            except SSHExchangeCancelled:
                pass
            raise

    async def _original(self, lease_id, owner, action):
        lease = self.read_lease(owner, lease_id)
        require(lease['id'] == lease_id and lease['ownerId'] == owner)
        receipt = (await asyncio.to_thread(self._observe, lease, action))[0]
        if receipt['state'] == 'RECLAIMED':
            if self.archive_original is None:
                raise ValueError('SSH_PROCESS_ARCHIVE_REQUIRED')
            await self.archive_original(owner, lease_id)
        return receipt

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
