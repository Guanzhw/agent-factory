"""Fresh ORX authority after semaphore admission; no subprocess or provider I/O."""
import asyncio
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from agent_factory.openresearch import BinaryPin, OpenResearchAdapter, OpenResearchError, REVISION, VERSION


class WaitingSemaphore(asyncio.Semaphore):
    def __init__(self):
        super().__init__(1)
        self.entered = asyncio.Event()

    async def __aenter__(self):
        self.entered.set()
        return await super().__aenter__()


class CompletedProcess:
    def __init__(self, output):
        self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
        self.stdout.feed_data(output)
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        self.returncode = 0

    async def wait(self):
        return self.returncode


class OrxCommandAuthorityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.binary = root / "synthetic-orx"
        content = b"Synthetic fixture bytes; this file is never executed"
        self.binary.write_bytes(content)
        self.trace = []
        self.denied = False

        def authorize(operation):
            self.trace.append(("authorize", operation))
            return not self.denied

        self.adapter = OpenResearchAdapter(binary=self.binary, scope=root / "scope",
            owner_id="synthetic-owner", task_id=str(uuid4()), authorize=authorize,
            pin=BinaryPin(REVISION, VERSION, hashlib.sha256(content).hexdigest()), enabled=True)
        self.semaphore = WaitingSemaphore()
        self.adapter._semaphore = self.semaphore

        async def spawn(argv):
            self.trace.append(("spawn", argv))
            return CompletedProcess(f"orx {VERSION}".encode() if "--version" in argv else b"synthetic result")

        self.spawn = AsyncMock(side_effect=spawn)
        self.adapter._spawn = self.spawn

    async def prime(self):
        await self.adapter.preflight()
        self.trace.clear()
        self.spawn.reset_mock()
        self.semaphore.entered.clear()

    async def test_each_command_keeps_fresh_preflight_and_one_operation_check_per_spawn(self):
        await self.prime()
        with patch.object(self.adapter, "_verify_hash", wraps=self.adapter._verify_hash) as verify:
            for _ in range(2):
                result = await self.adapter._command("discover", "discover", "synthetic")
                self.assertEqual(result.stdout, "synthetic result")
        expected = [("authorize", "preflight"), ("authorize", "discover"),
                    ("spawn", ("--no-telemetry", "discover", "synthetic"))]
        self.assertEqual(self.trace, expected * 2)
        self.assertEqual(verify.call_count, 6)  # preflight plus before/after semaphore for each command
        self.assertEqual(self.spawn.await_count, 2)

    async def test_revocation_while_waiting_for_semaphore_prevents_spawn(self):
        await self.prime()
        await self.semaphore.acquire()
        task = asyncio.create_task(self.adapter._command("discover", "discover", "synthetic"))
        try:
            await asyncio.wait_for(self.semaphore.entered.wait(), 1)
            self.assertFalse(task.done())
            self.assertEqual(self.trace, [("authorize", "preflight")])
            self.denied = True
        finally:
            self.semaphore.release()
        with self.assertRaises(OpenResearchError) as caught:
            await task
        self.assertEqual(caught.exception.code, "FORBIDDEN")
        self.assertEqual(self.trace, [("authorize", "preflight"), ("authorize", "discover")])
        self.spawn.assert_not_awaited()

    async def test_binary_replacement_while_waiting_for_semaphore_prevents_spawn(self):
        await self.prime()
        await self.semaphore.acquire()
        task = asyncio.create_task(self.adapter._command("discover", "discover", "synthetic"))
        try:
            await asyncio.wait_for(self.semaphore.entered.wait(), 1)
            self.binary.write_bytes(b"Unapproved synthetic replacement")
        finally:
            self.semaphore.release()
        with self.assertRaises(OpenResearchError) as caught:
            await task
        self.assertEqual(caught.exception.code, "UNVERIFIED_BINARY")
        self.spawn.assert_not_awaited()

    async def test_cancelled_semaphore_wait_never_spawns(self):
        await self.prime()
        await self.semaphore.acquire()
        task = asyncio.create_task(self.adapter._command("discover", "discover", "synthetic"))
        try:
            await asyncio.wait_for(self.semaphore.entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            self.semaphore.release()
        self.spawn.assert_not_awaited()
        self.assertEqual(self.trace, [("authorize", "preflight")])
