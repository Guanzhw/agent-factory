"""Actual origin UI over two separate loopback Factory/PG services.

Uses only generated fixture identities, one governed receiver process per pair,
and independent normal/UNKNOWN workloads. No route interception or mocked lease
JSON. This is controlled same-host HTTP evidence, not inter-host/TLS acceptance.
"""
import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright  # type: ignore[reportMissingImports]

from controlled_remote_worker import ORIGIN_OWNER, OTHER_OWNER, RECEIVER_OWNER, token  # type: ignore[reportMissingImports]
from test_remote_process_runtime_postgres import RemoteProcessRuntimePair, RemoteProcessRuntimePostgresTests  # type: ignore[reportMissingImports]


def scenario(playwright, database_url, output, workload):
    pair = RemoteProcessRuntimePair(database_url, workload=workload).start()
    browser = None
    try:
        fixture = RemoteProcessRuntimePostgresTests()
        fixture.pair, fixture.origin, fixture.receiver = pair, pair.origin, pair.receiver
        plan, task, _, receipt = fixture.execute()
        expected = "RECLAIMED" if workload == "normal" else "UNKNOWN"
        lease = fixture.wait_lease(receipt["remoteTaskId"], {expected})
        fixture.assert_single(task, receipt)

        def projected():
            detail = fixture.detail(task)
            value = detail["snapshot"]["remoteHandoff"].get("processLeases")
            if not value or value.get("complete") is not True or len(value.get("leases", [])) != 1:
                return None
            actual = value["leases"][0]
            return detail if actual["id"] == lease["id"] and actual["state"] == expected else None

        detail = fixture.until(projected)
        receiver_lease = detail["snapshot"]["remoteHandoff"]["processLeases"]["leases"][0]
        if workload == "normal":
            fixture.until(lambda: fixture.detail(task)["job"]["status"] == "completed")
            assert receiver_lease["executionStatus"] == "COMPLETED" and receiver_lease["exitCode"] == 0
            assert receiver_lease["capacityHeld"] is False and receiver_lease["stopEvidence"]["allStopped"] is True
        else:
            assert receiver_lease["capacityHeld"] is True
            assert not (receiver_lease.get("stopEvidence") or {}).get("allStopped")
        before = pair.receiver.facts(receipt["remoteTaskId"])
        browser = playwright.chromium.launch(headless=True)
        # Temporary generated fixture JWT only; never output credentials.
        context = browser.new_context(viewport={"width": 1440, "height": 1000},
            extra_http_headers={"Authorization": "Bearer " + token(pair.origin.configuration["jwtKey"], ORIGIN_OWNER)})
        page = context.new_page()
        errors, writes = [], []
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.on("request", lambda request: writes.append(request.method)
                if request.method not in {"GET", "HEAD", "OPTIONS"} else None)
        page.goto(pair.origin.url)
        page.locator("button.task-row").first.click()
        panel = page.locator('section[aria-label="接收端进程证据"]')
        panel.get_by_role("heading", name="接收端进程租约", exact=True).wait_for()
        card = panel.locator('[data-remote-process-lease-id="' + lease["id"] + '"]')
        card.wait_for()
        text = panel.inner_text()
        for value in (RECEIVER_OWNER, receipt["remoteTaskId"], receipt["remoteRunId"], receipt["remotePlanId"],
                      receiver_lease["poolId"], receiver_lease["providerJobId"]):
            assert value in text
        assert task not in text and plan["id"] not in text
        assert "不是当前站点的本地租约" in text
        assert "预约预算不是内核强制总量配额" in text
        assert panel.locator("button").count() == 0
        if workload == "normal":
            assert "租约预约容量已释放" in text and "进程已结束（COMPLETED）" in text
        else:
            assert "UNKNOWN" in text and "预约容量仍保留" in text and "进程停止证据尚未确认" in text
            assert "租约预约容量已释放" not in text
        page.screenshot(path=str(output / (workload + "-desktop.png")), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        panel.get_by_text("租约与进程绑定依据", exact=True).click()
        panel.get_by_text("接收端容量池依据", exact=True).click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / (workload + "-mobile.png")), full_page=True)
        assert errors == [] and writes == []
        unrelated = browser.new_context(extra_http_headers={
            "Authorization": "Bearer " + token(pair.origin.configuration["jwtKey"], OTHER_OWNER)})
        denied = unrelated.request.get(pair.origin.url + "/api/factory/jobs/" + task)
        assert denied.status == 404
        other_page = unrelated.new_page()
        other_page.goto(pair.origin.url)
        other_page.get_by_text("尚无任务。先描述一个研究问题。", exact=True).wait_for()
        assert other_page.locator("[data-remote-process-lease-id]").count() == 0
        unrelated.close()
        context.close()
        browser.close()
        browser = None
        after = pair.receiver.facts(receipt["remoteTaskId"])
        assert after["launchAttemptCount"] == before["launchAttemptCount"] == 1
        assert len(after["processAllocations"]) == len(before["processAllocations"]) == 1
        assert len(after["processMappings"]) == 1 and after["nativeTickets"] == 1
        original = fixture.assert_single(task, receipt)
        assert original["id"] == lease["id"] and original["providerJobId"] == lease["providerJobId"]
        origin_facts = pair.origin.facts(task)
        assert origin_facts["nativeTickets"] == 0 and origin_facts["leases"] == []
        return {"workload": workload, "originTaskId": task, "originPlanId": plan["id"],
            "receiverTaskId": receipt["remoteTaskId"], "receiverRunId": receipt["remoteRunId"],
            "receiverPlanId": receipt["remotePlanId"], "receiverOwnerId": RECEIVER_OWNER,
            "receiverLeaseId": lease["id"], "providerJobId": lease["providerJobId"], "poolId": receiver_lease["poolId"],
            "state": expected, "capacityHeld": receiver_lease["capacityHeld"], "originalReceiverIdentityPreserved": True,
            "browserMutationRequests": 0, "browserTriggeredLaunches": 0, "receiverLaunchAttempts": 1,
            "pageErrors": 0, "mobileHorizontalOverflow": False, "otherOwnerDenied": True,
            "originNativeTickets": 0, "originComputeLeases": 0}
    finally:
        if browser:
            browser.close()
        # Positive owned-process cleanup precedes isolated DB/temp removal.
        pair.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "evidence.json").exists():
        raise ValueError("Use a fresh output directory")
    with sync_playwright() as playwright:
        cases = [scenario(playwright, os.environ["FACTORY_TEST_DATABASE_URL"], args.output, workload)
                 for workload in ("normal", "unknown")]
    evidence = {"schema": 1, "evidenceKind": "actual-origin-browser-separate-services-controlled-process",
        "transport": "same-host-loopback-HTTP", "independentFixturePerWorkload": True, "cases": cases,
        "routeMocks": False, "interHostTLSValidated": False, "aggregateQuotaValidated": False,
        "productionCapacityValidated": False}
    (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"ok": True, "output": str(args.output)}))


if __name__ == "__main__":
    main()
