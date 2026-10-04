"""In-memory mock IdP and existing SQLite browser sessions; no network/PG."""
import asyncio
import base64
import hashlib
import importlib.util
import io
import os
import stat
from contextlib import contextmanager
from pathlib import Path
import re
import secrets
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import HTTPException
import httpx
from sqlalchemy import create_engine, text

from agent_factory.browser_auth import BrowserSessionService
from agent_factory.browser_oidc import BrowserOIDCError
from agent_factory.development_identity import (DevelopmentIdentityError, DevelopmentIdentityProvider,
    PERSONAS, PREFIX)

ORIGIN = "https://127.0.0.1:3443"


class MockIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.provider = DevelopmentIdentityProvider(demo=True, public_origin=ORIGIN)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.provider.app), base_url=ORIGIN,
                                       follow_redirects=False, trust_env=False)
        self.addAsyncCleanup(self.client.aclose)

    def parameters(self):
        verifier = secrets.token_urlsafe(32)
        return {"response_type": "code", "client_id": self.provider.config.client_id,
            "redirect_uri": self.provider.config.redirect_uri, "scope": "openid", "state": secrets.token_urlsafe(32),
            "nonce": secrets.token_urlsafe(32), "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}, verifier

    async def begin(self, client=None, params=None) -> Any:
        params, verifier = self.parameters() if params is None else (params, None)
        response = await (client or self.client).get(PREFIX + "/authorize", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        form = {}
        for name in ("flow", "csrf"):
            match = re.search('name="' + name + '" value="([A-Za-z0-9_-]{43})"', response.text)
            assert match is not None
            form[name] = match.group(1)
        return form, params, verifier, response

    async def select(self, persona, *, client=None, form=None) -> Any:
        if form is None:
            form, params, verifier, _ = await self.begin(client)
        else:
            params = verifier = None
        response = await (client or self.client).post(PREFIX + "/select", data={**form, "persona": persona}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 303, response.text)
        return parse_qs(urlsplit(response.headers["location"]).query), params, verifier

    async def test_mock_is_explicit_demo_loopback_and_ephemeral(self):
        for demo, origin in [(False, ORIGIN), (1, ORIGIN), (True, "http://127.0.0.1:3443"),
                             (True, "https://company.example"), (True, ORIGIN + "/path"),
                             (True, "https://user:pass@127.0.0.1:3443")]:
            with self.subTest(demo=demo, origin=origin), patch("agent_factory.development_identity.rsa.generate_private_key") as generate:
                with self.assertRaises(DevelopmentIdentityError):
                    DevelopmentIdentityProvider(demo=demo, public_origin=origin)
                generate.assert_not_called()
        other = DevelopmentIdentityProvider(demo=True, public_origin=ORIGIN)
        self.assertNotEqual(self.provider.config.fingerprint, other.config.fingerprint)
        self.assertEqual(set(PERSONAS), {"alice", "bob", "manager", "manager2"})
        self.assertNotIn("d", self.provider.config.jwks["keys"][0])

    async def test_two_browsers_choose_independent_personas_and_original_oidc_verifies(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.provider.app), base_url=ORIGIN,
                                    follow_redirects=False, trust_env=False) as second:
            left, right = await asyncio.gather(self.begin(), self.begin(second))
            codes = await asyncio.gather(self.select("alice", form=left[0]), self.select("bob", client=second, form=right[0]))
            for code, original, owner in [(codes[0], left, "alice"), (codes[1], right, "bob")]:
                self.assertEqual(code[0]["state"], [original[1]["state"]])
                identity = await self.provider.exchanger.exchange(code[0]["code"][0], code_verifier=original[2], nonce=original[1]["nonce"])
                self.assertEqual(identity.owner_id, owner)
                with self.assertRaises(BrowserOIDCError):
                    await self.provider.exchanger.exchange(code[0]["code"][0], code_verifier=original[2], nonce=original[1]["nonce"])

    async def test_selector_origin_csrf_cookie_and_one_use_flow(self):
        form, params, verifier, response = await self.begin()
        cookie = response.headers["set-cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=strict"):
            self.assertIn(flag, cookie)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["referrer-policy"], "strict-origin")
        for origin, body in [("https://evil.example", {**form, "persona": "manager"}),
                             ("null", {**form, "persona": "manager"}),
                             (ORIGIN, {**form, "csrf": "x"*43, "persona": "manager"}),
                             (ORIGIN, {**form, "persona": "unmapped-admin"})]:
            denied = await self.client.post(PREFIX + "/select", data=body, headers={"Origin": origin})
            self.assertEqual(denied.status_code, 400)
            self.assertEqual(denied.headers["referrer-policy"], "no-referrer")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.provider.app), base_url=ORIGIN) as unrelated:
            denied = await unrelated.post(PREFIX + "/select", data={**form, "persona": "manager"}, headers={"Origin": ORIGIN})
            self.assertEqual(denied.status_code, 400)
        callback, _, _ = await self.select("manager2", form=form)
        self.assertEqual((await self.provider.exchanger.exchange(callback["code"][0], code_verifier=verifier, nonce=params["nonce"])).owner_id, "manager2")
        replay = await self.client.post(PREFIX + "/select", data={**form, "persona": "alice"}, headers={"Origin": ORIGIN})
        self.assertEqual(replay.status_code, 400)

    async def test_cancel_and_expiry_issue_no_identity(self):
        form, _, _, _ = await self.begin()
        result, _, _ = await self.select("cancel", form=form)
        self.assertEqual(result["auth_error"], ["signin_cancelled"])
        self.assertEqual(self.provider._codes, {})
        form, _, _, _ = await self.begin()
        with patch("agent_factory.development_identity.time.time", return_value=time.time()+301):
            denied = await self.client.post(PREFIX + "/select", data={**form, "persona": "alice"}, headers={"Origin": ORIGIN})
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(self.provider._codes, {})

    async def test_strict_requests_and_wrong_pkce_never_mint_an_identity(self):
        params, _ = self.parameters()
        for changed in [{**params, "redirect_uri": "https://evil.example"}, {**params, "code_challenge_method": "plain"},
                        {**params, "scope": "openid admin"}, {**params, "extra": "untrusted"}]:
            denied = await self.client.get(PREFIX + "/authorize", params=changed)
            self.assertEqual(denied.status_code, 400)
        duplicate = list(params.items()) + [("nonce", params["nonce"])]
        self.assertEqual((await self.client.get(PREFIX + "/authorize", params=urlencode(duplicate))).status_code, 400)
        callback, selected, verifier = await self.select("alice")
        with self.assertRaises(BrowserOIDCError):
            await self.provider.exchanger.exchange(callback["code"][0], code_verifier="x"*43, nonce=selected["nonce"])
        with self.assertRaises(BrowserOIDCError):
            await self.provider.exchanger.exchange(callback["code"][0], code_verifier=verifier, nonce=selected["nonce"])
        denied = await self.client.post(PREFIX + "/token", content=b"x"*4097,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(denied.status_code, 400)

    async def test_expired_code_and_wrong_nonce_use_original_verifier(self):
        callback, params, verifier = await self.select("alice")
        with patch("agent_factory.development_identity.time.time", return_value=time.time()+61):
            with self.assertRaises(BrowserOIDCError):
                await self.provider.exchanger.exchange(callback["code"][0], code_verifier=verifier, nonce=params["nonce"])
        callback, params, verifier = await self.select("bob")
        with self.assertRaises(BrowserOIDCError):
            await self.provider.exchanger.exchange(callback["code"][0], code_verifier=verifier, nonce="x"*43)
        self.assertEqual(self.provider._codes, {})

    async def test_https_host_not_forwarded_headers_define_transport(self):
        params, _ = self.parameters()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.provider.app), base_url="http://127.0.0.1:3443") as client:
            denied = await client.get(PREFIX + "/authorize", params=params, headers={"X-Forwarded-Proto": "https"})
            self.assertEqual(denied.status_code, 400)
        denied = await self.client.get(PREFIX + "/authorize", params=params, headers={"Host": "evil.example"})
        self.assertEqual(denied.status_code, 400)

    async def test_existing_sql_session_lifecycle_logout_and_current_owner_recheck(self):
        with TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + str(Path(directory) / "browser.sqlite"))
            self.addCleanup(engine.dispose)
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE af_browser_auth(id TEXT PRIMARY KEY,kind TEXT,body TEXT)"))
            enabled = {"alice", "bob", "manager", "manager2"}
            def current(owner):
                if owner not in enabled:
                    raise HTTPException(403, "Synthetic owner disabled")
                return {"id": owner}
            authority = SimpleNamespace(_key="synthetic-browser-key-memory-only-not-a-production-credential", _current_user=current)
            service = BrowserSessionService(SimpleNamespace(engine=engine), authority, self.provider.config, exchanger=self.provider.exchanger)
            url, binding = service.start()
            params = {key: value[0] for key, value in parse_qs(urlsplit(url).query).items()}
            form, _, _, _ = await self.begin(params=params)
            callback, _, _ = await self.select("alice", form=form)
            opaque = await service.finish(callback["code"][0], callback["state"][0], binding)
            self.assertEqual(service.session(opaque)["owner"], "alice")
            self.assertEqual(len(service.csrf(opaque)), 43)
            enabled.remove("alice")
            with self.assertRaises(HTTPException):
                service.session(opaque)
            enabled.add("alice")
            service.logout(opaque)
            with self.assertRaises(HTTPException):
                service.session(opaque)
            with self.assertRaises(HTTPException):
                await service.finish(callback["code"][0], callback["state"][0], binding)
            with engine.connect() as connection:
                rows = connection.execute(text("SELECT body FROM af_browser_auth")).all()
            self.assertNotIn(callback["code"][0], str(rows))
            self.assertNotIn(opaque, str(rows))


class DevelopmentLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[2] / "scripts" / "run_development_factory.py"
        spec = importlib.util.spec_from_file_location("fixture_development_launcher", path)
        assert spec is not None and spec.loader is not None
        cls.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.launcher)

    def test_settings_rejects_mock_production_unknown_origin_and_implicit_enablement(self):
        from agent_factory.config import Settings
        base = {"db_url": "postgresql+psycopg://synthetic/development", "workspace": Path("/tmp/synthetic-development")}
        selected = Settings(**base, development_mock_login=True, development_public_origin=ORIGIN)
        self.assertIs(selected.demo, True)
        self.assertIs(selected.development_mock_login, True)
        for changes in [
            {"demo": False, "development_mock_login": True, "development_public_origin": ORIGIN,
             "jwt_key": "synthetic-key-more-than-thirty-two-characters"},
            {"development_mock_login": True, "development_public_origin": None},
            {"development_mock_login": True, "development_public_origin": "https://company.example"},
            {"development_mock_login": False, "development_public_origin": ORIGIN},
            {"development_mock_login": 1, "development_public_origin": ORIGIN},
            {"development_mock_login": True, "development_public_origin": ORIGIN, "oidc_identity": object()},
        ]:
            with self.subTest(changes=tuple(changes)), self.assertRaises(ValueError):
                Settings(**base, **changes)

    def test_launcher_builds_only_explicit_demo_settings_without_starting_server(self):
        @contextmanager
        def synthetic_tls(origin):
            self.assertEqual(origin, ORIGIN)
            yield (Path("synthetic-cert"), Path("synthetic-key"))
        database_url = "postgresql+psycopg://demo:synthetic-password@127.0.0.1/development_only"
        with TemporaryDirectory() as directory, \
             patch.object(self.launcher, "Settings", side_effect=lambda **kwargs: SimpleNamespace(**kwargs)) as settings, \
             patch.object(self.launcher, "create_app", return_value=object()) as create, \
             patch.object(self.launcher, "temporary_development_tls", synthetic_tls), \
             patch.object(self.launcher.uvicorn, "run") as run, \
             patch.object(self.launcher.os, "getenv", side_effect=lambda key: database_url if key == "FACTORY_DATABASE_URL" else self.fail("Unrelated environment read")), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            result = self.launcher.main(["--public-origin", ORIGIN, "--workspace", directory])
        self.assertEqual(result, 0)
        self.assertEqual(settings.call_args.kwargs["temporary_policy"], "admin-review")
        self.assertIs(settings.call_args.kwargs["development_mock_login"], True)
        self.assertIs(settings.call_args.kwargs["demo"], True)
        self.assertEqual(settings.call_args.kwargs["max_workers"], 1)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(run.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(run.call_args.kwargs["port"], 3443)
        self.assertIs(run.call_args.kwargs["access_log"], False)
        self.assertIn("DEVELOPMENT MOCK ONLY", output.getvalue())
        self.assertNotIn("synthetic-password", output.getvalue())

    def test_launcher_rejects_missing_or_external_inputs_and_sanitizes_failures(self):
        database_url = "postgresql+psycopg://demo:synthetic-private-password@127.0.0.1/development_only"
        with TemporaryDirectory() as directory:
            for origin in ["https://company.example:3443", "http://127.0.0.1:3443", "https://127.0.0.1"]:
                with patch.object(self.launcher, "create_app") as create, patch("sys.stderr", new_callable=io.StringIO) as output:
                    result = self.launcher.main(["--public-origin", origin, "--workspace", directory, "--database-url", database_url])
                self.assertEqual(result, 1)
                create.assert_not_called()
                self.assertEqual(output.getvalue(), "DEVELOPMENT_LAUNCH_FAILED\n")
            with patch.object(self.launcher, "Settings", side_effect=lambda **kwargs: SimpleNamespace(**kwargs)), \
                 patch.object(self.launcher, "create_app", side_effect=RuntimeError(database_url)), \
                 patch("sys.stderr", new_callable=io.StringIO) as output:
                self.assertEqual(self.launcher.main(["--public-origin", ORIGIN, "--workspace", directory, "--database-url", database_url]), 1)
                self.assertNotIn("synthetic-private-password", output.getvalue())

    def test_temporary_tls_is_private_loopback_only_and_removed_after_error(self):
        from cryptography import x509
        from agent_factory.development_tls import temporary_development_tls
        certificate = key = None
        with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
            with temporary_development_tls(ORIGIN) as (certificate, key):
                if os.name == "posix":
                    self.assertEqual(stat.S_IMODE(certificate.stat().st_mode), 0o600)
                    self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
                    self.assertEqual(stat.S_IMODE(key.parent.stat().st_mode), 0o700)
                public = x509.load_pem_x509_certificate(certificate.read_bytes())
                alternatives = public.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
                self.assertEqual(str(alternatives.get_values_for_type(x509.IPAddress)[0]), "127.0.0.1")
                raise RuntimeError("synthetic interruption")
        assert certificate is not None and key is not None
        self.assertFalse(certificate.exists())
        self.assertFalse(key.exists())
        self.assertFalse(key.parent.exists())


if __name__ == "__main__":
    unittest.main()
