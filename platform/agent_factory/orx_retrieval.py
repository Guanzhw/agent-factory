"""Free public literature CLI in a selected, task-owned Linux resource boundary.

This is containment for a reviewed fixed CLI, not an untrusted-code sandbox or
an egress firewall. No credentials, proxy configuration or arbitrary URLs enter
the container. The existing Docker bridge must work; there is no host fallback.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .openresearch import OpenResearchAdapter, OpenResearchError
from .orx_linux import TaskLinuxContainer
from .orx_pins import approved_pin


class LinuxRetrievalAdapter(OpenResearchAdapter):
    transport_kind = "bounded_linux_public_retrieval"

    def __init__(self, *, environment: dict[str, Any], **kwargs):
        super().__init__(**kwargs)
        if self.pin != approved_pin("linux"):
            raise OpenResearchError("UNVERIFIED_BINARY", "Approved Linux retrieval build required")
        self._verify_hash()
        self.environment = dict(environment)
        self.container = TaskLinuxContainer(self.task_id, self.owner_id, self.scope,
            self.binary, self.environment, profile="public-retrieval-v1")

    async def _spawn(self, argv):
        async def start():
            args = await asyncio.to_thread(self.container.exec_argv, argv, self.env)
            return await asyncio.create_subprocess_exec(*args, cwd=self.scope,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": self.env["HOME"]},
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True)
        launch = asyncio.create_task(start())
        try:
            return await asyncio.shield(launch)
        except asyncio.CancelledError:
            # Cancellation during the thread-backed Docker start must not lose
            # ownership of a process created after the awaiting task was canceled.
            process = None
            try:
                process = await launch
            finally:
                if process is None:
                    await asyncio.to_thread(self.container.terminate)
                else:
                    await self._terminate(process)
            raise

    async def _terminate(self, process):
        # docker-exec exit alone does not prove that owned descendants stopped.
        try:
            await asyncio.to_thread(self.container.terminate)
        finally:
            await super()._terminate(process)

    def containment_evidence(self):
        return self.container.evidence()


class TaskLinuxRetrievalProvider:
    def __init__(self, binary: Path):
        self.binary = binary.resolve()

    def create_retrieval_adapter(self, *, environment, **kwargs):
        return LinuxRetrievalAdapter(binary=self.binary, environment=environment,
                                     enabled=True, **kwargs)
