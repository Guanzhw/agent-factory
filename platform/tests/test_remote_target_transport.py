"""Bounded remote target transport and error disclosure (no providers)."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
import httpx

from agent_factory.remote_handoff import HandoffTarget, TrustedHandoffClient


class _Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks, self.reads, self.closed = chunks, 0, False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


class RemoteTargetTransportTests(unittest.IsolatedAsyncioTestCase):
    def client(self):
        client = TrustedHandoffClient.__new__(TrustedHandoffClient)
        client.store = SimpleNamespace(settings=SimpleNamespace(experiment_output_bytes=32))
        return client

    def target(self, response, requests=None):
        async def handler(request):
            if requests is not None:
                requests.append(request)
            return response
        return HandoffTarget("fixture", "origin", "http://receiver.invalid", {"alice": "bob"},
                             lambda _: {"Authorization": "Bearer synthetic-test-only"},
                             transport=httpx.MockTransport(handler))

    def test_http_is_loopback_or_explicit_test_transport_only(self):
        options = {"reference": "fixture", "origin_ref": "origin", "identity_map": {"alice": "bob"},
                   "headers": lambda _: {}}
        for url in ("http://127.0.0.1:3456", "http://[::1]:3456", "http://localhost:3456", "https://receiver.example"):
            HandoffTarget(base_url=url, **options)
        for url in ("http://receiver.example", "http://192.0.2.1", "http://127.0.0.1.example", "http://user:secret@localhost"):
            with self.assertRaises(ValueError):
                HandoffTarget(base_url=url, **options)

    async def test_only_fixed_public_codes_cross_error_boundary(self):
        private = "fixture-private-provider-handle"
        for code, expected in (("REMOTE_BINDING_REQUIRED", "REMOTE_BINDING_REQUIRED: "),
                               (private, ""), (None, "")):
            payload = json.dumps({"code": code, "message": private, "detail": private}).encode()
            stream = _Chunks([payload])
            target = self.target(httpx.Response(409, stream=stream))
            with self.assertRaises(HTTPException) as error:
                await self.client()._request("alice", target, "POST", "/prepare")
            self.assertEqual(error.exception.detail, expected + "Trusted receiver rejected the operation")
            self.assertNotIn(private, error.exception.detail)
            self.assertTrue(stream.closed)

    async def test_redirect_never_forwards_credential_or_body(self):
        requests, stream = [], _Chunks([b"private location"])
        target = self.target(httpx.Response(302, headers={"Location": "https://other.example"}, stream=stream), requests)
        with self.assertRaises(HTTPException) as error:
            await self.client()._request("alice", target, "GET", "/receipt")
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].headers["accept-encoding"], "identity")
        self.assertTrue(stream.closed)

    async def test_advertised_oversize_is_rejected_before_reading(self):
        for status, size in ((200, 2 * 1024 * 1024 + 1), (400, 16385)):
            stream = _Chunks([b"unused"])
            target = self.target(httpx.Response(status, headers={"Content-Length": str(size)}, stream=stream))
            with self.assertRaises(HTTPException) as error:
                await self.client()._request("alice", target, "GET", "/receipt")
            self.assertEqual(error.exception.status_code, 502)
            self.assertEqual(stream.reads, 0)
            self.assertTrue(stream.closed)

    async def test_chunked_oversize_closes_without_reading_remaining_chunks(self):
        stream = _Chunks([b"a" * 16, b"b" * 17, b"never read"])
        target = self.target(httpx.Response(200, stream=stream))
        with self.assertRaises(HTTPException) as error:
            await self.client()._request("alice", target, "GET", "/artifact", binary=True)
        self.assertEqual(error.exception.status_code, 502)
        self.assertEqual(stream.reads, 2)
        self.assertTrue(stream.closed)

    async def test_bounded_binary_preserves_hash_and_bytes(self):
        stream = _Chunks([b"abc", b"def"])
        target = self.target(httpx.Response(200, headers={"X-Content-SHA256": "a" * 64}, stream=stream))
        result = await self.client()._request("alice", target, "GET", "/artifact", binary=True)
        self.assertEqual(result, {"content": b"abcdef", "sha256": "a" * 64})
        self.assertTrue(stream.closed)

    async def test_compressed_peer_body_is_rejected_without_decompression(self):
        stream = _Chunks([b"compressed fixture"])
        target = self.target(httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=stream))
        with self.assertRaises(HTTPException):
            await self.client()._request("alice", target, "GET", "/receipt")
        self.assertEqual(stream.reads, 0)
        self.assertTrue(stream.closed)

    async def test_actual_loopback_does_not_use_ambient_proxy(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                raw = b'{"fixture":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        target = HandoffTarget("fixture", "origin", f"http://127.0.0.1:{server.server_port}",
                               {"alice": "bob"}, lambda _: {})
        try:
            with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "ALL_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}):
                result = await self.client()._request("alice", target, "GET", "/receipt")
            self.assertEqual(result, {"fixture": True})
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
