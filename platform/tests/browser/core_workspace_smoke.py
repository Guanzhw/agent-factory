"""Real core deployment/browser acceptance on newly created empty PostgreSQL.

Run after npm run build, with Playwright Chromium installed:
PYTHONPATH=platform:platform/tests:deployment:scripts python \
platform/tests/browser/core_workspace_smoke.py --database-url <disposable-loopback-PG> \
--output scratch/core-workspace-browser

Creates a distinct af_test_<uuid> database and temporary workspace for each mode;
only those newly generated fixtures are cleaned up. Never point at old data or
pass provider credentials. Uses the real deployment composition and business
HTTP endpoints, no Playwright routes or API mocks. Demo uses the development
OIDC selector; production-mode uses the existing local synthetic OIDC fixture
with real HTTPS code exchange. Neither proves real external production identity.
TLS certificate bypass is confined to the browser fixture context. No HAR,
trace, tokens, cookies, authorization URLs or private keys enter evidence.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import ssl
import tempfile

import httpx
from playwright.sync_api import expect, sync_playwright

from accept_browser_auth import listener, serve
from agent_factory.browser_oidc import BrowserCodeExchanger
from fixture_settings import Settings
from agent_factory_server.main import create_app, factory_state
from browser_identity_fixture import BrowserIdentityFixture, private_tls_files
from pg_fixture import IsolatedPostgres


def scenario(browser, origin, output, mode, viewport):
    context = browser.new_context(ignore_https_errors=True, viewport=viewport, service_workers="block")
    errors, failed_api = [], []
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    # Store only endpoint paths/statuses, never auth query strings or bodies.
    page.on("response", lambda response: failed_api.append({"path": response.url.split("?", 1)[0].removeprefix(origin),
        "status": response.status}) if response.status >= 400 and response.status != 401 and "/api/" in response.url else None)
    login_name = "选择开发测试身份" if mode == "demo" else "使用企业账号登录"
    screenshots = []

    def settled_workspace():
        # A heading mounts before its HTTP reads finish. Wait for those reads,
        # then require the actual mode and healthy workspace synchronization.
        page.wait_for_load_state("networkidle")
        expect(page.locator(".sync-state")).to_contain_text("页面已同步")
        expect(page.locator(".runtime-strip strong")).to_have_text("演示运行" if mode == "demo" else "真实运行模式")

    def screenshot(name):
        if name != "failure" and page.locator(".factory-shell").count():
            settled_workspace()
        filename = name + ".png"
        page.screenshot(path=str(output / filename), full_page=True)
        screenshots.append(filename)

    def login():
        button = page.get_by_role("button", name=login_name, exact=True)
        expect(button).to_be_enabled()
        button.click()
        if mode == "demo":
            page.locator('button[name="persona"][value="alice"]').click()
        expect(page.get_by_role("button", name="退出", exact=True)).to_be_visible()
        response = context.request.get(origin + "/api/factory/session")
        assert response.ok and response.json()["id"] == "alice"
        cookie = next(item for item in context.cookies() if item["name"] == "__Host-factory_session")
        assert cookie["httpOnly"] and cookie["secure"] and cookie["path"] == "/"

    def view(tab, title):
        page.goto(origin + "/?tab=" + tab)
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        settled_workspace()
        page.reload()
        expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="退出", exact=True)).to_be_visible()
        settled_workspace()
        assert not page.get_by_text("OpenResearch", exact=False).count()
        assert not page.get_by_text("Auto-Research", exact=False).count()
        assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        screenshot(tab)

    try:
        page.goto(origin + "/?tab=resources#connections")
        expect(page.get_by_role("button", name=login_name, exact=True)).to_be_visible()
        screenshot("login")
        login()
        expect(page).to_have_url(origin + "/?tab=resources#connections")
        expect(page.get_by_role("heading", name="我的资源", exact=True)).to_be_visible()
        screenshot("login-return")
        page.get_by_role("button", name="应用", exact=True).click()
        expect(page.get_by_text("暂无已接入的应用。", exact=True)).to_be_visible()
        page.go_back()
        expect(page.get_by_role("heading", name="我的资源", exact=True)).to_be_visible()
        page.go_forward()
        expect(page.get_by_text("暂无已接入的应用。", exact=True)).to_be_visible()
        screenshot("home")
        status = context.request.get(origin + "/api/factory/status")
        assert status.ok and status.json()["mode"] == ("demo" if mode == "demo" else "live")
        for tab, title in (("catalog", "应用目录"), ("tasks", "任务与证据"), ("resources", "我的资源"),
                           ("models", "我的模型/API"), ("connections", "我的凭据与连接")):
            view(tab, title)
        page.get_by_role("button", name="任务", exact=True).click()
        expect(page.get_by_text("尚无任务。在应用中提交目标后，在此查看进度与结果。", exact=True)).to_be_visible()
        page.get_by_role("button", name="资源", exact=True).click()
        page.get_by_role("button", name="设置我的模型/API", exact=True).click()
        expect(page.get_by_role("heading", name="我的模型/API", exact=True)).to_be_visible()
        page.get_by_role("button", name="返回工作区", exact=True).click()
        expect(page.get_by_role("heading", name="我的资源", exact=True)).to_be_visible()
        page.get_by_role("button", name="管理服务器与连接", exact=True).click()
        expect(page.get_by_role("heading", name="我的凭据与连接", exact=True)).to_be_visible()
        for tab in ("research", "openresearch", "autoresearch", "comparison"):
            page.goto(origin + "/?tab=" + tab)
            expect(page.get_by_text("暂无已接入的应用。", exact=True)).to_be_visible()
            expect(page).to_have_url(origin + "/?tab=catalog")
            assert not page.get_by_text("OpenResearch", exact=False).count()
        screenshot("retired-entry")
        page.get_by_role("button", name="退出", exact=True).click()
        expect(page.get_by_role("button", name=login_name, exact=True)).to_be_enabled()
        assert context.request.get(origin + "/api/factory/session").status == 401
        assert context.request.get(origin + "/api/factory/auth/session").json()["authenticated"] is False
        screenshot("logout")
        login()
        expect(page.get_by_text("暂无已接入的应用。", exact=True)).to_be_visible()
        screenshot("relogin")
        assert not errors, errors
        assert not failed_api, failed_api
        return {"screenshots": screenshots, "login": True, "emptyCatalog": True, "emptyTasks": True,
                "resourceNavigation": True, "directURLsAndRefresh": True, "retiredURLs": True,
                "loginDeepLinkReturn": True, "backForward": True,
                "logoutRevokesSession": True, "relogin": True, "pageErrors": errors, "serverErrors": failed_api}
    except BaseException:
        screenshot("failure")
        raise
    finally:
        context.close()


def run_mode(browser, args, mode):
    output = args.output / mode
    output.mkdir()
    with ExitStack() as stack:
        database = stack.enter_context(IsolatedPostgres(args.database_url))
        scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="core-workspace-")))
        certificate, key = private_tls_files(scratch / "tls")
        app_socket = listener()
        stack.callback(app_socket.close)
        origin = "https://127.0.0.1:" + str(app_socket.getsockname()[1])
        options = {"development_mock_login": True, "development_public_origin": origin} if mode == "demo" else {}
        identity = None
        if mode != "demo":
            idp_socket = listener()
            stack.callback(idp_socket.close)
            issuer = "https://127.0.0.1:" + str(idp_socket.getsockname()[1])
            identity = BrowserIdentityFixture(issuer=issuer, redirect_uri=origin + "/api/factory/auth/callback")
            options["browser_oidc"] = identity.config()
        settings = Settings(db_url=database.url, workspace=scratch / "workspace", demo=mode == "demo",
            jwt_key="synthetic-core-browser-fixture-signing-key-at-least-32bytes", max_workers=1,
            web_directory=args.dist.resolve(), **options)
        app = create_app(settings)
        state = factory_state(app)
        store, auth = state["store"], state["auth"]
        stack.callback(store.engine.dispose)
        stack.callback(store.native_db.db_engine.dispose)
        if identity:
            tls = ssl.create_default_context(cafile=str(certificate))
            state["browser_auth"].exchanger = BrowserCodeExchanger(identity.config(),
                transport=httpx.AsyncHTTPTransport(verify=tls, retries=0))
            # Active synthetic accounts use the core trusted-team authorization provider.
            auth.directory.upsert("alice", name="Synthetic Alice")
            serve(stack, identity.app, idp_socket, certificate, key)
        serve(stack, app, app_socket, certificate, key)
        results = {}
        for name, viewport in (("desktop", {"width": 1440, "height": 1000}), ("mobile", {"width": 390, "height": 844})):
            target = output / name
            target.mkdir()
            results[name] = scenario(browser, origin, target, mode, viewport)
        if identity:
            assert identity.authorizations >= 4 and identity.exchanges >= 4
        return {"mode": mode, "database": database.name, "newIsolatedDatabase": True,
                "identity": "development-selector" if mode == "demo" else "local-synthetic-oidc-over-https",
                "realExternalProductionIdentityVerified": False, "businessAPIsMocked": False, "viewports": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Authorized disposable loopback PG admin connection")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--browser", help="Existing Chromium executable")
    parser.add_argument("--mode", choices=("demo", "production-local", "both"), default="both")
    args = parser.parse_args()
    assert (args.dist / "index.html").is_file(), "Build frontend first"
    args.output.mkdir(parents=True, exist_ok=False)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
        try:
            modes = ("demo", "production-local") if args.mode == "both" else (args.mode,)
            evidence = {"ok": True, "results": [run_mode(browser, args, mode) for mode in modes]}
            (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
            print(json.dumps({"ok": True, "output": str(args.output)}))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
