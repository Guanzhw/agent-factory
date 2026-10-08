"""Public native endpoints cannot bypass Factory's approved envelope."""
import unittest
from unittest.mock import AsyncMock

from agent_factory.main import NativeIngress
from agent_factory.native_bridge import INTERNAL_NATIVE


class NativeIngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_and_websocket_reject_direct_workflow_execution(self):
        for kind in ('http', 'websocket'):
            for path in ('/workflows/example/runs', '/workflows/example/runs/original/continue',
                         '/workflows/ws', '/agents/factory-executor/runs', '/schedules/create'):
                with self.subTest(kind=kind, path=path):
                    app, send = AsyncMock(), AsyncMock()
                    await NativeIngress(app)({'type': kind, 'path': path, 'method': 'POST'}, AsyncMock(), send)
                    app.assert_not_awaited()
                    sent = send.await_args_list[0].args[0]
                    self.assertEqual(sent.get('status') if kind == 'http' else sent.get('code'),
                                     403 if kind == 'http' else 1008)

    async def test_trusted_context_only_opens_internal_call(self):
        app = AsyncMock()
        middleware = NativeIngress(app)
        scope = {'type': 'http', 'path': '/workflows/example/runs', 'method': 'POST',
                 'headers': [(b'internal-native', b'true')]}
        await middleware(scope, AsyncMock(), AsyncMock())
        app.assert_not_awaited()
        token = INTERNAL_NATIVE.set(True)
        try:
            await middleware(scope, AsyncMock(), AsyncMock())
        finally:
            INTERNAL_NATIVE.reset(token)
        app.assert_awaited_once()
