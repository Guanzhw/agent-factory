"""Synthetic ASGI/provider transports only: no sockets or credential discovery."""
import asyncio
import json
import unittest

import httpx

from agent_factory.opencode_go import USER_AGENT
from agent_factory.orx_research_broker import MODEL, ORXResearchBroker
from agent_factory.usage_ledger import UsageEvidence

CAP = "fixture_capability_" + "x" * 32
SESSION = "fixture_stable_session"


def response_body():
    return {"id": "fixture-completion", "model": MODEL, "choices": [{"index": 0,
        "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
        "tool_calls": [{"id": "call-fixture", "type": "function", "function": {
            "name": "read_fixture", "arguments": '{"name":"public"}'}}]}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19}}


def stream_bytes(*, repeat=None, done=True):
    value = response_body()
    tool = value["choices"][0]["message"]["tool_calls"][0]
    events = [{"model": MODEL, "choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, **tool}]}, "finish_reason": "tool_calls"}]},
        {"model": MODEL, "choices": [], "usage": value["usage"]}]
    if repeat is not None:
        events.append({"model": MODEL, "choices": [], "usage": repeat})
    return b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events) + (
        b"data: [DONE]\n\n" if done else b"")


class Fixture:
    def __init__(self, handler=None, **options):
        self.sent = []
        self.reserved = []
        self.settled = []
        self.held = []
        self.credential_calls = 0
        self.allowed = True
        self.authority_checks = 0

        async def authority():
            self.authority_checks += 1
            return self.allowed

        async def reserve(ordinal, input_bound, output_cap, body):
            ticket = {"ordinal": ordinal}
            self.reserved.append((ticket, input_bound, output_cap, body))
            return ticket

        async def settle(ticket, usage):
            self.settled.append((ticket, usage))

        async def hold(ticket, reason):
            self.held.append((ticket, reason))

        def credential():
            self.credential_calls += 1
            return "synthetic-provider-secret"

        async def transport(request):
            self.sent.append(request)
            if handler:
                return await handler(request)
            return httpx.Response(200, json=response_body())

        self.broker = ORXResearchBroker(capability=CAP, session_id=SESSION, credential=credential,
            current_authority=authority, reserve=reserve, settle=settle, hold=hold,
            transport=httpx.MockTransport(transport), **options)

    async def request(self, body=None, **kwargs):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.broker.app),
                                     base_url="http://fixture") as client:
            return await client.post("/v1/chat/completions", headers={"Authorization": "Bearer " + CAP},
                json=body if body is not None else {"model": MODEL,
                    "messages": [{"role": "user", "content": "synthetic public fixture"}]}, **kwargs)


class ResearchBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_response_preserved_and_authoritative_usage_once(self):
        f = Fixture()
        response = await f.request()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), response_body())
        self.assertEqual(f.settled[0][1], UsageEvidence(12, 7, "registered-native-provider-usage"))
        self.assertEqual(len(f.settled), 1)
        self.assertEqual(f.held, [])
        self.assertEqual(f.authority_checks, 4)
        outgoing = f.sent[0]
        self.assertEqual(str(outgoing.url), "https://opencode.ai/zen/go/v1/chat/completions")
        self.assertEqual(outgoing.headers["user-agent"], USER_AGENT)
        self.assertEqual(outgoing.headers["x-opencode-session"], SESSION)
        self.assertNotIn("synthetic-provider-secret", response.text)
        self.assertNotIn(CAP, str(outgoing.headers))
        self.assertEqual(f.reserved[0][3], json.loads(outgoing.content))

    async def test_titles_and_probes_share_three_attempt_budget(self):
        f = Fixture()
        for content in ("title", "probe", "research"):
            self.assertEqual((await f.request({"model": MODEL,
                "messages": [{"role": "user", "content": content}]})).status_code, 200)
        self.assertEqual((await f.request()).json()["error"]["code"], "REQUEST_LIMIT")
        self.assertEqual(len(f.sent), 3)
        self.assertEqual(f.credential_calls, 3)

    async def test_stream_identical_usage_preserved_without_double_settlement(self):
        raw = stream_bytes(repeat=response_body()["usage"])
        async def handler(_):
            return httpx.Response(200, content=raw)
        f = Fixture(handler)
        response = await f.request({"model": MODEL, "messages": [{"role": "user", "content": "public"}], "stream": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, raw)
        self.assertEqual(len(f.settled), 1)
        self.assertEqual(json.loads(f.sent[0].content)["stream_options"], {"include_usage": True})

    async def test_conflicting_usage_and_missing_done_stop_hold_without_retry(self):
        for raw in (stream_bytes(repeat={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}),
                    stream_bytes(done=False)):
            async def handler(_, raw=raw):
                return httpx.Response(200, content=raw)
            f = Fixture(handler)
            response = await f.request({"model": MODEL, "messages": [{}], "stream": True})
            self.assertEqual(response.status_code, 409)
            self.assertNotIn("read_fixture", response.text)
            self.assertEqual(f.settled, [])
            self.assertEqual(len(f.held), 1)
            self.assertEqual((await f.request()).json()["error"]["code"], "STOPPED")
            self.assertEqual(len(f.sent), 1)

    async def test_partial_transport_after_done_does_not_settle(self):
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield stream_bytes()
                raise httpx.ReadError("synthetic-sensitive-provider-message")
        async def handler(_):
            return httpx.Response(200, stream=Broken())
        f = Fixture(handler)
        response = await f.request({"model": MODEL, "messages": [{}], "stream": True})
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("sensitive", response.text)
        self.assertEqual(f.settled, [])
        self.assertEqual(len(f.held), 1)

    async def test_auth_quota_http_errors_hold_and_stop(self):
        for status, code in ((401, "AUTH"), (403, "AUTH"), (402, "QUOTA"), (429, "QUOTA"), (500, "HTTP_REJECTED")):
            async def handler(_, status=status):
                return httpx.Response(status, text="sensitive provider body")
            f = Fixture(handler)
            self.assertEqual((await f.request()).json()["error"]["code"], code)
            self.assertEqual((await f.request()).json()["error"]["code"], "STOPPED")
            self.assertEqual(len(f.sent), 1)
            self.assertEqual(f.held[0][1], code)

    async def test_usage_unknown_and_wrong_model_never_settle(self):
        for change in ({"usage": None}, {"model": "gpt-6-luna"}, {"usage": {
                "prompt_tokens": True, "completion_tokens": 7, "total_tokens": 8}}):
            async def handler(_, change=change):
                return httpx.Response(200, json={**response_body(), **change})
            f = Fixture(handler)
            self.assertEqual((await f.request()).status_code, 409)
            self.assertEqual(f.settled, [])
            self.assertEqual(len(f.held), 1)

    async def test_authority_denial_precedes_credentials(self):
        f = Fixture()
        f.allowed = False
        self.assertEqual((await f.request()).json()["error"]["code"], "AUTHORITY_DENIED")
        self.assertEqual(f.credential_calls, 0)
        self.assertEqual(f.sent, [])

    async def test_invalid_request_never_accesses_provider(self):
        f = Fixture()
        for body in ({"model": "gpt-6-luna", "messages": [{}]},
                     {"model": MODEL, "messages": [{}], "max_tokens": 513},
                     {"model": MODEL, "messages": [{}], "max_tokens": True},
                     {"model": MODEL, "messages": [{}], "n": True},
                     {"model": MODEL, "messages": [{}], "provider": "other"}):
            self.assertEqual((await f.request(body)).status_code, 409)
        self.assertEqual(f.sent, [])
        self.assertEqual(f.reserved, [])

    async def test_capability_duplicate_header_and_endpoint_denial(self):
        f = Fixture()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f.broker), base_url="http://fixture") as c:
            self.assertEqual((await c.post("/v1/chat/completions", json={})).status_code, 401)
            self.assertEqual((await c.post("/v1/chat/completions", headers=[("authorization", "Bearer " + CAP)] * 2,
                                          json={})).status_code, 401)
            self.assertEqual((await c.get("/v1/models", headers={"authorization": "Bearer " + CAP})).status_code, 409)
        self.assertEqual(f.sent, [])

    async def test_concurrent_second_request_is_not_dispatched(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def handler(_):
            entered.set()
            await release.wait()
            return httpx.Response(200, json=response_body())
        f = Fixture(handler)
        first = asyncio.create_task(f.request())
        await entered.wait()
        try:
            self.assertEqual((await f.request()).json()["error"]["code"], "INFLIGHT")
        finally:
            release.set()
        self.assertEqual((await first).status_code, 200)
        self.assertEqual(len(f.sent), 1)

    async def test_accounting_exception_is_sanitized_and_stops(self):
        f = Fixture()
        async def broken(*_):
            raise RuntimeError("private ledger details")
        f.broker._settle = broken
        response = await f.request()
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("private", response.text)
        self.assertEqual(len(f.held), 1)
        self.assertEqual((await f.request()).json()["error"]["code"], "STOPPED")

    async def test_cancellation_holds_original_attempt_without_replay(self):
        entered = asyncio.Event()
        async def handler(_):
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")
        f = Fixture(handler)
        running = asyncio.create_task(f.request())
        await entered.wait()
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertEqual(len(f.held), 1)
        self.assertEqual(f.settled, [])
        self.assertEqual((await f.request()).json()["error"]["code"], "STOPPED")
        self.assertEqual(len(f.sent), 1)

    async def test_revoked_after_reservation_cannot_read_credential(self):
        f = Fixture()
        original = f.broker._reserve
        async def reserve(*args):
            ticket = await original(*args)
            f.allowed = False
            return ticket
        f.broker._reserve = reserve
        self.assertEqual((await f.request()).json()["error"]["code"], "AUTHORITY_DENIED")
        self.assertEqual(f.credential_calls, 0)
        self.assertEqual(len(f.held), 1)
        self.assertEqual(f.sent, [])

    async def test_input_output_byte_bounds_and_duplicate_json(self):
        f = Fixture(max_input_bytes=100)
        self.assertEqual((await f.request({"model": MODEL, "messages": [{"content": "x" * 1000}]})).status_code, 409)
        self.assertEqual(f.sent, [])
        f = Fixture(max_output_bytes=10)
        self.assertEqual((await f.request()).json()["error"]["code"], "OUTPUT_BOUND")
        self.assertEqual(len(f.held), 1)
        f = Fixture()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=f.broker), base_url="http://fixture") as client:
            response = await client.post("/v1/chat/completions", headers={"authorization": "Bearer " + CAP},
                content=b'{"model":"deepseek-flash","model":"gpt-6-luna","messages":[{}]}')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(f.credential_calls, 0)

    async def test_early_usage_is_unknown_but_over_cap_usage_is_settled(self):
        early = b'data: {"model":"deepseek-flash","choices":[],"usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19}}\n\n'
        async def handler(_):
            return httpx.Response(200, content=early + stream_bytes())
        f = Fixture(handler)
        self.assertEqual((await f.request({"model": MODEL, "messages": [{}], "stream": True})).status_code, 409)
        self.assertEqual(f.settled, [])
        f = Fixture(max_output_tokens=6)
        self.assertEqual((await f.request()).json()["error"]["code"], "USAGE_BOUND")
        self.assertEqual(len(f.settled), 1)
        self.assertEqual(f.settled[0][1], UsageEvidence(12, 7, "registered-native-provider-usage"))
        self.assertEqual(f.held, [])

    async def test_stream_revocation_before_next_chunk_holds_without_tools(self):
        class RevokedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                raw = stream_bytes()
                split = raw.index(b"\n\n") + 2
                yield raw[:split]
                f.allowed = False
                yield raw[split:]
        async def handler(_):
            return httpx.Response(200, stream=RevokedStream())
        f = Fixture(handler)
        response = await f.request({"model": MODEL, "messages": [{}], "stream": True})
        self.assertEqual(response.json()["error"]["code"], "AUTHORITY_DENIED")
        self.assertNotIn("read_fixture", response.text)
        self.assertEqual(f.settled, [])
        self.assertEqual(len(f.held), 1)
        self.assertEqual((await f.request()).json()["error"]["code"], "STOPPED")
        self.assertEqual(len(f.sent), 1)

    async def test_verified_eof_revocation_preserves_settlement(self):
        for boundary in ("eof", "settle"):
            with self.subTest(boundary=boundary):
                class EndStream(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        yield stream_bytes()
                        if boundary == "eof":
                            f.allowed = False

                async def handler(_):
                    return httpx.Response(200, stream=EndStream())
                f = Fixture(handler)
                original_settle = f.broker._settle
                async def settle(ticket, usage):
                    await original_settle(ticket, usage)
                    if boundary == "settle":
                        f.allowed = False
                f.broker._settle = settle
                request = {"model": MODEL, "messages": [{}], "stream": True}
                response = await f.request(request)
                self.assertEqual(response.json()["error"]["code"], "AUTHORITY_DENIED")
                self.assertNotIn("read_fixture", response.text)
                self.assertEqual(len(f.settled), 1)
                self.assertEqual(f.held, [])
                self.assertEqual((await f.request()).json()["error"]["code"], "STOPPED")
                self.assertEqual(len(f.sent), 1)

    async def test_authoritative_input_overrun_is_settled_once_without_delivery(self):
        async def handler(_):
            payload = response_body()
            payload["usage"] = {"prompt_tokens": 100000, "completion_tokens": 7, "total_tokens": 100007}
            return httpx.Response(200, json=payload)
        f = Fixture(handler)
        response = await f.request()
        self.assertEqual(response.json()["error"]["code"], "USAGE_BOUND")
        self.assertNotIn("read_fixture", response.text)
        self.assertEqual(f.settled, [(f.reserved[0][0], UsageEvidence(100000, 7, "registered-native-provider-usage"))])
        self.assertEqual(f.held, [])
        self.assertEqual((await f.request()).json()["error"]["code"], "STOPPED")
        self.assertEqual(len(f.sent), 1)

    async def test_cancel_after_verified_settlement_never_delivers_or_holds_again(self):
        f = Fixture()
        original_authority = f.broker._authority
        async def authority():
            if f.settled:
                raise asyncio.CancelledError()
            return await original_authority()
        f.broker._authority = authority
        with self.assertRaises(asyncio.CancelledError):
            await f.request()
        self.assertEqual(len(f.settled), 1)
        self.assertEqual(f.held, [])
        self.assertEqual((await f.request()).json()["error"]["code"], "STOPPED")
        self.assertEqual(len(f.sent), 1)

    async def test_operator_attempt_bound_is_explicit_and_default_stays_three(self):
        self.assertEqual(Fixture().broker._max_requests, 3)
        for invalid in (0, 17, True, 3.0):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                Fixture(max_requests=invalid)
        f = Fixture(max_requests=16)
        for ordinal in range(1, 17):
            self.assertEqual((await f.request()).status_code, 200)
            self.assertEqual(f.reserved[-1][0]["ordinal"], ordinal)
        self.assertEqual((await f.request()).json()["error"]["code"], "REQUEST_LIMIT")
        self.assertEqual(len(f.sent), 16)
        self.assertEqual(len(f.settled), 16)

    async def test_safe_diagnostics_distinguish_transport_parse_and_accounting(self):
        async def invalid_json(_):
            return httpx.Response(200, content=b'{private-server-body')
        async def read_error(_):
            raise httpx.ReadError('private-server-body')
        cases = [(Fixture(invalid_json), 'eof', 'parse', 'JSONDecodeError', 'JSON_DECODE'),
                 (Fixture(read_error), 'dispatch', 'transport', 'ReadError', 'TRANSPORT_READ')]
        accounting = Fixture()
        async def broken_settle(*_):
            raise RuntimeError('private-ledger-token')
        accounting.broker._settle = broken_settle
        cases.append((accounting, 'parsed', 'settle', 'RuntimeError', 'UNKNOWN_ERROR'))
        for fixture, phase, operation, error_type, code in cases:
            with self.subTest(phase=phase):
                self.assertEqual((await fixture.request()).status_code, 409)
                diagnostic = fixture.broker.diagnostics[0]
                self.assertEqual((diagnostic['phase'], diagnostic['operation']), (phase, operation))
                self.assertEqual(diagnostic['error']['errorType'], error_type)
                self.assertEqual(diagnostic['error']['rejectionCode'], code)
                self.assertEqual(fixture.broker.stopped_reason, 'UNKNOWN')
                self.assertEqual(len(fixture.held), 1)
                self.assertNotIn('private-', json.dumps(diagnostic))
                self.assertEqual((await fixture.request()).json()['error']['code'], 'STOPPED')
                self.assertEqual(len(fixture.broker.diagnostics), 1)

    async def test_stream_parser_code_and_success_delivery_are_finite_local_facts(self):
        async def missing_done(_):
            return httpx.Response(200, content=stream_bytes(done=False))
        f = Fixture(missing_done)
        await f.request({'model': MODEL, 'messages': [{}], 'stream': True})
        diagnostic = f.broker.diagnostics[0]
        self.assertEqual(diagnostic['phase'], 'eof')
        self.assertEqual(diagnostic['operation'], 'parse')
        self.assertEqual(diagnostic['error']['errorType'], 'ModelProviderError')
        self.assertEqual(diagnostic['error']['rejectionCode'], 'STREAM_MISSING_TERMINAL')
        f = Fixture()
        self.assertEqual((await f.request()).status_code, 200)
        self.assertEqual(f.broker.diagnostics, [{'ordinal': 1, 'phase': 'delivered', 'operation': 'delivery'}])
        copied = f.broker.diagnostics; copied[0]['phase'] = 'arbitrary'
        self.assertEqual(f.broker.diagnostics[0]['phase'], 'delivered')

    async def test_hostile_exception_never_serializes_attributes_or_strings(self):
        class Hostile(RuntimeError):
            def __str__(self):
                raise AssertionError('must not stringify')
            def __getattribute__(self, name):
                if name in {'args', '__cause__', '__context__'}:
                    raise AssertionError('must not read private attribute')
                return super().__getattribute__(name)
        async def handler(_):
            raise Hostile('synthetic-secret')
        f = Fixture(handler)
        self.assertEqual((await f.request()).status_code, 409)
        diagnostic = f.broker.diagnostics[0]
        self.assertEqual(diagnostic['error']['errorType'], 'UnknownError')
        self.assertNotIn('synthetic-secret', json.dumps(diagnostic))
        self.assertEqual(len(f.held), 1)


if __name__ == "__main__":
    unittest.main()
