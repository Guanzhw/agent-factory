"""Original stopped-run checkpoint import into existing evidence storage.

Large tensor files remain in managed storage. Only a small immutable reference
uses the ordinary artifact budget. No candidate path, stdout or provenance is
accepted as authority. This adapter does not execute training or deserialize ML.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os

from .research_checkpoint import checkpoint_binding, open_verified_checkpoint
from .research_manifest import manifest_fingerprint
from .store import canonical, digest

_BASENAME = 'checkpoint.safetensors'
_KEY = 'research-checkpoint-v1'
_NAME = 'research-checkpoint-reference.json'


def _require(value):
    if not value:
        raise ValueError('RESEARCH_CHECKPOINT_CUSTODY_INVALID')


class ResearchCheckpointStore:
    def __init__(self, store, auth, resources, storage):
        self.store, self.auth, self.resources, self.storage = store, auth, resources, storage

    def _original(self, owner, lease_id, *, stopped):
        self.auth.require(owner, 'run')
        runtime = self.resources.execution_runtime('research-process-run-v1')
        lease, target, task, _ = runtime._custody(lease_id)
        _require(lease['ownerId'] == owner and task['owner_id'] == owner and not task['cancel_requested'])
        plan = self.store.plan(lease['planId'], owner)
        self.store.require_plan_execution(owner, plan, run_context=runtime._context(task))
        self.resources._authorize(owner, lease['connectionRef'])
        _, manifest, variant = runtime._config(task, plan)
        _require(lease['executionGuard']['manifestSha256'] == manifest_fingerprint(manifest)
                 and lease['executionGuard']['variantSha256'] == variant)
        if stopped:
            _require(lease['state'] == 'RECLAIMED' and lease['capacityHeld'] is False
                     and lease['executionStatus'] == 'COMPLETED' and type(lease['exitCode']) is int
                     and lease['exitCode'] == 0 and lease.get('stopEvidence', {}).get('allStopped') is True
                     and lease.get('gpuEvidence', {}).get('state') == 'RELEASED')
        binding = checkpoint_binding({'ownerId': owner, 'taskId': task['id'], 'nativeRunId': task['run_id'],
            'planId': plan['id'], 'planFingerprint': plan['fingerprint'], 'leaseId': lease_id,
            'providerJobId': lease['providerJobId'], 'variantSha256': variant,
            'manifestSha256': manifest_fingerprint(manifest)})
        return binding, manifest, target

    def reserve(self, binding, *, disk_bytes):
        """Trusted prelaunch callback; binding comes from original provider journal.

        Disk admission grows the existing task hold under the same global lock.
        It remains a conservative hold, not a filesystem quota.
        """
        binding = checkpoint_binding(binding)
        _require(type(disk_bytes) is int and 1024 <= disk_bytes <= 8 * 1024**4)
        owner, task_id = binding['ownerId'], binding['taskId']
        def current_authority():
            self.auth.require(owner, 'run')
            task = self.store.task(task_id, owner)
            plan = self.store.plan(binding['planId'], owner)
            _require(task['run_id'] == binding['nativeRunId'] and task['plan_id'] == binding['planId']
                     and plan['fingerprint'] == binding['planFingerprint']
                     and not task['terminal'] and not task['cancel_requested'])
            runtime = self.resources.execution_runtime('research-process-run-v1')
            self.store.require_plan_execution(owner, plan, run_context=runtime._context(task))
            # The allocation journal has the original job before the resource lease's
            # asynchronous provider response. Verify that original row, not a caller ID.
            rows = self.store.sql('SELECT body FROM af_process_allocations WHERE id=:id AND owner_id=:owner',
                                  id=binding['leaseId'], owner=owner)
            _require(len(rows) == 1)
            record = rows[0]['body']
            record = json.loads(record) if isinstance(record, str) else record
            original = record['binding']
            _require(record.get('processPin', {}).get('id') == binding['providerJobId']
                     and original['localTaskId'] == task_id and original['nativeRunId'] == binding['nativeRunId']
                     and original['planId'] == binding['planId'] and original['planHash'] == digest(plan)
                     and original['executionGuard']['manifestSha256'] == binding['manifestSha256']
                     and original['executionGuard']['variantSha256'] == binding['variantSha256'])
            runtime.guard_lease(original)

        current_authority()
        identifier = digest({'task': task_id, 'key': _KEY})
        # Retention must be acquired outside the metadata transaction, including
        # a size-one metadata pool. Match global admission -> task lock ordering.
        with self.storage._lock(identifier):
            with self.store.transaction():
                self.store.sql("SELECT pg_advisory_xact_lock(hashtext('af_admission'))")
                tasks = self.store.sql("SELECT id FROM af_tasks WHERE id=:id AND owner_id=:owner FOR UPDATE",
                                       id=task_id, owner=owner)
                _require(len(tasks) == 1)
                current_authority()  # Both lock waits can outlive authority.
                holds = self.store.sql("SELECT bytes FROM af_disk_holds WHERE task_id=:task AND owner_id=:owner AND state='HELD' FOR UPDATE",
                                       task=task_id, owner=owner)
                _require(len(holds) == 1)
                amount = max(disk_bytes, holds[0]['bytes'])
                extra = amount - holds[0]['bytes']
                total = self.store.sql("SELECT COALESCE(SUM(bytes),0) AS n FROM af_disk_holds WHERE state='HELD'")[0]['n']
                _require(all(mount['freeBytes'] - total - extra >= self.store.settings.storage_low_water_bytes
                             for mount in self.storage.filesystems()))
                current_authority()
                changed = self.store.sql("UPDATE af_disk_holds SET bytes=:bytes WHERE task_id=:task AND owner_id=:owner AND state='HELD' RETURNING bytes",
                                         bytes=amount, task=task_id, owner=owner)
                _require(len(changed) == 1 and changed[0]['bytes'] == amount)
                current_authority()
                path = self.storage._directory(task_id, identifier, evidence=True)
                flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
                _require(os.name == 'posix' and getattr(os, 'O_DIRECTORY', 0) and getattr(os, 'O_NOFOLLOW', 0))
                fd = os.open(path, flags)
                try:
                    info = os.fstat(fd)
                    row = self.storage._object(owner, identifier)
                    _require(row['identity'] == {'device': info.st_dev, 'directoryInode': info.st_ino})
                    chmod = getattr(os, "fchmod", None)
                    _require(callable(chmod))
                    current_authority()
                    if callable(chmod):
                        chmod(fd, 0o700)
                    os.fsync(fd)
                    identity = {'device': info.st_dev, 'inode': info.st_ino}
                finally:
                    os.close(fd)
                current_authority()
                return {'root': str(path), 'basename': _BASENAME, 'rootIdentity': identity}

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
                yield identifier, pin, reader

    def import_completed(self, owner, lease_id):
        binding, manifest, target = self._original(owner, lease_id, stopped=True)
        proof = target.provider.read_launch_proof(lease_id, owner)
        _require(proof['manifestSha256'] == binding['manifestSha256']
                 and proof['variantSha256'] == binding['variantSha256']
                 and proof.get('checkpoint') is None and proof.get('evaluationContractSha256') is None)
        maximum = min(manifest['artifactLimits']['checkpointBytes'], 2 * 1024**3)
        with self._open(binding, maximum) as (identifier, pin, reader):
            reference = {'schema': 1, 'storageObjectId': identifier, 'basename': _BASENAME,
                'rootIdentity': pin, 'checkpoint': reader.identity, 'binding': binding,
                'executedHarnessSha256': proof['descriptorSha256'], 'sourceSha256': proof['sourceSha256']}
            raw = canonical(reference).encode()
            metadata = {'evidenceKind': 'research_checkpoint_reference', **binding,
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

    def identity(self, task_id, artifact_id, maximum):
        """Trusted evaluator reader: virtual tensor identity, never reference hash."""
        _require(type(maximum) is int and 0 < maximum <= 2 * 1024**3)
        body, raw = self.store.artifact(task_id, artifact_id)
        _require(body['name'] == _NAME and len(raw) <= 16384
                 and body['provenance'].get('evidenceKind') == 'research_checkpoint_reference')
        reference = json.loads(raw)
        _require(type(reference) is dict and set(reference) == {'schema', 'storageObjectId', 'basename',
            'rootIdentity', 'checkpoint', 'binding', 'executedHarnessSha256', 'sourceSha256'}
            and type(reference['schema']) is int and reference['schema'] == 1)
        binding = checkpoint_binding(reference['binding'])
        _require(binding['taskId'] == task_id and body.get('id') == artifact_id and body.get('jobId') == task_id
                 and all(body['provenance'].get(key) == value for key, value in binding.items())
                 and body['provenance'].get('executedHarnessSha256') == reference['executedHarnessSha256'])
        current, _, target = self._original(binding['ownerId'], binding['leaseId'], stopped=True)
        _require(current == binding)
        proof = target.provider.read_launch_proof(binding['leaseId'], binding['ownerId'])
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
