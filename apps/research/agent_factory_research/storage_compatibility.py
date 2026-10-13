"""Read-only attribution of original research evidence and runtime storage."""
import hashlib
from pathlib import Path
from fastapi import HTTPException
from agent_factory.storage_governance import StorageGovernance


class ResearchStorageGovernance(StorageGovernance):
    def _protected_runtime_storage(self, owner):
        protected = []
        containers = []
        # Existing ORX evidence is measured, never adopted for cleanup. The
        # path is derived from authenticated owner and actual persisted task.
        experiments = self.store.sql("SELECT task_id FROM af_orx_task_experiments WHERE owner_id=:owner ORDER BY task_id LIMIT 10", owner=owner)
        for experiment in experiments:
            task_id = experiment["task_id"]
            path = Path(self.settings.workspace).resolve() / "orx-tasks" / hashlib.sha256(owner.encode()).hexdigest()[:24] / task_id
            item = {"taskId": task_id, "kind": "orx-evidence", "retentionProtected": True, "complete": False}
            try:
                observed = self.scan(path)
                item.update(logicalBytes=observed["logicalBytes"], allocatedBytes=observed["allocatedBytes"], complete=True)
            except (OSError, HTTPException):
                pass
            protected.append(item)
            if self.settings.runtime_tool_contract in {"local-orx-v1", "orx-evidence-v2"}:
                from .storage_runtime import observe_container
                containers.append(observe_container(Path(self.settings.workspace), owner, task_id))
        return protected, containers

    def _summary(self, owner, reconciliation_errors):
        result = super()._summary(owner, reconciliation_errors)
        result["observationLimits"]["orxDirectories"] = 10
        return result
