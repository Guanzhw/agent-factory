"""Synthetic routing contracts; no browser process, socket or credential input."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from inference_recovery_browser import fixture_origin, fixture_request  # pyright: ignore[reportMissingImports]


class InferenceBrowserScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_exact_origin_gets_header_and_redirects_are_not_followed(self):
        route = SimpleNamespace(request=SimpleNamespace(url='http://127.0.0.1:3210/api/test',
            headers={'authorization': 'synthetic-stale', 'accept': 'application/json'}),
            fetch=AsyncMock(return_value='synthetic-response'), fulfill=AsyncMock(), abort=AsyncMock())
        await fixture_request(route, fixture_origin('http://127.0.0.1:3210'), {'Authorization': 'synthetic-fixture'})
        route.fetch.assert_awaited_once_with(headers={'accept': 'application/json', 'Authorization': 'synthetic-fixture'},
            max_redirects=0)
        route.fulfill.assert_awaited_once_with(response='synthetic-response')
        route.abort.assert_not_awaited()

    async def test_external_redirect_targets_and_wrong_ports_never_receive_header(self):
        origin = fixture_origin('http://127.0.0.1:3210')
        for url in ('https://example.invalid/', 'http://127.0.0.1:3211/', 'http://localhost:3210/',
                    'http://user:pass@127.0.0.1:3210/', 'http://127.0.0.1:invalid/'):
            route = SimpleNamespace(request=SimpleNamespace(url=url, headers={}),
                fetch=AsyncMock(), fulfill=AsyncMock(), abort=AsyncMock())
            with self.subTest(url=url):
                await fixture_request(route, origin, {'Authorization': 'synthetic-fixture'})
                route.abort.assert_awaited_once()
                route.fetch.assert_not_awaited()
                route.fulfill.assert_not_awaited()
