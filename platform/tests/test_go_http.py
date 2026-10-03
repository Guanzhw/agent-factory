"""Offline Go HTTP policy tests; all environment values are synthetic."""
import os
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

import httpx

from agent_factory.go_http import open_go_client

_ROOT = "https://opencode.ai/zen/go/v1"


class _SelectedTransport(httpx.AsyncBaseTransport):
    created = []
    failure: Exception | None = None

    def __init__(self, *, proxy=None, retries=0, verify=True, trust_env=True, **_kwargs):
        self.proxy, self.retries, self.verify, self.trust_env = proxy, retries, verify, trust_env
        self.requests = []
        self.created.append(self)

    async def handle_async_request(self, request):
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return httpx.Response(200, json={"synthetic": True})


class GoHTTPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        _SelectedTransport.created = []
        _SelectedTransport.failure = None

    async def test_environment_proxy_selection_and_no_proxy_override(self):
        for bypass in (False, True):
            with self.subTest(no_proxy=bypass), patch.dict(os.environ, {
                "HTTPS_PROXY": "http://synthetic-proxy.invalid:8080",
                **({"NO_PROXY": "opencode.ai"} if bypass else {})}, clear=True), patch(
                    "httpx._client.AsyncHTTPTransport", _SelectedTransport):
                _SelectedTransport.created = []
                async with open_go_client(timeout=60) as client:
                    await client.get(_ROOT + "/models")
                    self.assertIsNone(client._auth)
                    used = [item for item in _SelectedTransport.created if item.requests]
                    self.assertEqual(len(used), 1)
                    self.assertEqual(used[0].proxy is None, bypass)
                    if not bypass:
                        self.assertEqual(str(used[0].proxy.url), "http://synthetic-proxy.invalid:8080")
                    self.assertTrue(all(item.verify is True and item.trust_env is True and item.retries == 0
                                        for item in _SelectedTransport.created))

    async def test_proxy_failure_has_no_retry_or_direct_fallback(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://synthetic-proxy.invalid:8080"}, clear=True), patch(
                "httpx._client.AsyncHTTPTransport", _SelectedTransport):
            _SelectedTransport.failure = httpx.ConnectError("synthetic proxy failure")
            async with open_go_client(timeout=60) as client:
                with self.assertRaises(httpx.ConnectError):
                    await client.get(_ROOT + "/models")
            used = [item for item in _SelectedTransport.created if item.requests]
            self.assertEqual(len(used), 1)
            self.assertIsNotNone(used[0].proxy)
            self.assertEqual(len(used[0].requests), 1)
            self.assertTrue(all(not item.requests for item in _SelectedTransport.created if item.proxy is None))

    async def test_real_httpx_transport_defaults_keep_tls_and_zero_retries(self):
        # Construct pools but never connect. This verifies installed HTTPX's
        # actual defaults, independently of the routing fake used above.
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://synthetic-proxy.invalid:8080"}, clear=True):
            async with open_go_client(timeout=60) as client:
                transports = [client._transport, *[value for value in client._mounts.values() if value is not None]]
                for transport in transports:
                    pool = getattr(transport, "_pool")
                    self.assertEqual(pool._retries, 0)
                    self.assertEqual(pool._ssl_context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(pool._ssl_context.check_hostname)

    async def test_fixture_transport_ignores_proxy_ca_and_netrc_environment(self):
        handler = Mock(return_value=httpx.Response(200))
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://synthetic-proxy.invalid:8080",
                "SSL_CERT_FILE": "/synthetic/nonexistent/ca.pem", "NETRC": "/synthetic/nonexistent/netrc"}, clear=True):
            async with open_go_client(timeout=60, transport=httpx.MockTransport(handler)) as client:
                await client.get(_ROOT + "/models")
                self.assertFalse(client.trust_env)
                self.assertEqual(client._mounts, {})
                self.assertIsNone(client._auth)
        handler.assert_called_once()
        self.assertNotIn("authorization", handler.call_args.args[0].headers)

    async def test_environment_ca_is_passed_to_verified_ssl_context(self):
        for name, parameter, value in (("SSL_CERT_FILE", "cafile", "/synthetic/reviewed-ca.pem"),
                                       ("SSL_CERT_DIR", "capath", "/synthetic/reviewed-ca-directory")):
            with self.subTest(name=name), patch.dict(os.environ, {name: value}, clear=True):
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                with patch("ssl.create_default_context", return_value=context) as create:
                    async with open_go_client(timeout=60):
                        create.assert_called_once_with(**{parameter: value})
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(context.check_hostname)

    async def test_invalid_environment_ca_fails_closed_without_tls_downgrade(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "SSL_CERT_FILE": str(Path(directory) / "missing.pem")}, clear=True):
            with self.assertRaises(FileNotFoundError):
                open_go_client(timeout=60)

    async def test_destination_guard_blocks_before_transport(self):
        invalid = [
            ("POST", "http://opencode.ai/zen/go/v1/responses"),
            ("POST", "https://other.invalid/zen/go/v1/responses"),
            ("POST", "https://opencode.ai.evil.invalid/zen/go/v1/responses"),
            ("POST", "https://opencode.ai:444/zen/go/v1/responses"),
            ("POST", "https://user:synthetic@opencode.ai/zen/go/v1/responses"),
            ("POST", _ROOT + "/responses?synthetic=value"),
            ("POST", _ROOT + "/responses#fragment"),
            ("POST", _ROOT + "/responses?"),
            ("POST", _ROOT + "/arbitrary"),
            ("GET", _ROOT + "/responses"),
            ("POST", _ROOT + "/models"),
        ]
        handler = Mock(return_value=httpx.Response(200))
        async with open_go_client(timeout=60, transport=httpx.MockTransport(handler)) as client:
            for method, url in invalid:
                with self.subTest(method=method, url=url), self.assertRaisesRegex(ValueError, "^GO_HTTP_DESTINATION_DENIED$"):
                    await client.request(method, url, headers={"authorization": "Bearer synthetic-placeholder"})
        handler.assert_not_called()

    async def test_only_fixed_models_get_and_inference_posts_are_allowed(self):
        handler = Mock(return_value=httpx.Response(200))
        async with open_go_client(timeout=60, transport=httpx.MockTransport(handler)) as client:
            await client.get(_ROOT + "/models")
            await client.post(_ROOT + "/responses")
            await client.post(_ROOT + "/chat/completions")
        self.assertEqual(handler.call_count, 3)

    async def test_redirect_never_sends_credentials_to_off_host(self):
        handler = Mock(return_value=httpx.Response(307, headers={"location": "https://other.invalid/stolen"}))
        async with open_go_client(timeout=60, transport=httpx.MockTransport(handler)) as client:
            result = await client.post(_ROOT + "/responses", headers={"authorization": "Bearer synthetic-placeholder"})
            self.assertEqual(result.status_code, 307)
            self.assertFalse(client.follow_redirects)
        handler.assert_called_once()
        self.assertEqual(handler.call_args.args[0].url.host, "opencode.ai")

    async def test_netrc_is_not_implicitly_used(self):
        with tempfile.TemporaryDirectory() as directory:
            netrc = Path(directory) / "synthetic-netrc"
            netrc.write_text("machine opencode.ai login synthetic-user password synthetic-password\n")
            with patch.dict(os.environ, {"NETRC": str(netrc)}, clear=True), patch(
                    "httpx._client.AsyncHTTPTransport", _SelectedTransport):
                async with open_go_client(timeout=60) as client:
                    await client.get(_ROOT + "/models")
                requests = [request for transport in _SelectedTransport.created for request in transport.requests]
                self.assertEqual(len(requests), 1)
                self.assertNotIn("authorization", requests[0].headers)

    def test_invalid_timeout_and_sync_transport_are_rejected(self):
        for timeout in (True, 0, -1, 61, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                open_go_client(timeout=timeout)
        with self.assertRaises(ValueError):
            open_go_client(timeout=60, transport=object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
