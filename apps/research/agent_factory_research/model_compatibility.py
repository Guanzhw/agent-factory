"""Research-specific recovery around the native model dispatcher."""
import asyncio
from agno.exceptions import InputCheckError
from agno.run.agent import RunOutput
from agent_factory.model_dispatch import DelegatingModel


class ResearchDelegatingModel(DelegatingModel):
    def _check_selected_plan(self, plan, context):
        from agent_factory.go_legacy import is_go_plan
        if is_go_plan(plan) and self.bindings.store.has_failures(context.session_id):
            raise InputCheckError("GO_TASK_STOPPED: prior development failure denies replay")

    def _check_task_wait(self, task):
        from .inference_wait import read, observe
        store = self.bindings.store
        wait = read(store, task["id"]) if callable(getattr(store, "sql", None)) else None
        if wait and wait["state"] in {"WAITING", "RESUMING"}:
            observe(store, task, wait)

    def _model_recovered(self, context):
        if callable(getattr(self.bindings.store, "sql", None)):
            self.bindings.store.sql("UPDATE af_inference_waits SET state='RECOVERED' WHERE task_id=:task AND state='RESUMING'", task=context.session_id)

    async def _apause(self, arguments, kwargs, error, *, streaming=False):
        from .inference_wait import prepare_pause, publish_pause
        response = kwargs.get("run_response")
        if response is None and len(arguments) > (6 if streaming else 5):
            response = arguments[6 if streaming else 5]
        messages = kwargs.get("messages", arguments[0] if arguments else None)
        if not isinstance(response, RunOutput) or not isinstance(messages, list):
            return None
        if await asyncio.to_thread(self._stop_development_replay, response):
            return None
        body = await asyncio.to_thread(prepare_pause, self.bindings.store, response, error)
        return None if body is None else publish_pause(self.bindings.store, response, messages, body, streaming=streaming)

    def _pause(self, arguments, kwargs, error, *, streaming=False):
        from .inference_wait import pause
        response = kwargs.get("run_response")
        if response is None and len(arguments) > (6 if streaming else 5):
            response = arguments[6 if streaming else 5]
        messages = kwargs.get("messages", arguments[0] if arguments else None)
        if not isinstance(response, RunOutput) or not isinstance(messages, list):
            return None
        if self._stop_development_replay(response):
            return None
        return pause(self.bindings.store, response, messages, error, streaming=streaming)

    def _stop_development_replay(self, response):
        """Persist final provider failure before the native queue can retry.

        Model-level 503 retries have already spent their explicit attempt budget.
        Queue restarts must not turn quota/unknown usage or an exhausted budget
        into a fresh model retry allowance. Existing protected failures provide
        the durable stop; no queue implementation or shared retry policy changes.
        """
        if response.model_provider != "opencode-go-development":
            return False
        from agent_factory.go_legacy import is_go_plan
        store = self.bindings.store
        task = store.task(response.session_id, response.user_id)
        if task["run_id"] != response.run_id:
            raise InputCheckError("Native failure identity differs from task binding")
        plan = store.plan(task["plan_id"], response.user_id)
        if not is_go_plan(plan):
            return False
        if not store.has_failures(task["id"]):
            store.event(task["id"], "protected_denied", "Development provider failure stops task replay",
                        {"code": "GO_TASK_STOPPED", "createsExecution": False})
        return True

    def _recovered(self, arguments, kwargs, *, streaming=False):
        if not callable(getattr(self.bindings.store, "sql", None)):
            return
        response = kwargs.get("run_response")
        if response is None and len(arguments) > (6 if streaming else 5):
            response = arguments[6 if streaming else 5]
        if isinstance(response, RunOutput):
            self.bindings.store.sql("UPDATE af_inference_waits SET state='RECOVERED' WHERE task_id=:task AND state='RESUMING'", task=response.session_id)

