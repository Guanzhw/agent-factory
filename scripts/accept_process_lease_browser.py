"""Actual native process lease UI against an isolated local PostgreSQL fixture.

No browser route mocks: create one governed native task, read its real bounded
process receipt after normal release. A second native task has a controlled
failed Popen before any child, leaving genuine durable UNKNOWN custody.
This validates a controlled cooperative process, not production host capacity.
"""
import argparse
import json
from pathlib import Path
import socket
import threading
from unittest.mock import patch

import httpx
from playwright.sync_api import sync_playwright  # type: ignore[reportMissingImports]
import uvicorn

from test_process_runtime_postgres import ProcessRuntimePostgresTests  # type: ignore[reportMissingImports]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "evidence.json").exists():
        raise ValueError("Use a new evidence output directory")
    fixture = ProcessRuntimePostgresTests()
    fixture.setUp()
    server = None
    thread = None
    client = None
    listener = None
    try:
        fixture.start(start_client=False)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        origin = "http://127.0.0.1:" + str(listener.getsockname()[1])
        server = uvicorn.Server(uvicorn.Config(fixture.app, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        fixture.until(lambda: server.started)
        client = httpx.Client(base_url=origin, timeout=20)
        fixture.client = client
        task, plan = fixture.submit()
        lease = fixture.until(lambda: fixture.lease(task))
        stopped = fixture.until(lambda: fixture.process_state(lease))
        assert stopped["allStopped"] is True
        def released_projection():
            values = fixture.request("GET", "/resources/leases")["leases"]
            row = next((value for value in values if value["id"] == lease["id"]), None)
            return row if row and row["state"] == "RECLAIMED" else None
        projected = fixture.until(released_projection)
        assert projected["stopEvidence"]["allStopped"] is True and projected["capacityHeld"] is False
        assert projected["executionStatus"] == "COMPLETED" and projected["exitCode"] == 0
        fixture.until(lambda: fixture.request("GET", "/jobs/" + task["id"])["job"]["status"] == "completed")
        assert projected["processBinding"]["taskId"] == task["id"]
        assert projected["processBinding"]["planId"] == plan["id"]
        assert projected["providerJobId"] == stopped["providerJobId"]
        allocations = len(fixture.store.sql("SELECT id FROM af_process_allocations"))
        assert allocations == 1
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            assert context.request.post(origin + "/api/factory/demo/login", data={"persona": "alice"}).ok
            page = context.new_page()
            errors, mutations = [], []
            page.on("pageerror", lambda error: errors.append(type(error).__name__))
            page.on("request", lambda request: mutations.append(request.method)
                    if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
            page.goto(origin)
            page.get_by_role("button", name="我的资源连接", exact=True).click()
            card = page.locator('[data-process-lease-id="' + lease["id"] + '"]')
            card.get_by_text("租约预约容量已释放。", exact=False).wait_for()
            assert stopped["providerJobId"] in card.inner_text()
            assert "服务端已记录原进程组停止证据" in card.inner_text()
            assert "不是进程组总量配额" in card.inner_text()
            page.screenshot(path=str(args.output / "desktop-released.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            card.get_by_text("租约与进程绑定依据", exact=True).click()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(args.output / "mobile-released.png"), full_page=True)
            assert "租约释放不代表进程成功" in card.inner_text()
            page.screenshot(path=str(args.output / "mobile-released.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            # Real native second task, controlled failed Popen before any child.
            # Its durable UNKNOWN custody must remain held, never auto-replayed.
            with patch("agent_factory.process_enforcement.subprocess.Popen", side_effect=OSError("Synthetic failed launch")) as spawn:
                unknown_task, _ = fixture.submit()
                unknown_lease = fixture.until(lambda: fixture.lease(unknown_task))
                fixture.until(lambda: spawn.call_count == 1)
                def unknown_projection():
                    values = fixture.request("GET", "/resources/leases")["leases"]
                    row = next((value for value in values if value["id"] == unknown_lease["id"]), None)
                    return row if row and row["state"] == "UNKNOWN" else None
                unknown = fixture.until(unknown_projection)
                assert unknown["capacityHeld"] is True
                spawn.assert_called_once()
            page.get_by_role("button", name="刷新资源", exact=True).click()
            unknown_card = page.locator('[data-process-lease-id="' + unknown_lease["id"] + '"]')
            unknown_card.get_by_text("UNKNOWN · 执行状态待核对", exact=True).wait_for()
            assert "预约容量仍保留" in unknown_card.inner_text()
            assert "进程停止证据尚未确认" in unknown_card.inner_text()
            assert "租约预约容量已释放" not in unknown_card.inner_text()
            page.screenshot(path=str(args.output / "mobile-unknown-held.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(path=str(args.output / "desktop-unknown-held.png"), full_page=True)
            bob = browser.new_context()
            assert bob.request.post(origin + "/api/factory/demo/login", data={"persona": "bob"}).ok
            bob_page = bob.new_page()
            bob_page.goto(origin)
            bob_page.get_by_role("button", name="我的资源连接", exact=True).click()
            bob_page.get_by_text("当前页没有可见执行租约。", exact=True).wait_for()
            assert bob_page.locator("[data-process-lease-id]").count() == 0
            bob.close()
            assert errors == [] and mutations == []
            assert len(fixture.store.sql("SELECT id FROM af_process_allocations")) == allocations + 1
            context.close()
            browser.close()
        evidence = {"schema": 1, "evidenceKind": "actual-native-cooperative-process-controlled-fixture",
            "taskId": task["id"], "planId": plan["id"], "leaseId": lease["id"],
            "nativeRunId": projected["nativeRunId"], "providerJobId": projected["providerJobId"],
            "actualNativeTask": True, "nativeTaskCompleted": True, "actualBoundedProcess": True,
            "normalLifecycleReleased": True, "stoppedHeldBrowserScenario": False,
            "browserMutationRequests": 0, "pageErrors": 0, "mobileHorizontalOverflow": False,
            "bobCannotSeeAliceLease": True, "allocationCount": allocations + 1, "browserTriggeredAllocations": 0,
            "unknownLeaseId": unknown_lease["id"], "unknownHeld": True, "unknownCase": "controlled-Popen-failure-no-child",
            "aggregateQuotaValidated": False, "hostileCodeSandboxValidated": False, "productionCapacityValidated": False}
        (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps({"ok": True, "output": str(args.output)}))
    finally:
        if client:
            client.close()
        if server:
            server.should_exit = True
        if thread:
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("Fixture server did not stop")
        if listener:
            listener.close()
        fixture.doCleanups()


if __name__ == "__main__":
    main()
