"""Controlled, inert research driver fixture. No process/GPU execution or enforcement.

Use only with synthetic targets. Durable assertions simulate custody for native
integration tests; they are never evidence about a physical device.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
from types import SimpleNamespace

from sqlalchemy import text

from agent_factory.gpu_custody import GpuBinding, evidence_fingerprint, validate_binding, validate_gpu_evidence
from agent_factory.store import canonical, digest


class ControlledResearchDriver:
    def __init__(self, store, gpu_binding, limits=None, namespace="7" * 64, *,
                 lose_allocate_ack=False, unknown_stop=False, lose_release_ack=False):
        self.store = store
        self.gpu_binding = gpu_binding if type(gpu_binding) is GpuBinding else GpuBinding(
            validate_binding(gpu_binding)["receiverNamespace"], validate_binding(gpu_binding)["deviceId"])
        self.limits = limits or SimpleNamespace(wall_seconds=600, address_space_mb=128, file_size_bytes=65536)
        if (type(namespace) is not str or len(namespace) != 64 or any(c not in "0123456789abcdef" for c in namespace)
                or not 0 < self.limits.file_size_bytes <= 65536):
            raise ValueError("CONTROLLED_DRIVER_CONFIGURATION")
        self.capacity_namespace = namespace
        self.configuration_fingerprint = digest({"fixture": "inert-research-driver-v1", "namespace": namespace,
            "gpuBinding": self.gpu_binding.to_dict(), "limits": vars(self.limits)})
        self.lose_allocate_ack = lose_allocate_ack
        self.unknown_stop = unknown_stop
        self.lose_release_ack = lose_release_ack

    @contextmanager
    def _transaction(self):
        with self.store.engine.connect() as conn:
            if conn.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "af_process_allocations"})
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _load(self, conn, lease_id, owner):
        row = conn.execute(text("SELECT owner_id,body FROM af_process_allocations WHERE id=:id"), {"id": lease_id}).first()
        if row is None or row[0] != owner:
            raise ValueError("CONTROLLED_DRIVER_ORIGINAL_MISSING")
        record = json.loads(row[1]) if isinstance(row[1], str) else row[1]
        if (record.get("configurationFingerprint") != self.configuration_fingerprint
                or record["binding"]["id"] != lease_id or record["binding"]["ownerId"] != owner
                or record["bindingHash"] != digest(record["binding"])):
            raise ValueError("CONTROLLED_DRIVER_ORIGINAL_CHANGED")
        return record

    def _save(self, conn, record, *, insert=False):
        body = "CAST(:body AS JSONB)" if conn.dialect.name == "postgresql" else ":body"
        query = (f"INSERT INTO af_process_allocations(id,owner_id,body) VALUES(:id,:owner,{body})" if insert else
                 f"UPDATE af_process_allocations SET body={body} WHERE id=:id AND owner_id=:owner")
        conn.execute(text(query), {"id": record["binding"]["id"], "owner": record["binding"]["ownerId"], "body": canonical(record)})

    @property
    def launches(self):
        with self._transaction() as conn:
            rows = conn.execute(text("SELECT body FROM af_process_allocations")).all()
            records = [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in rows]
            return sum(record.get("launches", 0) for record in records
                       if record.get("configurationFingerprint") == self.configuration_fingerprint)

    async def allocate(self, lease_id, owner, fingerprint, limits):
        raise ValueError("CONTROLLED_DRIVER_NATIVE_BINDING_REQUIRED")

    async def allocate_bound(self, lease, *, before_effect):
        if not callable(before_effect) or validate_binding(lease.get("gpuBinding")) != self.gpu_binding.to_dict():
            raise ValueError("CONTROLLED_DRIVER_BINDING")
        evidence_fingerprint(lease)
        with self._transaction() as conn:
            existing = conn.execute(text("SELECT id FROM af_process_allocations WHERE id=:id"), {"id": lease["id"]}).first()
            if existing:
                record = self._load(conn, lease["id"], lease["ownerId"])
                if record["binding"]["fingerprint"] != lease["fingerprint"]:
                    raise ValueError("CONTROLLED_DRIVER_ORIGINAL_CHANGED")
                return self._snapshot(record)
            record = {"binding": deepcopy(lease), "bindingHash": digest(lease),
                "configurationFingerprint": self.configuration_fingerprint, "state": "UNKNOWN", "released": False,
                "executionStatus": "UNKNOWN", "exitCode": None, "stopKind": None, "launches": 0, "outputHex": None}
            self._save(conn, record, insert=True)
        # Durable intent exists before the simulated dispatch. Failure never replays.
        with self._transaction() as conn:
            record = self._load(conn, lease["id"], lease["ownerId"])
            if record["state"] != "UNKNOWN" or record["launches"]:
                return self._snapshot(record)
            before_effect()
            record.update(state="RUNNING", executionStatus="RUNNING", launches=1)
            self._save(conn, record)
        if self.lose_allocate_ack:
            raise RuntimeError("CONTROLLED_ALLOCATE_ACK_LOST")
        return self._snapshot(record)

    def _snapshot(self, record):
        lease = record["binding"]
        process = {"taskId": lease["localTaskId"], "nativeRunId": lease["nativeRunId"], "planId": lease["planId"],
                   "bindingFingerprint": record["bindingHash"]}
        proof = None
        if record["released"]:
            proof = {"kind": "never-dispatched" if record["stopKind"] == "never-dispatched" else
                     "original-process-stopped-and-device-released", "processBindingFingerprint": record["bindingHash"],
                     "deviceObservationSha256": digest({"controlledFixture": True, "binding": record["bindingHash"], "released": True})}
        result = {"leaseId": lease["id"], "ownerId": lease["ownerId"], "fingerprint": lease["fingerprint"],
            "providerJobId": "controlled-" + lease["id"], "processBinding": process,
            "state": record["state"], "released": record["released"], "capacityHeld": not record["released"],
            "executionStatus": record["executionStatus"], "exitCode": record["exitCode"],
            "syntheticFixture": True, "stopEvidence": {"allStopped": True, "kind": record["stopKind"]} if record["stopKind"] else None,
            "gpuBinding": self.gpu_binding.to_dict(), "gpuEvidence": {"schema": 1,
                "bindingFingerprint": evidence_fingerprint(lease), "state": "RELEASED" if record["released"] else
                "UNKNOWN" if record["state"] == "UNKNOWN" else "HELD", "releaseProof": proof},
            "enforcement": {"cpu": "per-process-RLIMIT_CPU", "memory": "per-process-RLIMIT_AS",
                "fileSize": "per-file-RLIMIT_FSIZE", "wall": "cooperative-process-group-guardian",
                "aggregateQuota": False, "hostileCodeSandbox": False, "networkIsolation": False}}
        validate_gpu_evidence(lease, result)
        return result

    async def inspect(self, lease_id, owner):
        with self._transaction() as conn:
            return self._snapshot(self._load(conn, lease_id, owner))

    async def cancel(self, lease_id, owner):
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
            if not record["released"] and not record["stopKind"]:
                if self.unknown_stop:
                    record.update(state="UNKNOWN", executionStatus="UNKNOWN")
                else:
                    record.update(state="CANCEL_CONFIRMED", executionStatus="CANCELLED", exitCode=-15,
                        stopKind="original-root-reaped-and-no-live-process-group-members" if record["launches"] else "never-dispatched")
                self._save(conn, record)
            return self._snapshot(record)

    async def reclaim(self, lease_id, owner):
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
            if not record["stopKind"]:
                raise ValueError("CONTROLLED_DRIVER_STOP_UNKNOWN")
            record.update(state="RECLAIMED", released=True)
            self._save(conn, record)
        if self.lose_release_ack:
            raise RuntimeError("CONTROLLED_RELEASE_ACK_LOST")
        return self._snapshot(record)

    def complete(self, lease_id, owner, output: bytes):
        if type(output) is not bytes or not 0 < len(output) <= self.limits.file_size_bytes:
            raise ValueError("CONTROLLED_DRIVER_OUTPUT_BOUNDS")
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
            if record["released"] or record["stopKind"] or record["launches"] != 1:
                raise ValueError("CONTROLLED_DRIVER_NOT_RUNNING")
            record.update(state="COMPLETED", executionStatus="COMPLETED", exitCode=0, outputHex=output.hex(),
                          stopKind="original-root-reaped-and-no-live-process-group-members")
            self._save(conn, record)
            return self._snapshot(record)

    def read_completed_output(self, lease_id, owner):
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
            self._snapshot(record)
            if not (record["released"] and record["executionStatus"] == "COMPLETED" and record["exitCode"] == 0 and record["stopKind"]):
                raise ValueError("CONTROLLED_DRIVER_OUTPUT_UNCONFIRMED")
            raw = bytes.fromhex(record["outputHex"])
            if not 0 < len(raw) <= self.limits.file_size_bytes:
                raise ValueError("CONTROLLED_DRIVER_OUTPUT_BOUNDS")
            return raw


ResearchDriverFixture = ControlledResearchDriver
