"""Observe existing research waits without creating another execution owner."""
import asyncio
from agno.exceptions import RunCancelledException
from fastapi import HTTPException
from agent_factory.lifecycle_observer import FactoryLifecycleObserver


class ResearchLifecycleObserver(FactoryLifecycleObserver):
    def _mark_cancel(self, task: dict, reason: str) -> None:
        # Store.transaction shares its connection across nested metadata calls.
        # Publish research wait cleanup with the original task cancellation.
        with self.store.transaction():
            self.store.sql("UPDATE af_inference_waits SET state='STOPPING' WHERE task_id=:task AND state IN ('WAITING','RESUMING')", task=task["id"])
            super()._mark_cancel(task, reason)

    async def _observe_application_waits(self, root):
        from .inference_wait import read as read_wait, observe as observe_wait, reconcile_recovered_children
        for current_task in self._group(root)[0]:
            waiting = read_wait(self.store, current_task["id"])
            if waiting and waiting["state"] == "RECOVERED":
                try:
                    await asyncio.to_thread(reconcile_recovered_children, self.store, current_task, waiting)
                except RunCancelledException:
                    pass  # Preserve ordinary child/origin cancellation semantics.
                except Exception as error:
                    latest = read_wait(self.store, current_task["id"])
                    if latest and latest["state"] == "RECOVERED" and latest["controlId"] == waiting["controlId"]:
                        self.store.event(current_task["id"], "protected_denied", "Original child recovery reconciliation denied",
                            {"boundary": "inference-child-reconciliation", "errorType": type(error).__name__})
            if waiting and waiting["state"] in {"WAITING", "RESUMING"}:
                try:
                    await asyncio.to_thread(observe_wait, self.store, current_task, waiting)
                except Exception as error:
                    if isinstance(error, RunCancelledException):
                        continue
                    latest = read_wait(self.store, current_task["id"])
                    if not latest or latest["state"] not in {"WAITING", "RESUMING"} or latest["controlId"] != waiting["controlId"]:
                        continue
                    with self.store.transaction():
                        changed = self.store.sql("""UPDATE af_inference_waits SET state='STOPPING'
                            WHERE task_id=:task AND body->>'controlId'=:control AND state IN ('WAITING','RESUMING') RETURNING task_id""",
                            task=current_task["id"], control=waiting["controlId"])
                        if changed:
                            self.store.event(current_task["id"], "protected_denied", "Bounded inference wait requires original-work cleanup",
                                {"boundary": "inference-wait", "errorType": type(error).__name__,
                                 "code": (str(error.detail).split(":", 1)[0] if isinstance(error, HTTPException)
                                          and isinstance(error.detail, str) and error.detail.startswith(("INFERENCE_WAIT_", "USAGE_BUDGET_", "ORIGIN_AUTHORITY_"))
                                          else getattr(error, "code", None))})
