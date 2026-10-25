"""Observe existing research waits without creating another execution owner."""
import asyncio
from agno.exceptions import RunCancelledException
from fastapi import HTTPException
from agent_factory.lifecycle_observer import FactoryLifecycleObserver


class ResearchObservation:
    @staticmethod
    def mark_cancel(store, task_id):
        store.sql("UPDATE af_inference_waits SET state='STOPPING' WHERE task_id=:task AND state IN ('WAITING','RESUMING')", task=task_id)

    @staticmethod
    def summary_status(observer, task, status):
        from .inference_wait import CONTROL_NAME, read as read_wait
        waiting = read_wait(observer.store, task["id"])
        if waiting and waiting["state"] == "WAITING" and not task["cancel_requested"] and not observer.store.has_failures(task["id"]):
            ticket = observer._binding(task)
            if ticket and ticket["status"] == "paused" and any(
                    (item.get("tool_execution") or {}).get("tool_name") == CONTROL_NAME
                    and (item.get("tool_execution") or {}).get("external_execution_required") is True
                    for item in ticket.get("requirements", [])):
                return "waiting_approval"
        return status

    @staticmethod
    async def observe_waits(observer, current_task):
        from .inference_wait import read as read_wait, observe as observe_wait, reconcile_recovered_children
        waiting = read_wait(observer.store, current_task["id"])
        if waiting and waiting["state"] == "RECOVERED":
            try:
                await asyncio.to_thread(reconcile_recovered_children, observer.store, current_task, waiting)
            except RunCancelledException:
                pass  # Preserve ordinary child/origin cancellation semantics.
            except Exception as error:
                latest = read_wait(observer.store, current_task["id"])
                if latest and latest["state"] == "RECOVERED" and latest["controlId"] == waiting["controlId"]:
                    observer.store.event(current_task["id"], "protected_denied", "Original child recovery reconciliation denied",
                        {"boundary": "inference-child-reconciliation", "errorType": type(error).__name__})
        if waiting and waiting["state"] in {"WAITING", "RESUMING"}:
            try:
                await asyncio.to_thread(observe_wait, observer.store, current_task, waiting)
            except Exception as error:
                if isinstance(error, RunCancelledException):
                    return
                latest = read_wait(observer.store, current_task["id"])
                if not latest or latest["state"] not in {"WAITING", "RESUMING"} or latest["controlId"] != waiting["controlId"]:
                    return
                with observer.store.transaction():
                    changed = observer.store.sql("""UPDATE af_inference_waits SET state='STOPPING'
                        WHERE task_id=:task AND body->>'controlId'=:control AND state IN ('WAITING','RESUMING') RETURNING task_id""",
                        task=current_task["id"], control=waiting["controlId"])
                    if changed:
                        observer.store.event(current_task["id"], "protected_denied", "Bounded inference wait requires original-work cleanup",
                            {"boundary": "inference-wait", "errorType": type(error).__name__,
                             "code": (str(error.detail).split(":", 1)[0] if isinstance(error, HTTPException)
                                      and isinstance(error.detail, str) and error.detail.startswith(("INFERENCE_WAIT_", "USAGE_BUDGET_", "ORIGIN_AUTHORITY_"))
                                      else getattr(error, "code", None))})


class ResearchLifecycleObserver(FactoryLifecycleObserver):
    """Legacy standalone entry; production uses registered application hooks."""
    def _summary_status(self, task, status):
        return ResearchObservation.summary_status(self, task, status)

    def _mark_cancel(self, task, reason):
        with self.store.transaction():
            ResearchObservation.mark_cancel(self.store, task['id'])
            super()._mark_cancel(task, reason)

    async def _observe_application_waits(self, root):
        for task in self._group(root)[0]:
            await ResearchObservation.observe_waits(self, task)
