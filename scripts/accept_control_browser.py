"""Owned Chromium restarts over the real demo TCP service; no paid providers.

Run with platform/tests on PYTHONPATH, isolated FACTORY_TEST_DATABASE_URL and
an installed Playwright Chromium after npm run build. Evidence contains only
synthetic task references and receipt states, never session cookies.
"""
import argparse
import json
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright

from test_control_commands_process import CommandProcessTests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixture = CommandProcessTests()
    fixture.setUp()
    evidence = []
    try:
        with tempfile.TemporaryDirectory() as profile, sync_playwright() as playwright:
            for action, approved in (("answer", None), ("approve", False), ("approve", True), ("cancel", None)):
                task, _ = fixture.waiting("answer" if action == "cancel" else action)
                context = playwright.chromium.launch_persistent_context(profile, headless=True)
                origin = str(fixture.client.base_url)
                context.request.post(origin + "/api/factory/demo/login", data={"persona": "alice"})
                page = context.new_page()
                page.goto(origin)
                page.locator(".task-list .task-row").first.click()
                posts = []
                completed = []
                def lose(route):
                    if route.request.method != "POST":
                        route.continue_()
                        return
                    posts.append(route.request.post_data_json)
                    response = route.fetch()
                    assert response.ok, response.text()
                    route.abort("failed")
                    completed.append(True)
                page.route("**/api/factory/jobs/*/commands", lose)
                # Prevent current-page recovery: only a new browser process may
                # obtain the committed decision receipt after this response loss.
                page.route("**/api/factory/jobs/*/commands/*", lambda route: route.abort("failed"))
                page.route("**/api/factory/commands?*", lambda route: route.abort("failed"))
                if action == "answer":
                    page.locator("#job-answer").fill("Synthetic browser-private answer")
                    page.get_by_role("button", name="提交回答", exact=True).click()
                else:
                    page.get_by_role("button", name="请求取消" if action == "cancel" else "同意本次请求" if approved else "拒绝", exact=True).click()
                for _ in range(300):
                    if completed:
                        break
                    page.wait_for_timeout(100)
                assert completed, "Actual control response was not discarded"
                assert len(posts) == 1
                command = posts[0]
                saved = page.evaluate("JSON.stringify(localStorage)")
                assert command["commandId"] in saved
                assert "Synthetic browser-private answer" not in saved and "Authorization" not in saved
                context.close()  # Terminates Chromium, not just a page/reload.
                context = playwright.chromium.launch_persistent_context(profile, headless=True)
                # Session cookies need not survive browser shutdown: authenticate
                # again while the durable command pointer remains in localStorage.
                context.request.post(origin + "/api/factory/demo/login", data={"persona": "alice"})
                page = context.new_page()
                recovery_posts = []
                page.on("request", lambda request: recovery_posts.append(request.url) if request.method == "POST" and "/commands" in request.url else None)
                page.goto(origin)
                row = page.locator('[data-command-id="' + command["commandId"] + '"]')
                row.wait_for()
                receipt = fixture.api("GET", f'/jobs/{task}/commands/{command["commandId"]}')
                assert receipt["decisionRecorded"], receipt
                assert not recovery_posts
                page.get_by_role("button", name="退出", exact=True).click()
                page.get_by_role("button", name="研究员 Bob", exact=True).click()
                page.get_by_role("heading", name="研究工作台", exact=True).wait_for()
                assert page.locator('[data-command-id="' + command["commandId"] + '"]').count() == 0
                page.get_by_role("button", name="退出", exact=True).click()
                page.get_by_role("button", name="研究员 Alice", exact=True).click()
                row.wait_for()
                assert not recovery_posts
                page.screenshot(path=str(args.output / (action + str(approved) + ".png")), full_page=True)
                evidence.append({"action": action, "approved": approved, "commandId": command["commandId"], "taskId": task,
                    "receiptState": receipt["state"], "browserRestart": True, "identitySwitch": True,
                    "controlPOSTs": len(posts), "recoveryPOSTs": len(recovery_posts), "answerStored": False})
                context.close()
                fixture.api("POST", "/jobs/" + task + "/cancel")
        (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps({"ok": True, "cases": len(evidence), "output": str(args.output)}))
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
