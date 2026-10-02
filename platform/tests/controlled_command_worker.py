"""Owned demo-only process faults; never imported by application startup."""
import json
import os
from pathlib import Path

import uvicorn

from agent_factory.config import Settings
from agent_factory.control_commands import ControlCommands
from agent_factory.main import create_app


def main():
    configuration = json.loads(Path(os.environ["FACTORY_COMMAND_FIXTURE"]).read_text())
    root = Path(configuration["workspace"])
    app = create_app(Settings(db_url=configuration["database"], workspace=root, max_workers=1))
    state = app.app.state.factory
    fault_path = root / "fault.json"

    def fault(phase, command_id=None):
        if fault_path.exists():
            value = json.loads(fault_path.read_text())
            if value["phase"] == phase and (command_id is None or value["commandId"] == command_id):
                fault_path.unlink()  # Exactly one owned fault across restarts.
                (root / "crashed.json").write_text(json.dumps(value))
                os._exit(88)  # No lifespan/finally cleanup can manufacture proof.

    # Fixture-only fault after an owned rename, before its durable receipt.
    original_storage_state = state["store"].storage._state
    def storage_state(plan, phase, object_state, patch=None):
        fault("storage-before-" + phase, plan["id"])
        return original_storage_state(plan, phase, object_state, patch)
    state["store"].storage._state = storage_state

    original_dispatch = ControlCommands.dispatch
    async def dispatch(self, owner, task, command):
        fault("prepared", command)
        return await original_dispatch(self, owner, task, command)
    ControlCommands.dispatch = dispatch

    original_continue = state["bridge"].continue_run
    async def continuation(*args, **kwargs):
        command_id = kwargs.get("command_proof", {}).get("commandId")
        fault("before-native", command_id)
        with (root / "continuations.jsonl").open("a") as output:
            output.write(json.dumps({"commandId": command_id}) + "\n")
        result = await original_continue(*args, **kwargs)
        fault("after-native", command_id)
        return result
    state["bridge"].continue_run = continuation

    original_cancel = state["store"].delegation.cascade_cancel
    async def cancel(*args, **kwargs):
        result = await original_cancel(*args, **kwargs)
        fault("after-cancel")
        return result
    state["store"].delegation.cascade_cancel = cancel
    uvicorn.run(app, host="127.0.0.1", port=configuration["port"], log_level="warning")


if __name__ == "__main__":
    main()
