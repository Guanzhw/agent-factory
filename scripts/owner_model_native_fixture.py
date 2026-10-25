"""Offline native-model acceptance configuration and container-local broker bridge.

No application controller or provider credential enters the synthetic runtime.
"""
import asyncio
import json
import re
import sys

MAX_BYTES = 16 * 1024**2
BUILTINS = ('bash', 'edit', 'write', 'read', 'glob', 'grep', 'list', 'task', 'skill', 'lsp',
            'webfetch', 'websearch', 'codesearch', 'question', 'todowrite', 'todoread',
            'external_directory', 'doom_loop', 'apply_patch', 'multiedit', 'batch')
LOCAL_TOOLS = ('bash', 'edit', 'write', 'read', 'glob', 'grep', 'list', 'apply_patch', 'multiedit')
PERMISSIONS = {'*': 'deny', **{name: 'deny' for name in BUILTINS}, **{name: 'allow' for name in LOCAL_TOOLS}}


def require(value):
    if not value:
        raise ValueError('NATIVE_MODEL_FIXTURE_INVALID')


def opencode_config(capability, max_output_tokens=512):
    require(type(max_output_tokens) is int and 1 <= max_output_tokens <= 4096)
    require(type(capability) is str and re.fullmatch('[A-Za-z0-9_-]{24,128}', capability) is not None)
    # The pinned harness translates legacy tools into permissions before merging.
    # Repeating those keys can move '*' behind the specific allow rules and
    # disable every tool. Use the native permission contract only.
    # The pinned harness emits its stable user-message request ID for opencode*
    # providers. Use a distinct local provider ID, with the same compatible SDK
    # and loopback broker; no built-in Go auth, plugin or extra provider is used.
    agent = {'model': 'opencode-factory/owner-model', 'permission': PERMISSIONS}
    return {'$schema': 'https://opencode.ai/config.json', 'model': 'opencode-factory/owner-model', 'small_model': 'opencode-factory/owner-model',
        'default_agent': 'factory', 'enabled_providers': ['opencode-factory'], 'autoupdate': False, 'share': 'disabled',
        'plugin': [], 'lsp': False, 'formatter': False, 'permission': PERMISSIONS,
        'agent': {'factory': {**agent, 'mode': 'primary'}, 'build': agent, 'plan': agent,
                  'explore': {'disable': True}, 'general': {'disable': True}, 'title': {'disable': True}},
        'provider': {'opencode-factory': {'npm': '@ai-sdk/openai-compatible', 'name': 'Owner model broker',
            'options': {'baseURL': 'http://127.0.0.1:4801/v1', 'apiKey': capability},
            'models': {'owner-model': {'name': 'Owner selected model', 'limit': {'context': 32768, 'output': max_output_tokens}}}}},
        'mcp': {}}


def environment(capability, max_output_tokens=512):
    return {'PATH': '/trusted:/usr/local/bin:/usr/bin:/bin', 'HOME': '/session/home',
        'XDG_CONFIG_HOME': '/session/xdg/config', 'XDG_DATA_HOME': '/session/xdg/data',
        'XDG_CACHE_HOME': '/session/xdg/cache', 'XDG_STATE_HOME': '/session/xdg/state',
        'OPENCODE_CONFIG_CONTENT': json.dumps(opencode_config(capability, max_output_tokens), separators=(',', ':')),
        **{key: '1' for key in ('OPENCODE_DISABLE_AUTOUPDATE', 'OPENCODE_DISABLE_MODELS_FETCH',
            'OPENCODE_DISABLE_DEFAULT_PLUGINS', 'OPENCODE_DISABLE_LSP_DOWNLOAD', 'OPENCODE_DISABLE_AUTOCOMPACT',
            'OPENCODE_DISABLE_CLAUDE_CODE', 'OPENCODE_DISABLE_EXTERNAL_SKILLS', 'OPENCODE_DISABLE_PROJECT_CONFIG',
            'OPENCODE_CONFIG_PROJECT_DISABLE')}, 'NO_COLOR': '1', 'DO_NOT_TRACK': '1'}


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
    local = await asyncio.start_server(lambda r, w: relay(r, w,
        lambda: getattr(asyncio, 'open_unix_connection')('/session/sockets/broker.sock'), gate),
        '127.0.0.1', 4801)
    async with local:
        await local.serve_forever()


if __name__ == '__main__':
    if sys.argv[1:] != ['--bridge']:
        raise ValueError('NATIVE_MODEL_FIXTURE_ARGUMENTS_INVALID')
    asyncio.run(bridges())
