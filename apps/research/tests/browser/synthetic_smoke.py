"""Real Chromium smoke against the built UI, with every API response synthetic.

Run `npm run build`, then `python apps/research/tests/browser/synthetic_smoke.py`.
Requires Playwright's Python package and Chromium (no install or network fallback).
Fixtures mirror openresearch-workspace and verification-metadata compatibility
tests. This verifies browser rendering/read paths, not real model/ORX execution.
"""

from __future__ import annotations

import argparse
import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import tempfile
from threading import Thread
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[4]
OWNER = {"id": "alice", "name": "Synthetic Alice", "role": "user"}
HASH = "a" * 64
CONNECTION = {
    "ref": "synthetic-binding", "registrationRef": "synthetic-remote",
    "ownerId": OWNER["id"], "kind": "orx", "status": "active", "available": True,
    "taskId": None, "capabilities": ["project:read", "session:read", "session:prompt"],
    "fingerprint": HASH, "revision": "synthetic-r1", "version": 1,
    "allowedActions": ["inspect"], "createdAt": "2026-10-13T00:00:00Z",
    "expiresAt": None, "revokedAt": None,
}
NATIVE = {
    "id": "native-1", "name": "Synthetic native project", "projectIdentityHash": HASH,
    "verificationStatus": "metadata-observed", "evidenceKind": "native-project-metadata",
}
PROJECT = {
    "id": "orp-one", "name": NATIVE["name"], "description": "Synthetic fixture only",
    "kind": "native-openresearch", "upstreamProjectId": NATIVE["id"],
    "nativeProject": NATIVE, "connectionRefs": {"workspace": CONNECTION["ref"]},
    "sessionExecutionAvailable": False,
    "sessionBlocker": "NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED",
}
GROUP = {
    "id": "orp-group", "name": "Synthetic controlled group", "description": "",
    "kind": "factory-workspace", "connectionRefs": {}, "upstreamProjectId": None,
}
CONTROLLED_SESSION = {
    "id": "ors-one", "projectId": GROUP["id"], "goal": "Synthetic controlled goal",
    "workloadPresetId": "preset-one", "state": "unknown", "taskId": None,
    "executionContract": "controlled-workload-v1", "contextSource": "approved-workload-preset",
    "verificationStatus": "not-live-verified",
}


