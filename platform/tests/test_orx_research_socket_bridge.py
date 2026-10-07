"""Loopback/AF_UNIX-only bridge tests; no model endpoint or container."""
import asyncio
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location('orx_bridge_test', Path(__file__).resolve().parents[2] / 'scripts/orx_research_socket_bridge.py')
assert _spec and _spec.loader
subject = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(subject)


class OrxBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_loopback_http_bytes_reach_only_selected_unix_socket(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'broker.sock')
            seen = []
            async def upstream(reader, writer):
                seen.append(await reader.readuntil(b'\r\n\r\n'))
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK')
                await writer.drain(); writer.close()
            unix = await asyncio.start_unix_server(upstream, path)
            gate = asyncio.Semaphore(1)
            tcp = await asyncio.start_server(lambda r, w: subject.relay(r, w,
                lambda: asyncio.open_unix_connection(path), gate), '127.0.0.1', 0)
            try:
                reader, writer = await asyncio.open_connection('127.0.0.1', tcp.sockets[0].getsockname()[1])
                writer.write(b'GET /mcp HTTP/1.1\r\nHost: local\r\n\r\n'); await writer.drain(); writer.write_eof()
                data = await asyncio.wait_for(reader.read(), 3)
                self.assertTrue(data.endswith(b'OK'))
                self.assertEqual(len(seen), 1)
                writer.close(); await writer.wait_closed()
            finally:
                tcp.close(); unix.close(); await tcp.wait_closed(); await unix.wait_closed()

    async def test_full_gate_refuses_before_connecting(self):
        from unittest.mock import AsyncMock, Mock
        gate = asyncio.Semaphore(0)
        writer, connect = Mock(), AsyncMock()
        await subject.relay(Mock(), writer, connect, gate)
        writer.close.assert_called_once()
        connect.assert_not_awaited()

    async def test_byte_limit_closes_connection(self):
        from unittest.mock import AsyncMock, Mock
        reader = Mock(read=AsyncMock(return_value=b'oversized'))
        other = Mock(read=AsyncMock(return_value=b''))
        writer, remote = Mock(), Mock()
        writer.can_write_eof.return_value = remote.can_write_eof.return_value = False
        with patch.object(subject, 'MAX_BYTES', 2):
            await subject.relay(reader, writer, AsyncMock(return_value=(other, remote)), asyncio.Semaphore(1))
        remote.write.assert_not_called()
        writer.close.assert_called_once(); remote.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
