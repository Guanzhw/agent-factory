"""Free public literature CLI in a selected, task-owned Linux resource boundary.

This is containment for a reviewed fixed CLI, not an untrusted-code sandbox or
an egress firewall. No credentials, proxy configuration or arbitrary URLs enter
the container. The existing Docker bridge must work; there is no host fallback.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from weakref import WeakValueDictionary

from .openresearch import OpenResearchAdapter, OpenResearchError
from .orx_linux import TaskLinuxContainer
from .orx_pins import approved_pin


class LinuxRetrievalAdapter(OpenResearchAdapter):
    transport_kind = "bounded_linux_public_retrieval"

    def __init__(self, *, environment: dict[str, Any], resource_lock: asyncio.Lock | None = None, **kwargs):
        super().__init__(**kwargs)
        if self.pin != approved_pin("linux"):
            raise OpenResearchError("UNVERIFIED_BINARY", "Approved Linux retrieval build required")
        self._verify_hash()
        self.environment = dict(environment)
        self._resource_lock = resource_lock if resource_lock is not None else asyncio.Lock()
        self.container = TaskLinuxContainer(self.task_id, self.owner_id, self.scope,
            self.binary, self.environment, profile="public-retrieval-v1")

    async def _execute(self, argv, **kwargs):
        # Tool handles share one task namespace and one in-process lease. The
        # cgroup is also common across restarts, so limits are not multiplied by
        # the number of selected paper/discovery tools.
        async with self._resource_lock:
            return await super()._execute(argv, **kwargs)

    async def _spawn(self, argv):
        async def start():
            if await asyncio.to_thread(self.container.process_ids):
                raise OpenResearchError("RETRIEVAL_BUSY", "Original task retrieval is still active; no replay allowed")
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
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    def create_retrieval_adapter(self, *, environment, **kwargs):
        key = str(kwargs["scope"].resolve())
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return LinuxRetrievalAdapter(binary=self.binary, environment=environment,
                                     enabled=True, resource_lock=lock, **kwargs)
