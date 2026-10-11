"""Application interface v1 HTTP client; caller owns authentication and transport.

Each write is sent once. The supplied HTTP client must also have automatic
write retries disabled. Transport failure leaves the original intent unknown;
call request/query or the command receipt endpoint, never blindly start again.
"""
from typing import Any, Mapping
from urllib.parse import quote
import re

import httpx

from .application_interface import ApplicationStart


def _pointer(value):
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', value) is None or '..' in value:
        raise ValueError('APPLICATION_POINTER_INVALID')
    return quote(value, safe='')


class ApplicationClient:
    def __init__(self, http: httpx.AsyncClient, *, owner_id: str):
        if type(owner_id) is not str or not 1 <= len(owner_id) <= 200 or not owner_id.isprintable():
            raise ValueError('APPLICATION_OWNER_REQUIRED')
        self._http, self._owner = http, owner_id

    async def _request(self, method, path, body=None, params=None):
        response = await self._http.request(method, '/api/factory' + path, json=body, params=params,
            headers={'X-Factory-Expected-Owner': self._owner})
        response.raise_for_status()
        return response

    async def inputs(self, application_id: str) -> dict[str, Any]:
        response = await self._request('GET', '/applications')
        definitions = [item for item in response.json() if item['id'] == application_id]
        return {'interfaceVersion': 1, 'definitions': definitions}

    async def resources(self) -> dict[str, Any]:
        materials = await self._request('GET', '/materials')
        connections = await self._request('GET', '/connections')
        return {'interfaceVersion': 1, 'materials': materials.json(), 'connections': connections.json()}

    async def start(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = ApplicationStart.model_validate(dict(request)).model_dump(exclude_none=True)
        return (await self._request('POST', '/application-interface/v1/starts', body)).json()

    async def request(self, request_id: str) -> dict[str, Any]:
        return (await self._request('GET', '/application-interface/v1/starts/' + _pointer(request_id))).json()

    async def query(self, task_id: str) -> dict[str, Any]:
        return (await self._request('GET', '/jobs/' + _pointer(task_id))).json()

    async def cancel(self, task_id: str, command_id: str) -> dict[str, Any]:
        _pointer(command_id)
        if not 8 <= len(command_id) <= 100:
            raise ValueError('APPLICATION_COMMAND_ID_INVALID')
        body = {'commandId': command_id, 'action': 'cancel'}
        return (await self._request('POST', '/jobs/' + _pointer(task_id) + '/commands', body)).json()

    async def events(self, task_id: str, cursor: str | None = None) -> dict[str, Any]:
        params = {'cursor': cursor} if cursor is not None else None
        return (await self._request('GET', '/jobs/' + _pointer(task_id) + '/events', params=params)).json()

    async def artifacts(self, task_id: str) -> list[dict[str, Any]]:
        return (await self.query(task_id))['artifacts']

    async def artifact(self, task_id: str, artifact_id: str) -> bytes:
        import hashlib
        response = await self._request('GET', '/jobs/' + _pointer(task_id) + '/artifacts/' + _pointer(artifact_id))
        expected = response.headers.get('X-Content-SHA256')
        if expected is None or hashlib.sha256(response.content).hexdigest() != expected:
            raise ValueError('APPLICATION_ARTIFACT_INTEGRITY')
        return response.content
