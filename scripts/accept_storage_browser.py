"""Chromium owner-scoped retention against the actual loopback service.

Only a new generated database and an explicitly rebuildable scratch directory
are used. No real historical directory, runtime container or artifact is deleted.
"""
import argparse
import json
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright

from test_control_commands_process import CommandProcessTests
from test_storage_process import owned_directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixture = CommandProcessTests()
    fixture.setUp()
    try:
        task, _ = fixture.waiting("answer")
        path = owned_directory(fixture, task)
        fixture.api("POST", "/jobs/" + task + "/cancel")
        with tempfile.TemporaryDirectory() as profile, sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(profile, headless=True)
            origin = str(fixture.client.base_url)
            context.request.post(origin + "/api/factory/demo/login", data={"persona": "alice"})
            page = context.new_page()
            page.goto(origin)
            page.get_by_role("button", name="磁盘与回收", exact=True).click()
            page.get_by_role("button", name="生成回收 dry-run", exact=True).click()
            page.get_by_text("计划已记录，尚未移动", exact=True).wait_for()
            assert (path / "synthetic.txt").exists()
            plans = fixture.api("GET", "/storage")["plans"]
            assert len(plans) == 1
            plan = plans[0]
            page.get_by_role("button", name="确认隔离", exact=True).click()
            page.get_by_text("已隔离，可恢复", exact=True).first.wait_for()
            assert not path.exists()
            context.close()
            context = playwright.chromium.launch_persistent_context(profile, headless=True)
            context.request.post(origin + "/api/factory/demo/login", data={"persona": "alice"})
            page = context.new_page()
            posts = []
            page.on("request", lambda request: posts.append(request.url) if request.method == "POST" and "/storage/" in request.url else None)
            page.goto(origin)
            page.get_by_role("button", name="磁盘与回收", exact=True).click()
            page.locator('[data-retention-id="' + plan["id"] + '"]').wait_for()
            assert not posts, "Browser recovery must never automatically move or delete"
            page.get_by_role("button", name="恢复原目录", exact=True).click()
            page.get_by_text("已恢复原目录", exact=True).first.wait_for()
            assert (path / "synthetic.txt").read_bytes() == b"Owned recoverable storage fixture"
            assert len(posts) == 1
            page.screenshot(path=str(args.output / "alice-restored.png"), full_page=True)
            page.get_by_role("button", name="退出", exact=True).click()
            page.get_by_role("button", name="研究员 Bob", exact=True).click()
            page.get_by_role("button", name="磁盘与回收", exact=True).click()
            page.get_by_text("尚无平台登记的任务目录。历史目录不会被自动接管。", exact=True).wait_for()
            assert page.locator('[data-retention-id="' + plan["id"] + '"]').count() == 0
            page.screenshot(path=str(args.output / "bob-scoped.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            context.close()
            evidence = {"taskId": task, "planId": plan["id"], "dryRunDidNotMove": True, "quarantineDidNotDelete": True,
                "browserRestartRecoveredOriginal": True, "recoveryMutationPOSTs": 0, "explicitRestorePOSTs": len(posts),
                "restoredBytesMatch": True, "bobCannotSeeAlicePlan": True, "mobileOverflow": False}
            (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
            print(json.dumps({"ok": True, "output": str(args.output)}))
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
