"""Offline fixed public source fetch boundaries; no credentials or sockets."""
import asyncio
import json
import ssl
import unittest
from unittest.mock import patch

import httpx

from agent_factory import public_code_fetch as fetch

PRIVATE = "synthetic-private-header-error-payload"


class Chunks(httpx.AsyncByteStream):
    def __init__(self, *chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class PublicCodeFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_fixed_gets_no_auth_cookie_redirect_and_fixture_label(self):
        requests = []
        def handler(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("cookie", request.headers)
            self.assertEqual(request.headers["accept-encoding"], "identity")
            self.assertEqual(request.headers["user-agent"], "agent-factory-public-code-fetch/1")
            return httpx.Response(200, content=b"synthetic-public-code", headers={"set-cookie": "secret="+PRIVATE})
        with patch.dict("os.environ", {"NETRC": "/nonexistent", "SSL_CERT_FILE": "/nonexistent", "HTTPS_PROXY": "http://invalid.example:9"}):
            result = await fetch.fetch_public_code(transport=httpx.MockTransport(handler))
        self.assertEqual([str(r.url) for r in requests], list(fetch.SOURCE_URLS))
        self.assertEqual(len(result), 2)
        self.assertTrue(all(r.evidence_mode == "controlled-fixture" and r.http_status == 200 for r in result))
        self.assertEqual(result[0].content, b"synthetic-public-code")
        self.assertEqual(len(result[0].sha256), 64)
        self.assertNotIn(PRIVATE, json.dumps([r.metadata for r in result]))

    async def test_destination_hook_rejects_all_nonexact_requests_before_transport(self):
        seen = []
        async with fetch._client(timeout=1, transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200))) as client:
            for method, url in (("POST", fetch.SOURCE_URLS[0]), ("GET", "http://raw.githubusercontent.com/x"),
                                ("GET", fetch.SOURCE_URLS[0]+"?secret="+PRIVATE), ("GET", fetch.SOURCE_URLS[0]+"#fragment"),
                                ("GET", "https://user:secret@raw.githubusercontent.com/x"), ("GET", "https://example.com/"),
                                ("GET", fetch.SOURCE_URLS[0].replace(fetch.COMMIT, "main"))):
                with self.assertRaises(fetch.PublicCodeFetchError) as caught:
                    await client.request(method, url)
                self.assertEqual(caught.exception.code, "DESTINATION_DENIED")
                self.assertNotIn(PRIVATE, str(caught.exception))
        self.assertEqual(seen, [])

    async def test_redirect_status_proxy_failure_no_retries_or_second_source(self):
        for status, code in ((302, "REDIRECT_DENIED"), (403, "HTTP_STATUS"), (429, "HTTP_STATUS"), (500, "HTTP_STATUS")):
            with self.subTest(status=status):
                calls = []
                def handler(request):
                    calls.append(request)
                    return httpx.Response(status, headers={"location": "https://example.com/"+PRIVATE}, content=PRIVATE.encode())
                with self.assertRaises(fetch.PublicCodeFetchError) as caught:
                    await fetch.fetch_public_code(transport=httpx.MockTransport(handler))
                self.assertEqual((caught.exception.code, caught.exception.http_status), (code, status))
                self.assertEqual(len(calls), 1)
                self.assertNotIn(PRIVATE, str(caught.exception))
        calls = []
        def denied(request):
            calls.append(request)
            raise httpx.ProxyError(PRIVATE)
        with self.assertRaises(fetch.PublicCodeFetchError) as caught:
            await fetch.fetch_public_code(transport=httpx.MockTransport(denied))
        self.assertEqual(caught.exception.code, "PROXY")
        self.assertEqual(len(calls), 1)
        self.assertNotIn(PRIVATE, str(caught.exception))

    async def test_stream_file_and_aggregate_bounds_close_response(self):
        for file_limit, total_limit, chunks in ((4, 8, (b"123", b"45")), (5, 6, (b"1234",))):
            with self.subTest(file_limit=file_limit):
                streams = []
                def handler(request):
                    stream = Chunks(*chunks)
                    streams.append(stream)
                    return httpx.Response(200, stream=stream)
                with patch.object(fetch, "MAX_FILE_BYTES", file_limit), patch.object(fetch, "MAX_TOTAL_BYTES", total_limit):
                    with self.assertRaises(fetch.PublicCodeFetchError) as caught:
                        await fetch.fetch_public_code(transport=httpx.MockTransport(handler))
                self.assertEqual(caught.exception.code, "BODY_LIMIT")
                self.assertTrue(all(s.closed for s in streams))
                self.assertLessEqual(len(streams), 2)

    async def test_nonidentity_encoding_and_wall_timeout_fail_closed(self):
        with self.assertRaises(fetch.PublicCodeFetchError) as caught:
            await fetch.fetch_public_code(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-encoding": "br"}, stream=Chunks(b"synthetic"))))
        self.assertEqual(caught.exception.code, "BODY_ENCODING")
        calls = []
        async def stalled(request):
            calls.append(request)
            await asyncio.sleep(1)
            return httpx.Response(200)
        with self.assertRaises(fetch.PublicCodeFetchError) as caught:
            await fetch.fetch_public_code(transport=httpx.MockTransport(stalled), timeout=.01)
        self.assertEqual(caught.exception.code, "TIMEOUT")
        self.assertEqual(len(calls), 1)

    async def test_invalid_transport_timeout_and_ca_never_fallback(self):
        class OtherMock(httpx.MockTransport):
            pass
        for timeout in (0, 21, float("nan"), True):
            with self.assertRaises(fetch.PublicCodeFetchError) as caught:
                await fetch.fetch_public_code(timeout=timeout)
            self.assertEqual(caught.exception.code, "CONFIG_INVALID")
        with self.assertRaises(fetch.PublicCodeFetchError):
            await fetch.fetch_public_code(transport=OtherMock(lambda r: httpx.Response(200)))
        with patch("httpx.AsyncClient", side_effect=ssl.SSLError(PRIVATE)) as client:
            with self.assertRaises(fetch.PublicCodeFetchError) as caught:
                await fetch.fetch_public_code()
            self.assertNotIn(PRIVATE, str(caught.exception))
            client.assert_called_once()
            self.assertTrue(client.call_args.kwargs["verify"])
            self.assertTrue(client.call_args.kwargs["trust_env"])
            self.assertFalse(client.call_args.kwargs["follow_redirects"])
            self.assertIsNone(client.call_args.kwargs["auth"])

    async def test_snapshot_wrapper_checks_pinned_hash_and_keeps_fixture_provenance(self):
        from test_public_code_knowledge import snapshot  # type: ignore[reportMissingImports]
        expected = snapshot()
        files = {row["rawUrl"]: row["content"] for row in expected["sources"]}
        seen = []
        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(200, content=files[str(request.url)])
        actual = await fetch.fetch_snapshot(transport=httpx.MockTransport(handler))
        self.assertEqual(actual, expected)
        self.assertEqual(seen, list(fetch.SOURCE_URLS))
        with self.assertRaises(fetch.PublicCodeFetchError) as caught:
            await fetch.fetch_snapshot(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=PRIVATE.encode())))
        self.assertEqual(caught.exception.code, "SNAPSHOT_INVALID")
        self.assertNotIn(PRIVATE, str(caught.exception))

    async def test_native_client_verifies_tls_and_has_zero_transport_retries_without_dispatch(self):
        with patch.dict("os.environ", {}, clear=True):
            async with fetch._client(timeout=20, transport=None) as client:
                assert isinstance(client._transport, httpx.AsyncHTTPTransport)
                pool = client._transport._pool
                self.assertEqual(pool._retries, 0)
                assert pool._ssl_context is not None
                self.assertEqual(pool._ssl_context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(pool._ssl_context.check_hostname)
                self.assertIsNone(client._auth)
                self.assertFalse(client.follow_redirects)