def fixtures(verified: bool) -> dict:
    personal_project = {
        "name": "Synthetic personal project", "nativeProjectId": "synthetic-project",
        "upstreamOrxProjectId": "synthetic-project", "connectionPin": CONNECTION,
        "namespace": "native-openresearch", "executionContract": "personal-external-v1",
        "modelCredentialCustody": "remote", "budgetEnforcement": "advisory",
        "stopGuarantee": "unverified", "sessionCreationSupported": False,
    }
    session = {
        "id": "synthetic-session", "namespace": "native-openresearch",
        "executionContract": "personal-external-v1", "connectionRef": CONNECTION["ref"],
        "connectionPin": CONNECTION, "bindingStatus": "active", "bindingHistory": [],
        "nativeProjectId": "synthetic-project", "upstreamOrxProjectId": "synthetic-project",
        "nativeSessionId": "synthetic-native-session", "activeRequestId": None,
        "state": "result_observed", "factoryIdentity": None,
        "modelCredentialCustody": "remote", "budgetEnforcement": "advisory",
        "stopVerified": False, "liveEndToEndVerified": verified,
        "observation": {
            "sessionId": "synthetic-native-session", "projectId": "synthetic-project",
            "observedAt": "2026-10-13T00:00:00Z", "provenance": "remote-reported",
            "trustedMetering": False, "exactTurnVerified": False,
            "messages": [
                {"id": "question", "role": "user", "completed": True,
                 "events": [{"type": "text", "text": "Synthetic historical research goal"}],
                 "usageProvenance": "unavailable"},
                {"id": "answer", "role": "assistant", "completed": True,
                 "events": [{"type": "text", "text": "Synthetic historical answer: no model was called."}],
                 "usageProvenance": "unavailable"},
            ],
        },
    }
    return {
        "/auth/config": {"enabled": False, "loginPath": "/api/factory/auth/login", "logoutPath": "/api/factory/auth/logout"},
        "/session": OWNER,
        "/status": {"mode": "demo", "activeWorkers": 0, "queuedJobs": 0, "maxWorkers": 2},
        "/materials": [], "/jobs": [], "/execution-targets": [], "/applications": [],
        "/user-connections": [CONNECTION],
        "/commands": {"items": [], "nextCursor": None},
        "/compositions/proposals": {"schema": 1, "ownerId": OWNER["id"], "items": [], "nextCursor": None, "snapshot": False},
        "/personal-agent/capabilities": {
            "executionContract": "personal-external-v1", "nativeQueue": True,
            "ownerSubmit": "/api/factory/personal-agent/commands/submit",
            "modelConfiguration": "remote-configured-model", "factoryBYOKForwarded": False,
        },
        "/personal-agent/sessions": [session],
        "/personal-agent/sessions/synthetic-session": session,
        "/personal-agent/projects": personal_project,
        "/personal-agent/native-sessions": {
            "nativeProjectId": "synthetic-project", "namespace": "native-openresearch",
            "executionContract": "personal-external-v1", "connectionPin": CONNECTION,
            "sessions": [{"nativeProjectId": "synthetic-project", "nativeSessionId": "synthetic-native-session", "title": "Synthetic existing session"}],
        },
        "/personal-remotes": [{
            "registrationRef": CONNECTION["registrationRef"], "providerId": "openresearch-personal-session-v1",
            "origin": "https://runtime.example.invalid", "projectId": "synthetic-project",
            "status": "verified", "available": True, "allowedActions": [],
            "capabilities": CONNECTION["capabilities"], "revision": "synthetic-r1",
            "configRevision": "synthetic-r1", "expiresAt": None,
        }],
        "/personal-remotes/providers": [], "/personal-credentials": [],
        "/personal-credentials/capabilities": {"enabled": False, "providerIds": []},
        "/personal-models": [], "/personal-ssh": [],
        "/personal-ssh/capabilities": {"enabled": False},
        "/application-environments": [], "/application-environments/servers": [],
        "/application-environments/capabilities": {"locations": [], "applications": []},
        "/openresearch/capabilities": {
            "contractVersion": 1, "nativeProjectAttachment": True, "upstreamProjectCreation": False,
            "liveEndToEndVerified": verified,
            "workloads": [{"id": "preset-one", "name": "Synthetic controlled preset", "ready": True, "blockers": [], "limits": {"maxExperiments": 1}}],
        },
        "/openresearch/projects": [PROJECT, GROUP],
        "/openresearch/projects/orp-one": PROJECT,
        "/openresearch/projects/orp-one/sessions": [],
        "/openresearch/projects/orp-one/managed-profiles": [],
        "/openresearch/projects/orp-group": GROUP,
        "/openresearch/projects/orp-group/sessions": [CONTROLLED_SESSION],
        "/openresearch/native-projects": {"connectionRef": CONNECTION["ref"], "projects": [NATIVE]},
        "/autoresearch/presets": [{"id": "preset-one", "name": "Synthetic controlled preset", "defaultGoal": "Synthetic default goal", "ready": True, "blockers": [], "limits": {"maxExperiments": 1}}],
    }


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def scenario(browser, base: str, output: Path, name: str, viewport: dict, verified: bool):
    context = browser.new_context(viewport=viewport, service_workers="block")
    page = context.new_page()
    page.set_default_timeout(10000)
    responses = fixtures(verified)
    requests, violations, page_errors = [], [], []
    widths = {}
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def capture(stage):
        width = page.evaluate("({viewport: innerWidth, document: document.documentElement.scrollWidth})")
        assert width["document"] <= width["viewport"] + 1, f"{stage} horizontal overflow: {width}"
        widths[stage] = width
        page.screenshot(path=str(output / f"{name}-{stage}.png"), full_page=True)

    def intercept(route):
        request = route.request
        url = urlsplit(request.url)
        if f"{url.scheme}://{url.netloc}" != base:
            violations.append(f"external request: {request.url}")
            route.abort()
            return
        if url.path.startswith("/api/"):
            requests.append({"method": request.method, "path": url.path, "query": url.query})
            path = url.path.removeprefix("/api/factory")
            query = parse_qs(url.query)
            valid_connection = query.get("connectionRef", [CONNECTION["ref"]]) == [CONNECTION["ref"]]
            if request.method != "GET" or path not in responses or not valid_connection:
                violations.append(f"unconfigured API: {request.method} {url.path}?{url.query}")
                route.fulfill(status=599, json={"error": "Synthetic smoke rejects unexpected requests"})
            else:
                route.fulfill(status=200, json=responses[path])
            return
        if request.method == "GET" and (url.path == "/" or url.path.startswith("/assets/")):
            route.continue_()
        else:
            violations.append(f"unexpected resource: {request.method} {url.path}")
            route.abort()

    context.route("**/*", intercept)
    try:
        page.goto(base + "/", wait_until="networkidle")
        expect(page.get_by_role("heading", name="选择你的工作区", exact=True)).to_be_visible()
        page.get_by_role("button", name="进入 OpenResearch", exact=True).click()
        expect(page).to_have_url(base + "/?tab=openresearch")
        expect(page.get_by_role("heading", name="OpenResearch", exact=True)).to_be_visible()
        page.get_by_role("button", name="Synthetic historical research goal", exact=True).click()
        expect(page.get_by_label("研究结果", exact=True).get_by_text("Synthetic historical answer: no model was called.", exact=True)).to_be_visible()
        page.reload(wait_until="networkidle")
        expect(page.get_by_label("研究结果", exact=True).get_by_text("Synthetic historical answer: no model was called.", exact=True)).to_be_visible()
        capture("personal")

        page.get_by_text("其他模式与资源", exact=True).click()
        page.get_by_role("button", name="切换受管模式（可选）", exact=True).click()
        page.get_by_role("button", name="Synthetic native project", exact=False).click()
        expect(page.get_by_role("heading", name=PROJECT["name"], exact=True)).to_be_visible()
        expect(page.get_by_text(PROJECT["sessionBlocker"], exact=True)).to_be_visible()
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name=PROJECT["name"], exact=True)).to_be_visible()
        page.get_by_role("button", name="项目", exact=True).click()
        page.get_by_role("button", name="Synthetic controlled group", exact=False).click()
        expect(page.get_by_role("heading", name=CONTROLLED_SESSION["goal"], exact=True)).to_be_visible()
        expect(page.get_by_text("受控工作负载 · unknown · not-live-verified", exact=True)).to_be_visible()
        capture("managed")

        page.get_by_role("button", name="高级与管理", exact=True).click()
        page.get_by_role("button", name="开发者装配", exact=True).click()
        page.get_by_text("受控实验开发入口", exact=True).click()
        page.get_by_role("button", name="打开受控 Auto-Research 实验", exact=True).click()
        expect(page).to_have_url(re.compile(r"[?&]tab=autoresearch(?:&|$)"))
        expect(page.get_by_role("heading", name="Synthetic controlled preset", exact=True)).to_be_visible()
        page.get_by_role("button", name="检查默认目标", exact=True).click()
        expect(page.get_by_role("heading", name="开始前确认", exact=True)).to_be_visible()
        page.get_by_role("button", name="返回修改", exact=True).click()
        page.go_back(wait_until="networkidle")
        expect(page.get_by_role("heading", name="开发者装配", exact=True)).to_be_visible()
        page.go_forward(wait_until="networkidle")
        expect(page.get_by_role("heading", name="Synthetic controlled preset", exact=True)).to_be_visible()
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name="Synthetic controlled preset", exact=True)).to_be_visible()
        capture("autoresearch")
        paths = {row["path"] for row in requests}
        for path in ["/personal-agent/projects", "/personal-agent/sessions/synthetic-session", "/openresearch/projects/orp-one", "/openresearch/projects/orp-group/sessions", "/autoresearch/presets"]:
            assert "/api/factory" + path in paths, f"GET was not exercised: {path}"
        assert not violations, violations
        assert not page_errors, page_errors
        return {"scenario": name, "viewport": viewport, "liveEndToEndVerified": verified, "apiRequests": requests, "externalRequests": 0, "writeRequests": 0, "pageErrors": page_errors, "horizontalWidths": widths, "result": "passed"}
    except Exception:
        page.screenshot(path=str(output / f"{name}-failure.png"), full_page=True)
        (output / f"{name}-failure.txt").write_text(json.dumps({"violations": violations, "pageErrors": page_errors, "requests": requests, "body": page.locator("body").inner_text()}, ensure_ascii=False, indent=2))
        raise
    finally:
        context.close()


