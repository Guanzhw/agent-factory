#!/usr/local/bin/python3
"""Container-private bounded byte bridges; no external TCP listener or model API."""
import asyncio
import os
from pathlib import Path
import sys

MAX_BYTES = 16 * 1024**2


async def relay(reader, writer, connect, gate):
    if gate.locked():
        writer.close()
        return
    async with gate:
        remote = None
        try:
            async with asyncio.timeout(300):
                upstream, remote = await connect()
                async def copy(source, destination):
                    total = 0
                    while chunk := await source.read(65536):
                        total += len(chunk)
                        if total > MAX_BYTES:
                            raise ValueError('BRIDGE_LIMIT')
                        destination.write(chunk)
                        await destination.drain()
                    if destination.can_write_eof():
                        destination.write_eof()
                await asyncio.gather(copy(reader, remote), copy(upstream, writer))
        except (OSError, TimeoutError, ValueError, ConnectionError):
            pass
        finally:
            writer.close()
            if remote is not None:
                remote.close()


async def bridges():
    gate = asyncio.Semaphore(16)
    path = Path('/session/sockets/orx.sock')
    if path.exists() or path.is_symlink():
        raise ValueError('ORX_SOCKET_ALREADY_EXISTS')
    local = await asyncio.start_server(lambda r, w: relay(r, w,
        lambda: asyncio.open_unix_connection('/session/sockets/broker.sock'), gate), '127.0.0.1', 4801)
    reverse = await asyncio.start_unix_server(lambda r, w: relay(r, w,
        lambda: asyncio.open_connection('127.0.0.1', 4791), gate), str(path))
    path.chmod(0o600)
    async with local, reverse:
        await asyncio.gather(local.serve_forever(), reverse.serve_forever())


if __name__ == '__main__':
    if sys.argv[1:] == ['--bridge']:
        asyncio.run(bridges())
    else:
        # This same readonly file is mounted as /trusted/opencode, before the
        # real pinned binary on PATH. Every ORX-created serve is gated here.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from entry import opencode_wrapper  # pyright: ignore[reportMissingImports]
        os.umask(0o077)
        opencode_wrapper(sys.argv[1:])
