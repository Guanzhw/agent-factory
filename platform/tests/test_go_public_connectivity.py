import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

_SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'check_go_public_connectivity.py'
spec = importlib.util.spec_from_file_location('go_public_connectivity', _SCRIPT)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class UnreadableBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        raise AssertionError('Response body must not be read')
        yield b''


@unittest.skipUnless(os.name == 'posix', 'Private POSIX evidence required')
class GoPublicConnectivityTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_one_get_no_auth_body_redirect_or_second_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            requests = []
            async def respond(request):
                requests.append(request)
                self.assertTrue((Path(directory) / runner.MARKER).exists())
                self.assertTrue((Path(directory) / 'dispatch-started.json').exists())
                self.assertEqual(str(request.url), runner.URL)
                self.assertEqual(request.method, 'GET')
                self.assertNotIn('authorization', request.headers)
                self.assertNotIn('x-opencode-session', request.headers)
                self.assertEqual(request.headers['user-agent'], runner.USER_AGENT)
                return httpx.Response(302, headers={'location': 'https://private.example/'}, stream=UnreadableBody())
            def client(**kw):
                self.assertEqual(kw, {'timeout': 10})
                return httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False, trust_env=False)
            with patch.object(runner, 'open_go_client', side_effect=client) as factory:
                result = await runner.probe(directory)
                before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(directory).iterdir()}
                again = await runner.probe(directory)
                self.assertEqual(again['execution'], 'inspection-only')
                self.assertEqual(factory.call_count, 1)
            self.assertEqual(len(requests), 1)
            self.assertEqual(result['httpStatus'], 302)
            self.assertNotIn('private', json.dumps(result))
            self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(directory).iterdir()})
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in Path(directory).iterdir()))

    async def test_failure_is_sanitized_persisted_and_never_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            async def fail(request):
                raise httpx.ProxyError('403 Forbidden private-proxy')
            with patch.object(runner, 'open_go_client', side_effect=lambda **kw: httpx.AsyncClient(
                    transport=httpx.MockTransport(fail), trust_env=False)) as factory:
                result = await runner.probe(directory)
                await runner.probe(directory)
            self.assertEqual(factory.call_count, 1)
            self.assertEqual(result['diagnostic']['category'], 'PROXY')
            self.assertNotIn('httpStatus', result)
            self.assertNotIn('private', json.dumps(result))
            self.assertNotIn('403', json.dumps(result))

    async def test_existing_prepared_marker_after_crash_never_dispatches(self):
        with tempfile.TemporaryDirectory() as directory:
            runner.write_private(Path(directory) / runner.MARKER, {'phase': 'PREPARED'})
            with patch.object(runner, 'open_go_client') as factory:
                result = await runner.probe(directory)
                factory.assert_not_called()
            self.assertEqual(result['outcome'], 'UNKNOWN')

    async def test_marker_write_failure_and_nonempty_directory_prevent_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runner, 'write_private', side_effect=OSError('private')), \
                 patch.object(runner, 'open_go_client') as factory:
                with self.assertRaises(OSError):
                    await runner.probe(directory)
                factory.assert_not_called()
            (Path(directory) / 'existing').write_text('synthetic')
            with patch.object(runner, 'open_go_client') as factory:
                with self.assertRaises(ValueError):
                    await runner.probe(directory)
                factory.assert_not_called()

    async def test_cancellation_preserves_attempt_and_no_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            async def cancel(request):
                raise asyncio.CancelledError()
            with patch.object(runner, 'open_go_client', side_effect=lambda **kw: httpx.AsyncClient(
                    transport=httpx.MockTransport(cancel), trust_env=False)) as factory:
                result = await runner.probe(directory)
                await runner.probe(directory)
                self.assertEqual(factory.call_count, 1)
            self.assertEqual(result['diagnostic']['category'], 'CANCELLED')

    async def test_inspection_rejects_injected_private_text_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            runner.write_private(Path(directory) / runner.MARKER, {"phase": "private-credential"})
            with patch.object(runner, 'open_go_client') as factory:
                with self.assertRaisesRegex(ValueError, 'Invalid stored'):
                    await runner.probe(directory)
                factory.assert_not_called()
