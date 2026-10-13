"""Research-only recovery of the original immutable experiment connection."""
from fastapi import HTTPException

from agent_factory.connections import ConnectionService
from agent_factory.store import digest


class ResearchConnectionService(ConnectionService):
    def cleanup_handle(self, owner, pin, *, adapter_ref, task_id):
        """Trusted reclaim only: exact old ORX handle, no refreshed execution grant.

        No HTTP route exposes this accessor. A persisted native launch intent
        and the immutable task experiment binding must already exist. Revoked
        or expired owner references remain revoked/expired; changed handles,
        owner/task/source pins and native identities are never substituted.
        """
        if adapter_ref != "openresearch-experiment-v1" or not isinstance(pin, dict):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: only original local experiment reclaim is supported")
        task = self.store.task(task_id, owner)
        native_db = self.store.native_db
        ticket = native_db.get_job(task["run_id"], strict=True) if native_db and task.get("run_id") else None
        expected_native = {"id": task.get("run_id"), "session_id": task_id, "user_id": owner,
                           "component_id": "factory-executor", "component_type": "agent"}
        if not ticket or any(ticket.get(key) != value for key, value in expected_native.items()):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: exact native task identity is unavailable")
        rows = self.store.sql("SELECT * FROM af_orx_task_experiments WHERE task_id=:task AND owner_id=:owner", task=task_id, owner=owner)
        if len(rows) != 1:
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: original experiment binding is unavailable")
        binding_row = rows[0]
        binding = binding_row["binding"]
        if (digest(binding) != binding_row["binding_hash"] or binding_row["plan_id"] != task["plan_id"]
                or binding_row["run_id"] != task["run_id"] or binding.get("ownerId") != owner
                or binding.get("taskId") != task_id or binding.get("planId") != task["plan_id"]
                or binding.get("nativeRunId") != task["run_id"]):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: original experiment identity changed")
        recorded_pin = binding.get("connection", {})
        if any(recorded_pin.get(key) != pin.get(key) for key in ("ref", "version", "fingerprint", "revision", "capabilities")):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: requested handle differs from original execution")
        intent = self.store.sql("SELECT effect_key,fingerprint FROM af_effects WHERE task_id=:task AND run_id=:run",
                                task=task_id, run=task["run_id"])
        expected_key = task["run_id"] + ":orx-experiment-launch-v1"
        request_hash = digest({key: value for key, value in binding.items() if key not in {"projectId", "experimentId"}})
        if not any(effect.get("effect_key") == expected_key and effect.get("fingerprint") == request_hash for effect in intent):
            raise HTTPException(409, "CLEANUP_BINDING_INVALID: durable launch intent is unavailable")
        with self._read() as connection:
            row = self._row(connection, owner, pin.get("ref"))
            body = row["body"]
            if (body["kind"] != "orx" or body["taskId"] not in {None, task_id}
                    or row["fingerprint"] != pin.get("fingerprint")
                    or any(body.get(key) != pin.get(key) for key in ("ref", "version", "revision", "capabilities", "taskId"))):
                raise HTTPException(409, "CLEANUP_BINDING_INVALID: immutable owner reference changed")
            trusted = self._trusted(row["registration_ref"], owner, connection)
            if (trusted.fingerprint != body["trustedFingerprint"] or trusted.adapter_ref != adapter_ref
                    or trusted.kind != "orx" or not callable(getattr(trusted.opaque_handle, "create_experiment_adapter", None))):
                raise HTTPException(409, "CLEANUP_BINDING_INVALID: original cleanup handle is unavailable")
            return trusted.opaque_handle

