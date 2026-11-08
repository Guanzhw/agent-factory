"""Observe native streaming admission without buffering the worker's whole run."""
import asyncio

import httpx


async def submit_stream(app, method, path, *, headers, data):
    """Return HTTP acceptance (or the complete rejection); execution stays in Agno's queue."""
    request = httpx.Request(method, 'http://native.agent-factory' + path, headers=headers, data=data)
    body = request.read()
    response = asyncio.get_running_loop().create_future()
    disconnected = asyncio.Event()
    sent = False
    status, response_headers, chunks = 500, [], []

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        await disconnected.wait()
        return {'type': 'http.disconnect'}

    async def send(message):
        nonlocal status, response_headers
        if message['type'] == 'http.response.start':
            status, response_headers = message['status'], message['headers']
            if status < 400:
                response.set_result(httpx.Response(status, headers=response_headers, request=request))
        elif message['type'] == 'http.response.body' and status >= 400:
            chunks.append(message.get('body', b''))
            if not message.get('more_body', False):
                response.set_result(httpx.Response(status, headers=response_headers,
                    content=b''.join(chunks), request=request))

    async def invoke():
        try:
            await app({'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
                'http_version': '1.1', 'method': method, 'scheme': 'http',
                'path': request.url.path, 'raw_path': request.url.raw_path,
                'query_string': request.url.query, 'root_path': '',
                'headers': request.headers.raw, 'server': ('native.agent-factory', 80),
                'client': ('127.0.0.1', 0)}, receive, send)
            if not response.done():
                response.set_exception(RuntimeError('Native streaming admission returned no response'))
        except BaseException as error:
            if not response.done():
                response.set_exception(error)
            raise

    task = asyncio.create_task(invoke())
    try:
        return await response
    finally:
        disconnected.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
