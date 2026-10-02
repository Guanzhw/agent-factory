"""Owned-process scheduling fault barrier, used only by acceptance fixtures.

Actual Factory/native lifecycle remains unchanged. The only injected fault is a
pause at a persisted boundary until the test hard-kills its own Popen tree.
There is no HTTP fault-control endpoint, model replacement or queue replacement.
"""
import asyncio
import json
import os
from pathlib import Path
import time

from agent_factory.config import Settings
from agent_factory.main import create_app


def main():
    directory = Path(os.environ["FACTORY_RECOVERY_FIXTURE_DIRECTORY"]).resolve()
    control = directory / "fault-control.json"
    marker = directory / "fault-boundary.json"
    settings = Settings.from_env()
    # Native queue and scheduler are real. Slow the FIRST process queue poll
    # only when requested, so a post-commit kill can precede worker binding.
    settings.queue_poll = float(os.getenv("FACTORY_RECOVERY_QUEUE_POLL", ".2"))
    settings.schedule_poll_seconds = float(os.getenv("FACTORY_RECOVERY_SCHEDULE_POLL", "60"))
    # Several independent crash cases intentionally retain UNKNOWN capacity
    # in this one disposable DB. Keep the production defaults unchanged.
    settings.max_user_tasks = 8
    app = create_app(settings)
    state = app.app.state.factory
    store, schedules = state["store"], state["schedules"]

    def phase():
        if not control.exists():
            return None
        return json.loads(control.read_text(encoding="utf-8")).get("phase")

    def mark(kind, data):
        marker.write_text(json.dumps({"phase": kind, **data}, sort_keys=True), encoding="utf-8")

    original_reserve = store.reserve_task
    def reserve_task(plan, request_id):
        result = original_reserve(plan, request_id)
        if request_id.startswith("schedule:") and phase() == "before-task-binding":
            mark("before-task-binding", {"taskId": result[0]["id"], "requestId": request_id})
            while True:
                time.sleep(.02)
        return result
    store.reserve_task = reserve_task

    original = schedules.bridge
    class NativeBoundary:
        def __getattr__(self, name):
            return getattr(original, name)

        async def submit(self, plan, owner, request_id):
            selected = phase()
            if selected == "before-native":
                mark(selected, {"taskId": plan["task_id"], "requestId": request_id})
                while True:
                    await asyncio.sleep(.02)
            result = await original.submit(plan, owner, request_id)
            if selected == "after-native":
                mark(selected, {"taskId": plan["task_id"], "requestId": request_id, "runId": result["run_id"]})
                while True:
                    await asyncio.sleep(.02)
            return result
    schedules.bridge = NativeBoundary()
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=settings.port, access_log=False)


if __name__ == "__main__":
    main()
