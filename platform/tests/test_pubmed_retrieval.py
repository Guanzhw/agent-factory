"""Synthetic public metadata only; all HTTP is exact MockTransport."""
import asyncio
import hashlib
import json
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx

from agent_factory import pubmed_retrieval as module

_REAL_THROTTLE = module._throttle


class Stream(httpx.AsyncByteStream):
    def __init__(self, raw, *, wait=False):
        self.raw, self.wait, self.closed = raw, wait, False

    async def __aiter__(self):
        if self.wait:
            await asyncio.sleep(10)
        yield self.raw

    async def aclose(self):
        self.closed = True


def xml(ids=('123',), abstract='Original public metadata abstract with a short located quotation.'):
    return ('<PubmedArticleSet>' + ''.join('<PubmedArticle><MedlineCitation><PMID>' + identifier +
        '</PMID><Article><ArticleTitle>Test title</ArticleTitle><Abstract><AbstractText>' + abstract +
        '</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle>' for identifier in ids) + '</PubmedArticleSet>').encode()


class PubMedTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.throttle = self.enterContext(patch.object(module, '_throttle', new_callable=AsyncMock))

    async def run_fixture(self, ids=('123',), raw=None, **options):
        calls, streams = [], []
        def handler(request):
            calls.append(request)
            body = json.dumps({'esearchresult': {'idlist': list(ids)}}).encode() if len(calls) == 1 else raw if raw is not None else xml(ids)
            stream = Stream(body)
            streams.append(stream)
            return httpx.Response(200, stream=stream, headers={'Set-Cookie': 'synthetic=do-not-forward'})
        result = await module.retrieve(transport=httpx.MockTransport(handler), **options)
        return result, calls, streams

    async def test_fixed_query_allowlisted_ids_exact_excerpt_hash_and_no_cookie_forward(self):
        result, calls, streams = await self.run_fixture(ids=('123', '456'))
        self.assertEqual(result['evidenceMode'], 'controlled-fixture')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].url.params['term'], 'retrieval augmented generation')
        self.assertEqual(calls[1].url.params['id'], '123,456')
        self.assertTrue(all(r.headers['User-Agent'] == module.USER_AGENT for r in calls))
        self.assertTrue(all('authorization' not in r.headers and 'cookie' not in r.headers for r in calls))
        self.assertTrue(all(s.closed for s in streams))
        self.assertEqual(self.throttle.await_count, 2)
        record = result['sources'][0]
        abstract = 'Original public metadata abstract with a short located quotation.'
        self.assertEqual(record['sha256'], hashlib.sha256(abstract.encode()).hexdigest())
        locator = record['locator']
        self.assertEqual(record['excerpt'], abstract[locator['start']:locator['endExclusive']])
        self.assertLessEqual(len(record['excerpt'].split()), 20)
        self.assertLessEqual(len(record['excerpt']), 160)
        self.assertFalse(record['fullTextAvailable'])
        self.assertEqual(record['licenseStatus'], 'unverified')
        self.assertFalse(result['provenance']['containerIsolation'])
        self.assertEqual(len(result['provenance']['responses']), 2)

    async def test_empty_search_issues_no_fetch_and_absent_abstract_is_explicit(self):
        result, calls, _ = await self.run_fixture(ids=())
        self.assertEqual(result['sources'], [])
        self.assertEqual(len(calls), 1)
        result, _, _ = await self.run_fixture(raw=xml(abstract=''))
        self.assertEqual(result['sources'][0]['textStatus'], 'metadata_only')
        self.assertIsNone(result['sources'][0]['sha256'])

    async def test_invalid_config_refused_before_transport(self):
        handler = AsyncMock()
        invalid: list[dict[str, Any]] = [{'query_id': 'private-query'}, {'limit': True}, {'limit': 4}, {'transport': httpx.AsyncHTTPTransport()}]
        for kwargs in invalid:
            with self.assertRaisesRegex(module.PubMedRetrievalError, '^CONFIG_INVALID$'):
                await module.retrieve(**kwargs)
        handler.assert_not_called()

    async def test_search_and_xml_identity_malformed_entities_and_duplicates_fail_closed(self):
        for ids in (('123', '123'), ('../secret',), ('0',), ('123', '456', '789')):
            with self.subTest(ids=ids), self.assertRaises(module.PubMedRetrievalError):
                await self.run_fixture(ids=ids)
        variants = [(b'<bad>', 'XML_INVALID'), (b'<!DOCTYPE x><PubmedArticleSet/>', 'XML_ENTITY_DENIED'),
                    (b'<!ENTITY x "private"><PubmedArticleSet/>', 'XML_ENTITY_DENIED'),
                    (xml(('456',)), 'SOURCE_ID_MISMATCH'), (xml(('123', '123')), 'SOURCE_ID_MISMATCH'),
                    (b'<PubmedArticleSet/>', 'SOURCE_ID_MISMATCH')]
        for raw, expected in variants:
            with self.subTest(code=expected), self.assertRaises(module.PubMedRetrievalError) as caught:
                await self.run_fixture(raw=raw)
            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn('private', str(caught.exception))

    async def test_status_redirect_body_encoding_and_bounds_do_not_retry(self):
        for status, headers, raw, expected in [(403, {}, b'private', 'HTTP_STATUS'),
            (302, {'Location': 'https://elsewhere.invalid/private'}, b'', 'REDIRECT_DENIED'),
            (200, {'Content-Encoding': 'gzip'}, b'private', 'BODY_ENCODING'),
            (200, {}, b'x' * (module.MAX_SEARCH_BYTES + 1), 'BODY_LIMIT'),
            (200, {}, b'not-json-private', 'JSON_INVALID')]:
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, headers=headers, stream=Stream(raw))
            with self.subTest(expected=expected), self.assertRaises(module.PubMedRetrievalError) as caught:
                await module.retrieve(transport=httpx.MockTransport(handler))
            self.assertEqual(caught.exception.code, expected)
            self.assertNotIn('private', str(caught.exception))
            self.assertEqual(len(calls), 1)

    async def test_cancellation_and_total_deadline_close_response(self):
        for cancel in (True, False):
            stream = Stream(b'', wait=True)
            handler = AsyncMock(return_value=httpx.Response(200, stream=stream))
            with patch.object(module, 'TOTAL_TIMEOUT', 0.05 if not cancel else 25):
                task = asyncio.create_task(module.retrieve(transport=httpx.MockTransport(handler)))
                if cancel:
                    while not handler.call_count:
                        await asyncio.sleep(0)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError): await task
                else:
                    with self.assertRaisesRegex(module.PubMedRetrievalError, '^TIMEOUT$'): await task
            self.assertTrue(stream.closed)
            self.assertEqual(handler.call_count, 1)

    async def test_proxy_failure_is_lossy_and_has_no_direct_fallback(self):
        handler = AsyncMock(side_effect=httpx.ProxyError('private-proxy-details'))
        with self.assertRaisesRegex(module.PubMedRetrievalError, '^PROXY$'):
            await module.retrieve(transport=httpx.MockTransport(handler))
        self.assertEqual(handler.call_count, 1)

    async def test_native_client_configuration_retains_environment_tls_and_no_redirects(self):
        with patch.object(module.httpx, 'AsyncClient', side_effect=OSError('private-env-path')) as constructor:
            with self.assertRaisesRegex(module.PubMedRetrievalError, '^TRANSPORT$'):
                await module.retrieve()
        options = constructor.call_args.kwargs
        self.assertIs(options['trust_env'], True)
        self.assertIs(options['verify'], True)
        self.assertIs(options['follow_redirects'], False)
        self.assertIsNone(options['auth'])
        self.assertIsNone(options['transport'])
        self.assertEqual(options['timeout'], 10)

    async def test_global_rate_limiter_spaces_actual_admission(self):
        with patch.object(module, '_last_dispatch', 0.0):
            await _REAL_THROTTLE()
            first = module._last_dispatch
            await _REAL_THROTTLE()
            self.assertGreaterEqual(module._last_dispatch - first, 0.35)

    async def test_observed_exact_public_doctype_is_removed_without_entity_resolution(self):
        raw = b'<?xml version="1.0"?>\n' + module.PUBLIC_DOCTYPE.encode() + b'\n' + xml()
        result, _, _ = await self.run_fixture(raw=raw)
        self.assertEqual(result['sources'][0]['sourceId'], '123')
        self.assertEqual(result['provenance']['responses'][1]['sha256'], hashlib.sha256(raw).hexdigest())
        for declaration in (module.PUBLIC_DOCTYPE.replace('250101', '250102'),
                            module.PUBLIC_DOCTYPE.replace('https://dtd.nlm.nih.gov', 'https://untrusted.invalid'),
                            module.PUBLIC_DOCTYPE[:-1] + ' [<!ENTITY x SYSTEM "file:///private">]>',
                            module.PUBLIC_DOCTYPE + '\n' + module.PUBLIC_DOCTYPE,
                            module.PUBLIC_DOCTYPE + '\n<!ENTITY x "private">'):
            with self.subTest(declaration=declaration), self.assertRaisesRegex(module.PubMedRetrievalError, '^XML_ENTITY_DENIED$'):
                await self.run_fixture(raw=declaration.encode() + xml())

    async def test_each_dispatch_checks_current_authority_after_rate_wait_and_preserves_denial(self):
        calls = []
        denial = PermissionError('private-current-authority')
        checks = []
        async def throttle():
            checks.append('throttle')
        def authorize():
            checks.append('authorize')
            if calls:
                raise denial
            return {'trusted': 'plan-return-is-ignored'}
        def handler(request):
            calls.append(request)
            return httpx.Response(200, stream=Stream(b'{"esearchresult":{"idlist":["123"]}}'))
        with patch.object(module, '_throttle', side_effect=throttle):
            with self.assertRaises(PermissionError) as caught:
                await module.retrieve(transport=httpx.MockTransport(handler), before_dispatch=authorize)
        self.assertIs(caught.exception, denial)
        self.assertEqual(len(calls), 1)
        self.assertEqual(checks, ['throttle', 'authorize', 'throttle', 'authorize'])

    async def test_async_authority_callback_is_rejected_without_dispatch(self):
        handler = AsyncMock()
        callback = AsyncMock()
        with self.assertRaisesRegex(module.PubMedRetrievalError, '^CONFIG_INVALID$'):
            await module.retrieve(transport=httpx.MockTransport(handler), before_dispatch=callback)
        handler.assert_not_called()
