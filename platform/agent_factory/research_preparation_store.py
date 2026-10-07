"""Original bounded-process tokenizer preparation evidence in managed storage.

Large tensor files remain in managed storage. Only a small immutable reference
uses the ordinary artifact budget. No candidate path, stdout or provenance is
accepted as authority. This adapter does not execute training or deserialize ML.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os

from .research_checkpoint import checkpoint_binding, open_verified_checkpoint
import re
from typing import cast
from .store import canonical, digest

_BASENAME = 'token-bytes.safetensors'
_MAXIMUM = 16 * 1024**2
_KEY = 'research-tokenizer-preparation-v1'
_NAME = 'research-tokenizer-preparation-reference.json'


def _require(value):
    if not value:
        raise ValueError('RESEARCH_PREPARATION_CUSTODY_INVALID')


class ResearchPreparationStore:
    def __init__(self, store, auth, resources, storage, *, preparation_manifest_sha256, source_sha256):
        for value in (preparation_manifest_sha256, source_sha256):
            _require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value))
        self.store, self.auth, self.resources, self.storage = store, auth, resources, storage
        self._manifest, self._source = preparation_manifest_sha256, source_sha256

    def _original(self, owner, lease_id, *, stopped):
        self.auth.require(owner, 'run')
        runtime = self.resources.execution_runtime('bounded-process-run-v1')
        lease, target, task, _ = runtime._custody(lease_id)
        _require(lease['ownerId'] == owner and task['owner_id'] == owner and not task['cancel_requested'])
        plan = self.store.plan(lease['planId'], owner)
        _require(task['id'] == lease['localTaskId'] and task['run_id'] == lease['nativeRunId']
                 and task['plan_id'] == plan['id'] and lease['planHash'] == digest(plan))
        from .autoresearch_custody import require_original_custody
        require_original_custody(self.store, owner, plan, runtime._context(task), stopped=stopped)
        authorized = self.resources._authorize(owner, lease['connectionRef'])
        _require(lease['targetFingerprint'] == self.resources._target_fingerprint(authorized)
                 and self.resources._target_fingerprint(target) == lease['targetFingerprint'])
        rows = self.store.sql('SELECT * FROM af_process_runs WHERE task_id=:task AND effect_key=:effect',
            task=task['id'], effect='bounded-process-run-v1')
        _require(len(rows) == 1 and rows[0]['lease_id'] == lease_id and rows[0]['owner_id'] == owner
                 and rows[0]['native_run_id'] == task['run_id'])
        rows = self.store.sql('SELECT body FROM af_process_allocations WHERE id=:id AND owner_id=:owner', id=lease_id, owner=owner)
        _require(len(rows) == 1)
        record = rows[0]['body']; record = json.loads(record) if isinstance(record, str) else record
        original = record['binding']
        _require(record['bindingHash'] == digest(original)
                 and record['configurationFingerprint'] == target.provider.configuration_fingerprint
                 and all(original.get(key) == lease.get(key) for key in
                    ('id', 'ownerId', 'localTaskId', 'nativeRunId', 'planId', 'planHash', 'fingerprint', 'targetFingerprint')))
        job = record.get('processPin', {}).get('id')
        _require(type(job) is str and lease.get('providerJobId') in (None, job))
        if stopped:
            _require(lease['state'] == 'RECLAIMED' and lease['capacityHeld'] is False
                     and lease['executionStatus'] == 'COMPLETED' and type(lease['exitCode']) is int
                     and lease['exitCode'] == 0 and lease.get('stopEvidence', {}).get('allStopped') is True)
        else:
            _require(not task['terminal'] and record.get('released') is False)
            runtime.guard_lease(original)
        binding = checkpoint_binding({'ownerId': owner, 'taskId': task['id'], 'nativeRunId': task['run_id'],
            'planId': plan['id'], 'planFingerprint': plan['fingerprint'], 'leaseId': lease_id,
            'providerJobId': job, 'variantSha256': self._source, 'manifestSha256': self._manifest})
        return binding, {'artifactLimits': {'checkpointBytes': _MAXIMUM}}, target

    def _proof(self, target, binding):
        proof = target.provider.read_launch_proof(binding['leaseId'], binding['ownerId'])
        fields = {'schema', 'evidenceKind', 'descriptorSha256', 'sourceSha256', 'manifestSha256',
                  'variantSha256', 'leaseBindingSha256', 'processIdentitySha256', 'executionVerified'}
        rows = self.store.sql('SELECT body FROM af_process_allocations WHERE id=:id AND owner_id=:owner',
            id=binding['leaseId'], owner=binding['ownerId'])
        _require(len(rows) == 1)
        record = rows[0]['body']; record = json.loads(record) if isinstance(record, str) else record
        _require(type(proof) is dict and set(proof) == fields and type(proof['schema']) is int and proof['schema'] == 1
                 and proof['evidenceKind'] == 'research-tokenizer-preparation-v1' and proof['executionVerified'] is False
                 and proof['manifestSha256'] == self._manifest and proof['sourceSha256'] == self._source
                 and proof['variantSha256'] == self._source
                 and proof['leaseBindingSha256'] == digest(record['binding'])
                 and proof['processIdentitySha256'] == record['processPin']['identitySha256']
                 and all(type(proof[key]) is str and re.fullmatch('[a-f0-9]{64}', cast(str, proof[key])) for key in
                    ('descriptorSha256', 'leaseBindingSha256', 'processIdentitySha256')))
        return proof

    def reserve(self, owner, lease_id, *, disk_bytes):
        """Derive producer identity from original native custody before dispatch."""
        binding, _, _ = self._original(owner, lease_id, stopped=False)
        _require(type(disk_bytes) is int and 1024 <= disk_bytes <= 8 * 1024**4)
        task_id = binding['taskId']
        identifier = digest({'task': task_id, 'key': _KEY})

        def fresh():
            current, _, _ = self._original(owner, lease_id, stopped=False)
            _require(current == binding)

        # Retention uses a nonblocking, separate connection. Acquire it before
        # the admission/task transaction; never wait for it holding a task row.
        # The task lock matches Store.observed, preventing terminal hold release
        # between admission and the directory effect (including replay).
        with self.storage._lock(identifier), self.store.transaction():
            self.store.sql("SELECT pg_advisory_xact_lock(hashtext('af_admission'))")
            rows = self.store.sql("SELECT * FROM af_tasks WHERE id=:id FOR UPDATE", id=task_id)
            _require(len(rows) == 1 and rows[0]['owner_id'] == owner
                     and rows[0]['run_id'] == binding['nativeRunId']
                     and rows[0]['plan_id'] == binding['planId']
                     and not rows[0]['terminal'] and not rows[0]['cancel_requested'])
            fresh()
            holds = self.store.sql("SELECT bytes FROM af_disk_holds WHERE task_id=:task AND owner_id=:owner AND state='HELD'",
                                   task=task_id, owner=owner)
            _require(len(holds) == 1)
            extra = max(0, disk_bytes - holds[0]['bytes'])
            total = self.store.sql("SELECT COALESCE(SUM(bytes),0) AS n FROM af_disk_holds WHERE state='HELD'")[0]['n']
            _require(all(mount['freeBytes'] - total - extra >= self.store.settings.storage_low_water_bytes
                         for mount in self.storage.filesystems()))
            fresh()
            if extra:
                changed = self.store.sql("UPDATE af_disk_holds SET bytes=:bytes WHERE task_id=:task AND owner_id=:owner AND state='HELD' RETURNING bytes",
                                         bytes=disk_bytes, task=task_id, owner=owner)
                _require(len(changed) == 1 and changed[0]['bytes'] == disk_bytes)
            fresh()
            path = self.storage._directory(task_id, identifier, evidence=True)
            flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
            _require(os.name == 'posix' and getattr(os, 'O_DIRECTORY', 0) and getattr(os, 'O_NOFOLLOW', 0))
            fd = os.open(path, flags)
            try:
                info = os.fstat(fd)
                row = self.storage._object(owner, identifier)
                _require(row['identity'] == {'device': info.st_dev, 'directoryInode': info.st_ino})
                # This dedicated producer namespace alone becomes private.
                chmod = getattr(os, "fchmod", None)
                _require(callable(chmod))
                fresh()
                if callable(chmod):
                    chmod(fd, 0o700)
                os.fsync(fd)
                identity = {'device': info.st_dev, 'inode': info.st_ino}
            finally:
                os.close(fd)
            fresh()
        # A returned destination is not dispatch permission. The eventual
        # controller must supply its own cancellation/fresh-authority fence.
        fresh()
        return {'binding': binding, 'destination': {'root': str(path), 'basename': _BASENAME, 'rootIdentity': identity}}

    @contextmanager
    def _open(self, binding, maximum):
        identifier = digest({'task': binding['taskId'], 'key': _KEY})
        with self.storage._lock(identifier):
            self.storage._namespace()
            row = self.storage._object(binding['ownerId'], identifier)
            _require(row['task_id'] == binding['taskId'] and row['root_id'] == self.storage.root_id
                     and row['state'] == 'AVAILABLE' and row['evidence'] is True)
            identity = row['identity']
            _require(type(identity) is dict and set(identity) == {'device', 'directoryInode'})
            pin = {'device': identity['device'], 'inode': identity['directoryInode']}
            with open_verified_checkpoint(self.storage.objects / identifier, _BASENAME, pin, binding, maximum) as reader:
                tensors = reader.tensors
                _require(set(tensors) == {'token_bytes'} and tensors['token_bytes']['dtype'] == 'I32'
                         and len(tensors['token_bytes']['shape']) == 1 and tensors['token_bytes']['shape'][0] > 0)
                yield identifier, pin, reader

    def import_completed(self, owner, lease_id):
        binding, manifest, target = self._original(owner, lease_id, stopped=True)
        proof = self._proof(target, binding)
        maximum = min(manifest['artifactLimits']['checkpointBytes'], _MAXIMUM)
        with self._open(binding, maximum) as (identifier, pin, reader):
            reference = {'schema': 1, 'storageObjectId': identifier, 'basename': _BASENAME,
                'rootIdentity': pin, 'checkpoint': reader.identity, 'binding': binding,
                'executedHarnessSha256': proof['descriptorSha256'], 'sourceSha256': proof['sourceSha256']}
            raw = canonical(reference).encode()
            metadata = {'evidenceKind': 'research_tokenizer_preparation_reference', **binding,
                'executedHarnessSha256': proof['descriptorSha256'], 'syntheticFixture': target.synthetic_fixture}
            # Retention fence serializes import and unknown-ACK replay. Existing
            # references must match exactly; never publish a replacement.
            existing = [item for item in self.store.artifacts(binding['taskId']) if item['name'] == _NAME]
            _require(len(existing) <= 1)
            current, _, _ = self._original(owner, lease_id, stopped=True)
            _require(current == binding and target.provider.read_launch_proof(lease_id, owner) == proof)
            reader.reset()  # Recheck original FD and path immediately before publication.
            if existing:
                body, content = self.store.artifact(binding['taskId'], existing[0]['id'])
                _require(content == raw and body['provenance'] == metadata)
                return body
            return self.store.artifact_write(binding['taskId'], _NAME, raw, metadata=metadata)

    def identity(self, owner, task_id, artifact_id, maximum=_MAXIMUM):
        """Trusted evaluator reader: virtual tensor identity, never reference hash."""
        _require(type(maximum) is int and 0 < maximum <= _MAXIMUM)
        self.store.task(task_id, owner)
        body, raw = self.store.artifact(task_id, artifact_id)
        _require(body['name'] == _NAME and len(raw) <= 16384
                 and body['provenance'].get('evidenceKind') == 'research_tokenizer_preparation_reference')
        reference = json.loads(raw)
        _require(type(reference) is dict and set(reference) == {'schema', 'storageObjectId', 'basename',
            'rootIdentity', 'checkpoint', 'binding', 'executedHarnessSha256', 'sourceSha256'}
            and type(reference['schema']) is int and reference['schema'] == 1)
        binding = checkpoint_binding(reference['binding'])
        _require(binding['ownerId'] == owner and binding['taskId'] == task_id and body.get('id') == artifact_id and body.get('jobId') == task_id
                 and all(body['provenance'].get(key) == value for key, value in binding.items())
                 and body['provenance'].get('executedHarnessSha256') == reference['executedHarnessSha256'])
        current, _, target = self._original(binding['ownerId'], binding['leaseId'], stopped=True)
        _require(current == binding)
        proof = self._proof(target, binding)
        _require(proof['descriptorSha256'] == reference['executedHarnessSha256']
                 and proof['sourceSha256'] == reference['sourceSha256'])
        with self._open(binding, maximum) as (identifier, pin, reader):
            _require(reference['storageObjectId'] == identifier and reference['basename'] == _BASENAME
                     and reference['rootIdentity'] == pin and reference['checkpoint'] == reader.identity)
            current, _, current_target = self._original(binding['ownerId'], binding['leaseId'], stopped=True)
            _require(current == binding and current_target.provider.read_launch_proof(binding['leaseId'], binding['ownerId']) == proof)
            reader.reset()
            metadata = {'id': artifact_id, 'jobId': task_id, 'size': reader.identity['sizeBytes'],
                        'sha256': reader.identity['sha256'], 'provenance': {**binding,
                        'executedHarnessSha256': reference['executedHarnessSha256']}}
            return metadata, dict(reader.identity)

    def input_pin(self, owner, task_id, artifact_id):
        """Trusted internal consumer pin, never a public arbitrary-path endpoint."""
        _, identity = self.identity(owner, task_id, artifact_id)
        _, raw = self.store.artifact(task_id, artifact_id)
        reference = json.loads(raw)
        binding = checkpoint_binding(reference['binding'])
        _require(binding['ownerId'] == owner and binding['taskId'] == task_id)
        with self._open(binding, _MAXIMUM) as (identifier, pin, reader):
            _require(reader.identity == identity)
            current, _, target = self._original(owner, binding['leaseId'], stopped=True)
            _require(current == binding and self._proof(target, binding)['descriptorSha256'] == reference['executedHarnessSha256'])
            reader.reset()
            return {'root': str(self.storage.objects / identifier), 'basename': _BASENAME,
                'rootIdentity': pin, 'binding': binding, **identity}
