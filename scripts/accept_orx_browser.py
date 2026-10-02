"""Task-owned Edge acceptance against a real configured Factory service.

The input contains generated fixture auth only and is never copied to evidence.
This harness does not create model providers or configure production access.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    origin = fixture["baseUrl"]
    url = urlparse(origin)
    assert url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"}
    args.output.mkdir(parents=True, exist_ok=True)
    evidence = {"browser": "installed Playwright + Microsoft Edge", "application": fixture.get("applicationId", "orx-local-toy"), "modelCalls": "No paid provider configured", "phases": []}
    requests = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel="msedge", headless=True)
        owner = await browser.new_context(extra_http_headers=fixture["ownerHeaders"], accept_downloads=True, viewport={"width": 1440, "height": 1050})
        reviewer = await browser.new_context(extra_http_headers=fixture["reviewerHeaders"], viewport={"width": 1360, "height": 900})
        page = await owner.new_page()
        manager = await reviewer.new_page()
        page.set_default_timeout(20000)
        manager.set_default_timeout(20000)
        def observed(request):
            if request.method == "POST" and "/api/factory/" in request.url:
                body = request.post_data_json or {}
                requests.append({"path": urlparse(request.url).path, "requestId": body.get("requestId"), "planId": body.get("planId"), "approved": body.get("approved")})
        page.on("request", observed)
        await page.goto(origin)
        await page.get_by_role("heading", name="研究工作台", exact=True).wait_for()
        await manager.goto(origin)
        await manager.get_by_role("button", name="方案审查", exact=True).click()

        async def api(path):
            return await page.evaluate("async path => { const r = await fetch('/api/factory'+path); if (!r.ok) throw Error('Owned fixture read failed '+r.status); return r.json(); }", path)

        async def build(mode, goal, lose_ack=False):
            again = page.get_by_role("button", name="开始新的装配", exact=True)
            if await again.count():
                await again.click()
            await page.locator("#application-selector").select_option(evidence["application"])
            await page.get_by_role("combobox", name="应用执行方式", exact=True).select_option(mode)
            for name, ref in fixture.get("connectionRefs", {}).items():
                await page.get_by_role("combobox", name="资源连接 " + name, exact=True).select_option(ref)
            await page.locator("#research-topic").fill(goal)
            before = len(requests)
            await page.get_by_role("button", name="生成装配提案", exact=True).dblclick()
            await page.get_by_role("button", name="接受提案并固定方案", exact=True).wait_for()
            await page.get_by_role("button", name="接受提案并固定方案", exact=True).dblclick()
            await page.get_by_role("heading", name="已固定的执行方案", exact=True).wait_for()
            await page.get_by_role("button", name="提交方案审查", exact=True).dblclick()
            row = manager.locator("article.review-row").filter(has=manager.get_by_role("heading", name=goal, exact=True))
            await row.wait_for()
            await row.get_by_role("heading", name="固定令牌与金额承诺", exact=True).wait_for()
            await row.get_by_role("button", name="同意方案", exact=True).dblclick()
            await page.wait_for_function("() => [...document.querySelectorAll('button')].some(b => b.textContent === '确认方案并创建任务' && !b.disabled)")
            if lose_ack:
                async def lose_once(route):
                    if route.request.method != "POST":
                        await route.continue_(); return
                    response = await route.fetch()
                    assert response.ok
                    await page.unroute("**/api/factory/instances", lose_once)
                    await route.fulfill(status=503, content_type="application/json", body=json.dumps({"code": "CONTROLLED_ACK_LOST", "message": "Controlled admission acknowledgement lost"}))
                await page.route("**/api/factory/instances", lose_once)
            await page.get_by_role("button", name="确认方案并创建任务", exact=True).dblclick()
            await page.get_by_role("heading", name="等待执行审批", exact=True).wait_for(timeout=90000)
            await page.wait_for_function("() => [...document.querySelectorAll('button')].some(b => b.textContent === '同意本次请求' && !b.disabled)", timeout=90000)
            jobs = await api("/jobs")
            matches = [j for j in jobs if j["input"]["topic"] == goal]
            assert len(matches) == 1, "Repeated submission created another Factory task"
            job = matches[0]
            detail = await api("/jobs/" + job["id"])
            experiment = detail["orxExperiment"]
            assert experiment["taskId"] == job["id"] and experiment["orxRunId"] is None and experiment["status"] == "NOT_STARTED"
            assert experiment["projectId"] and experiment["experimentId"]
            assert experiment["provenance"]["upstreamSourceCommit"] == "f336b121525d99364e2dee4fe90b2784894a54e6"
            await page.screenshot(path=str(args.output / (mode + "-before-native-approval.png")), full_page=True)
            mutations = requests[before:]
            assert len([r for r in mutations if r["path"] == "/api/factory/instances"]) == 1
            return job, detail

        async def terminal(job_id, state):
            await page.wait_for_function("async args => { const d = await (await fetch('/api/factory/jobs/'+args[0])).json(); return d.job.status === args[1] && d.orxExperiment && ['done','failed','cancelled'].includes(d.orxExperiment.status); }", arg=[job_id, state], timeout=90000)
            return await api("/jobs/" + job_id)

        try:
            goal = "Actual ORX browser owned success"
            job, before = await build("success", goal, lose_ack=True)
            approve_before = len([r for r in requests if r["path"].endswith("/approve")])
            await page.get_by_role("button", name="同意本次请求", exact=True).dblclick()
            result = await terminal(job["id"], "completed")
            assert result["orxExperiment"]["status"] == "done" and result["orxExperiment"]["evaluation"]["zeroModelCalls"] is True
            assert result["orxExperiment"]["evaluation"]["baseline"]["value"] == 16 and result["orxExperiment"]["evaluation"]["candidate"]["value"] == 0
            assert len([r for r in requests if r["path"].endswith("/approve")]) == approve_before + 1
            await page.get_by_text("基线 MSE（toy）", exact=True).wait_for()
            assert await page.get_by_role("alert").count() == 0
            downloads = []
            for artifact in result["artifacts"]:
                async with page.expect_download() as download_info:
                    await page.get_by_role("button", name="校验并下载 " + artifact["name"], exact=True).click()
                download = await download_info.value
                target = args.output / ("download-" + artifact["id"] + ".bin")
                await download.save_as(target)
                raw = target.read_bytes()
                actual = hashlib.sha256(raw).hexdigest()
                assert len(raw) == artifact["size"] and actual == artifact["sha256"]
                downloads.append({"artifactId": artifact["id"], "name": artifact["name"], "bytes": len(raw), "sha256": actual, "verified": True})
            assert downloads
            await page.screenshot(path=str(args.output / "success-desktop.png"), full_page=True)
            evidence["phases"].append({"name": "actual_binary_success", "taskId": job["id"], "planId": job["planId"], "beforeApproval": before["orxExperiment"], "experiment": result["orxExperiment"], "ledger": result["usageLedger"], "downloads": downloads, "nativeAdmissions": len([e for e in result["events"] if e["type"] == "native_accepted"]), "lostAdmissionAckRecoveredWithoutDuplicatePOST": True})

            # Tamper a read in the browser transport; retain server bytes/metadata.
            first_artifact = result["artifacts"][0]
            artifact_pattern = "**/api/factory/jobs/" + job["id"] + "/artifacts/" + first_artifact["id"]
            async def corrupt_read(route):
                response = await route.fetch()
                raw = bytearray(await response.body())
                assert raw
                raw[0] ^= 1
                await route.fulfill(response=response, body=bytes(raw))
            await page.route(artifact_pattern, corrupt_read)
            await page.get_by_role("button", name="校验并下载 " + first_artifact["name"], exact=True).click()
            await page.get_by_role("alert").filter(has_text="SHA-256 不匹配").wait_for()
            await page.unroute(artifact_pattern, corrupt_read)
            evidence["phases"].append({"name": "tampered_download_rejected", "artifactId": first_artifact["id"], "serverArtifactUnchanged": True})

            await page.reload()
            await page.locator(".task-list .task-row").filter(has_text=goal).click()
            restored = await api("/jobs/" + job["id"])
            assert restored["orxExperiment"]["orxRunId"] == result["orxExperiment"]["orxRunId"]
            assert len([e for e in restored["events"] if e["type"] == "native_accepted"]) == 1
            evidence["phases"].append({"name": "reload_preserves_original_native_run", "taskId": job["id"], "orxRunId": restored["orxExperiment"]["orxRunId"], "nativeAdmissions": 1})

            job, _ = await build("evaluator_failure", "Actual ORX browser owned evaluator failure")
            await page.get_by_role("button", name="同意本次请求", exact=True).click()
            failed = await terminal(job["id"], "failed")
            assert failed["orxExperiment"]["evaluation"]["failureCode"] == "REVIEWED_EVALUATOR_FAILURE"
            await page.get_by_text("已审阅评估器报告失败：", exact=False).wait_for()
            await page.screenshot(path=str(args.output / "evaluator-failure.png"), full_page=True)
            evidence["phases"].append({"name": "actual_evaluator_failure_preserved", "taskId": job["id"], "experiment": failed["orxExperiment"], "artifacts": [{"id": a["id"], "sha256": a["sha256"]} for a in failed["artifacts"]]})

            job, _ = await build("cancellable", "Actual ORX browser owned running cancellation")
            await page.get_by_role("button", name="同意本次请求", exact=True).click()
            await page.wait_for_function("async id => { const d=await(await fetch('/api/factory/jobs/'+id)).json(); return d.orxExperiment && d.orxExperiment.status==='running' && !!d.orxExperiment.orxRunId; }", arg=job["id"], timeout=90000)
            running = await api("/jobs/" + job["id"])
            await page.get_by_text("真实本地实验运行中", exact=True).wait_for()
            await page.screenshot(path=str(args.output / "actual-running-progress.png"), full_page=True)
            await page.get_by_role("button", name="请求取消", exact=True).dblclick()
            stopped = await terminal(job["id"], "canceled")
            await page.wait_for_function("async id => { const d=await(await fetch('/api/factory/jobs/'+id)).json(); return d.orxExperiment.stopEvidence && d.orxExperiment.stopEvidence.allStopped===true; }", arg=job["id"], timeout=90000)
            stopped = await api("/jobs/" + job["id"])
            assert stopped["orxExperiment"]["orxRunId"] == running["orxExperiment"]["orxRunId"]
            await page.get_by_text("服务端已记录实验及 detached supervisor 全部停止的正向证据。", exact=True).wait_for()
            await page.screenshot(path=str(args.output / "positive-stop-proof.png"), full_page=True)
            evidence["phases"].append({"name": "actual_running_cancel_positive_stop", "taskId": job["id"], "running": running["orxExperiment"], "stopped": stopped["orxExperiment"], "ledger": stopped["usageLedger"]})

            # Current detail read can fail and recover; never mutate launch.
            detail_pattern = "**/api/factory/jobs/" + job["id"]
            async def offline_read(route):
                if route.request.method == "GET": await route.abort("failed")
                else: await route.continue_()
            await page.route(detail_pattern, offline_read)
            await page.get_by_role("button", name="刷新", exact=True).click()
            await page.get_by_role("alert").filter(has_text="记录更新失败").wait_for()
            await page.unroute(detail_pattern, offline_read)
            await page.get_by_role("button", name="重新连接", exact=True).click()
            await page.wait_for_function("() => ![...document.querySelectorAll('[role=alert]')].some(x=>x.textContent.includes('记录更新失败'))")
            recovered = await api("/jobs/" + job["id"])
            assert recovered["orxExperiment"]["orxRunId"] == stopped["orxExperiment"]["orxRunId"]
            evidence["phases"].append({"name": "detail_read_error_explicit_recovery", "originalOrxRunId": recovered["orxExperiment"]["orxRunId"], "noNewLaunch": True})

            await page.set_viewport_size({"width": 390, "height": 844})
            await page.screenshot(path=str(args.output / "actual-orx-mobile.png"), full_page=True)
            width = await page.evaluate("() => ({viewport:innerWidth,document:document.documentElement.scrollWidth})")
            assert width["document"] <= width["viewport"], "Mobile page overflow"
            evidence["phases"].append({"name": "mobile_actual_evidence", **width})
            evidence["mutationReceipts"] = requests
        finally:
            await owner.close()
            await reviewer.close()
            await browser.close()
    target = args.output / "actual-orx-browser-evidence.json"
    target.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "phases": len(evidence["phases"]), "evidence": str(target)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
