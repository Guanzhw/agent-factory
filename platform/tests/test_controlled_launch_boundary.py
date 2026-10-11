"""The fixture cannot substitute queued/unknown work for a real crash boundary."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from controlled_remote_process_worker import DropControlAcknowledgement, LaunchBoundaryExit


GUARDIAN = {"pid": 123, "start": "456", "group": 123, "state": "S",
    "bootId": "00000000-0000-0000-0000-000000000001"}
ORIGINAL = {"id": "synthetic-process", "taskId": "synthetic-task", "bootId": GUARDIAN["bootId"]}


def retained_process():
    return SimpleNamespace(pid=123, poll=lambda: None)


class LaunchBoundaryTests(unittest.TestCase):
    def test_accepted_dispatch_and_actual_same_task_launch_in_either_order_exit_once(self):
        for launch_first in (True, False):
            with self.subTest(launch_first=launch_first), TemporaryDirectory() as directory:
                marker = Path(directory) / "fault.json"
                boundary = LaunchBoundaryExit(marker)
                boundary.arm()
                with patch("controlled_remote_process_worker.birth", return_value=GUARDIAN), \
                     patch("controlled_remote_process_worker.os._exit") as exit_process:
                    actions = [lambda: boundary.launched(ORIGINAL, retained_process()),
                        lambda: boundary.accepted(ORIGINAL["taskId"])]
                    if not launch_first:
                        actions.reverse()
                    actions[0]()
                    exit_process.assert_not_called()
                    self.assertFalse(marker.exists())
                    actions[1]()
                    boundary.launched(ORIGINAL, retained_process())
                    exit_process.assert_called_once_with(41)
                proof = json.loads(marker.read_text())
                self.assertEqual(proof["phase"], "after-process-launch-before-http-ack")
                self.assertEqual(proof["taskId"], ORIGINAL["taskId"])
                self.assertEqual(proof["processId"], ORIGINAL["id"])
                self.assertEqual(proof["guardian"], GUARDIAN)

    def test_queued_unpinned_unrelated_or_disarmed_launch_cannot_trigger_exit(self):
        with TemporaryDirectory() as directory:
            marker = Path(directory) / "fault.json"
            boundary = LaunchBoundaryExit(marker)
            boundary.arm()
            boundary.accepted(ORIGINAL["taskId"])
            with patch("controlled_remote_process_worker.os._exit") as exit_process:
                boundary.launched(ORIGINAL, None)
                with patch("controlled_remote_process_worker.birth", return_value=None):
                    boundary.launched(ORIGINAL, retained_process())
                with patch("controlled_remote_process_worker.birth", return_value=GUARDIAN):
                    boundary.launched({**ORIGINAL, "taskId": "different-task"}, retained_process())
                    boundary.launched(ORIGINAL, SimpleNamespace(pid=123, poll=lambda: 125))
                for bad in ({**GUARDIAN, "bootId": "00000000-0000-0000-0000-000000000002"},
                            {**GUARDIAN, "group": 999}, {**GUARDIAN, "state": "Z"}):
                    with patch("controlled_remote_process_worker.birth", return_value=bad):
                        boundary.launched(ORIGINAL, retained_process())
                with patch("controlled_remote_process_worker.birth", return_value=GUARDIAN):
                    boundary.disarm()
                    boundary.launched(ORIGINAL, retained_process())
                exit_process.assert_not_called()
            self.assertFalse(marker.exists())


class LaunchAcknowledgementTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, status):
        messages = []
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": status, "headers": []})
            await send({"type": "http.response.body", "body": b'{"remoteTaskId":"synthetic-task"}'})
        async def send(message):
            if message.get("status") == 503:
                self.assertFalse(boundary.pending, "Late launch cannot exit after a fault-failure response starts")
            messages.append(message)
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        with TemporaryDirectory() as directory:
            boundary = LaunchBoundaryExit(Path(directory) / "fault.json")
            wrapped = DropControlAcknowledgement(app, {"fault": "exit_after_dispatch"}, Mock(), boundary.marker, boundary)
            scope = {"type": "http", "method": "POST", "path": "/api/factory/remote-handoffs/original/dispatch"}
            async def timeout(awaitable, *, timeout):
                awaitable.close()
                raise TimeoutError
            with patch("controlled_remote_process_worker.asyncio.wait_for", side_effect=timeout), \
                 patch("controlled_remote_process_worker.os._exit") as exit_process:
                await wrapped(scope, receive, send)
                exit_process.assert_not_called()
            self.assertFalse(boundary.pending)
            self.assertFalse(boundary.marker.exists())
        return messages

    async def test_missing_launch_reports_fault_failure_without_forwarding_success_ack(self):
        messages = await self.exercise(202)
        self.assertEqual([m["status"] for m in messages if m["type"] == "http.response.start"], [503])
        body = b"".join(m.get("body", b"") for m in messages)
        self.assertIn(b"CONTROLLED_CRASH_BOUNDARY_NOT_REACHED", body)

    async def test_rejected_dispatch_keeps_rejection_without_exit_or_fault_marker(self):
        messages = await self.exercise(409)
        self.assertEqual([m["status"] for m in messages if m["type"] == "http.response.start"], [409])
