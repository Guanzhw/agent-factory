"""Desktop/mobile synthetic OIDC browser acceptance over loopback HTTPS only.

Uses a new disposable PG database and temporary self-signed TLS files. Browser
certificate bypass is limited to this synthetic context; no host trust changes.
No trace/HAR/token/cookie values are persisted in acceptance evidence.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import time

import httpx
from playwright.sync_api import expect, sync_playwright
import uvicorn

from agent_factory.browser_oidc import BrowserCodeExchanger
from agent_factory.config import Settings
from agent_factory.main import create_app
from browser_identity_fixture import BrowserIdentityFixture, private_tls_files
from pg_fixture import IsolatedPostgres


def listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    return sock


def serve(stack, app, sock, certificate, key):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=sock.getsockname()[1],
        ssl_certfile=str(certificate), ssl_keyfile=str(key), access_log=False, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    def stop():
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise RuntimeError("Synthetic HTTPS fixture did not stop")
    stack.callback(stop)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(.02)
    if not server.started:
        raise RuntimeError("Synthetic HTTPS fixture did not start")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    with ExitStack() as stack:
        database = stack.enter_context(IsolatedPostgres(args.database_url))
        scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="browser-auth-https-")))
        certificate, key = private_tls_files(scratch / "tls")
        app_socket, idp_socket = listener(), listener()
        stack.callback(app_socket.close)
        stack.callback(idp_socket.close)
        origin = "https://127.0.0.1:" + str(app_socket.getsockname()[1])
        issuer = "https://127.0.0.1:" + str(idp_socket.getsockname()[1])
        identity = BrowserIdentityFixture(issuer=issuer, redirect_uri=origin + "/api/factory/auth/callback")
        settings = Settings(db_url=database.url, workspace=scratch / "workspace", demo=False,
            jwt_key="synthetic-browser-acceptance-signing-key-at-least-32bytes",
            browser_oidc=identity.config(), max_workers=1)
        app = create_app(settings)
        state = app.app.state.factory
        store, auth = state["store"], state["auth"]
        stack.callback(store.engine.dispose)
        stack.callback(store.native_db.db_engine.dispose)
        tls = ssl.create_default_context(cafile=str(certificate))
        state["browser_auth"].exchanger = BrowserCodeExchanger(identity.config(),
            transport=httpx.AsyncHTTPTransport(verify=tls, retries=0))
        auth.authorization.define_role("browser-fixture-user", ["agents:factory-executor:read",
            "agents:factory-executor:run", "components:read", "registry:read", "sessions:read", "filesystem:read"])
        for owner in ("alice", "bob"):
            auth.directory.upsert(owner, name="Synthetic " + owner)
            auth.authorization.assign(owner, "browser-fixture-user")
        serve(stack, identity.app, idp_socket, certificate, key)
        serve(stack, app, app_socket, certificate, key)
        playwright = stack.enter_context(sync_playwright())
        browser = playwright.chromium.launch(headless=True)
        stack.callback(browser.close)
        evidence = {"identityMode": "synthetic-loopback-https", "realIdentityProviderVerified": False,
                    "hostTrustChanged": False, "screens": []}
        for name, viewport in (("desktop", {"width": 1440, "height": 1000}),
                               ("mobile", {"width": 390, "height": 844})):
            context = browser.new_context(ignore_https_errors=True, viewport=viewport)
            try:
                page = context.new_page()
                page.goto(origin)
                login = page.get_by_role("button", name="使用企业账号登录", exact=True)
                login.wait_for()
                expect(login).to_be_enabled()
                assert page.get_by_role("button", name="研究员 Alice", exact=True).count() == 0
                page.screenshot(path=str(args.output / (name + "-login.png")), full_page=True)
                identity.subject = "subject-alice"
                # A tab may abandon one flow before clicking sign-in again.
                pending = context.request.post(origin + "/api/factory/auth/login", data={},
                    headers={"Origin": origin})
                assert pending.ok
                login.click()
                logout = page.get_by_role("button", name="退出", exact=True)
                logout.wait_for()
                current = context.request.get(origin + "/api/factory/session")
                assert current.json()["id"] == "alice"
                assert "no-store" in current.headers["cache-control"]
                assert any(row["body"]["status"] == "CANCELLED" for row in
                    store.sql("SELECT body FROM af_browser_auth WHERE kind='flow'"))
                cookies = context.cookies()
                cookie = next(item for item in cookies if item["name"] == "__Host-factory_session")
                assert cookie["secure"] and cookie["httpOnly"] and cookie["path"] == "/"
                assert "factory_session" not in page.evaluate("document.cookie")
                page.reload()
                logout.wait_for()
                assert context.request.get(origin + "/api/factory/session").json()["id"] == "alice"
                page.get_by_text("尚无任务。先描述一个研究问题。", exact=True).wait_for()
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
                assert not overflow
                page.screenshot(path=str(args.output / (name + "-signed-in.png")), full_page=True)
                logout.click()
                login.wait_for()
                expect(login).to_be_enabled()
                assert not context.request.get(origin + "/api/factory/auth/session").json()["authenticated"]
                page.screenshot(path=str(args.output / (name + "-signed-out.png")), full_page=True)
                evidence["screens"].append({"viewport": name, "login": True, "reloadSession": True,
                    "logout": True, "pendingLoginRetry": True, "privateNoStore": True,
                    "httpOnlySecureCookie": True, "horizontalOverflow": False})
            finally:
                context.close()
        evidence["authorizationCount"] = identity.authorizations
        evidence["exchangeCount"] = identity.exchanges
        (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps({"ok": True, "output": str(args.output)}))


if __name__ == "__main__":
    main()