def prepared_scenario(browser, base: str, output: Path, name: str, *, unknown=False, race=False):
    """Only the exact original prepared command may reach the synthetic POST stub."""
    context = browser.new_context(viewport={"width": 390 if unknown or race else 1440, "height": 1000}, service_workers="block")
    original_request = "synthetic-original-prepared-request"
    context.add_init_script(f"localStorage.setItem('factory-or-pending:alice', {json.dumps(original_request)})")
    page = context.new_page()
    page.set_default_timeout(10000)
    responses = fixtures(False)
    session = {**CONTROLLED_SESSION, "state": "unknown" if unknown else "prepared"}
    responses["/openresearch/projects/orp-group/sessions"] = [session]
    recovery_path = f"/openresearch/requests/{original_request}"
    expected_body = {"workloadPresetId": session["workloadPresetId"], "goal": session["goal"], "requestId": original_request, "executionContract": "controlled-workload-v1"}
    reads, writes, violations, errors = [], [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def intercept(route):
        request = route.request
        url = urlsplit(request.url)
        if f"{url.scheme}://{url.netloc}" != base:
            violations.append(f"external request: {request.url}")
            route.abort()
            return
        path = url.path.removeprefix("/api/factory")
        if url.path.startswith("/api/"):
            if request.method == "GET" and path == recovery_path:
                reads.append(path)
                if race and len(reads) > 1:
                    session["state"] = "unknown"
                route.fulfill(status=200, json={"requestId": original_request, "action": "session-create", "session": session})
            elif request.method == "GET" and path in responses:
                route.fulfill(status=200, json=responses[path])
            elif request.method == "POST" and path == "/openresearch/projects/orp-group/sessions" and not unknown and not race:
                body = request.post_data_json
                writes.append(body)
                if body != expected_body or len(writes) != 1 or len(reads) < 2:
                    violations.append(f"unexpected original command: {body}")
                    route.fulfill(status=599, json={"error": "Invalid synthetic command"})
                else:
                    session.update({"state": "queued", "taskId": "synthetic-original-task"})
                    route.fulfill(status=200, json=session)
            else:
                violations.append(f"unconfigured API: {request.method} {url.path}")
                route.fulfill(status=599, json={"error": "Unexpected synthetic request"})
        elif request.method == "GET" and (url.path == "/" or url.path.startswith("/assets/")):
            route.continue_()
        else:
            violations.append(f"unexpected resource: {request.method} {url.path}")
            route.abort()

    context.route("**/*", intercept)
    try:
        page.goto(base + "/?tab=openresearch&mode=managed&project=orp-group", wait_until="networkidle")
        page.get_by_role("button", name="核对原请求", exact=True).click()
        if unknown:
            expect(page.get_by_role("button", name="继续原受控会话请求", exact=True)).to_have_count(0)
            expect(page.get_by_text(re.compile("原请求尚待核对：" + original_request))).to_be_visible()
        else:
            retry = page.get_by_role("button", name="继续原受控会话请求", exact=True)
            expect(retry).to_be_visible()
            expect(page.get_by_role("button", name="确认范围并提交受控会话", exact=True)).to_be_disabled()
            retry.click()
            expect(retry).to_have_count(0)
            if not race:
                expect(page.get_by_text("受控工作负载 · queued · not-live-verified", exact=True)).to_be_visible()
        pending = page.evaluate("localStorage.getItem('factory-or-pending:alice')")
        assert pending == (original_request if unknown or race else None), pending
        assert len(writes) == (0 if unknown or race else 1), writes
        assert len(reads) == (1 if unknown else 2), reads
        assert not violations, violations
        assert not errors, errors
        page.screenshot(path=str(output / f"{name}.png"), full_page=True)
        return {"scenario": name, "result": "passed", "recoveryReads": len(reads), "syntheticWriteBodies": writes, "pendingRequest": pending, "externalRequests": 0, "pageErrors": errors}
    except Exception:
        page.screenshot(path=str(output / f"{name}-failure.png"), full_page=True)
        (output / f"{name}-failure.txt").write_text(json.dumps({"violations": violations, "errors": errors, "reads": reads, "writes": writes, "body": page.locator("body").inner_text()}, ensure_ascii=False, indent=2))
        raise
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--browser", default=shutil.which("chromium") or shutil.which("google-chrome"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not (args.dist / "index.html").is_file():
        parser.error("Built UI missing; run npm run build first")
    if not args.browser:
        parser.error("No Chromium binary found; supply --browser (this script never installs one)")
    output = args.output or Path(tempfile.mkdtemp(prefix="agent-factory-browser-smoke-"))
    output.mkdir(parents=True, exist_ok=True)
    print(f"Synthetic screenshots and request evidence: {output}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(args.dist)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            try:
                results = [scenario(browser, f"http://127.0.0.1:{server.server_port}", output, name, viewport, verified)
                           for name, viewport, verified in [
                               ("desktop-false", {"width": 1440, "height": 1000}, False),
                               ("desktop-true", {"width": 1440, "height": 1000}, True),
                               ("narrow-false", {"width": 390, "height": 844}, False),
                               ("narrow-true", {"width": 390, "height": 844}, True),
                           ]]
                for name, options in [
                    ("desktop-prepared-original-command", {}),
                    ("narrow-unknown-readonly", {"unknown": True}),
                    ("narrow-prepared-became-unknown", {"race": True}),
                ]:
                    results.append(prepared_scenario(browser, f"http://127.0.0.1:{server.server_port}", output, name, **options))
                (output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
                print(json.dumps({"scenariosPassed": len(results), "output": str(output), "modelIntegrationVerified": False}))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
