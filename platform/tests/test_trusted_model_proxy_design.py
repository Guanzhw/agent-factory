"""Real installed httpcore protocol state machine over an in-memory stream.

Proves emitted CONNECT/Host and TLS API arguments, not real proxy policy,
upstream routing, certificate-chain acceptance or live business compatibility.
"""
import ssl
import unittest
from unittest.mock import patch

from agno.exceptions import ModelProviderError
from agno.models.message import Message
import httpcore
import httpx

from agent_factory.byok_model import OwnerChatModel, PinnedChatTransport
from agent_factory.personal_remote_provider import SecretLease
from trusted_proxy_design_fixture import Binding, BoundBackend, bound_pool

IP = '93.184.216.34'  # Synthetic wire fixture; all real sockets/DNS are denied.
HOST = 'opencode.ai'
PROXY = 'fixture-proxy.invalid'
EVIDENCE = []
FIXTURE_SECRET = 'synthetic-test-password'


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        async for chunk in self.stream:
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class ProxyModelFixture(httpx.AsyncBaseTransport):
    """Test-only bridge; never registered or available to production configuration."""
    def __init__(self, backend, ctx):
        self.pool = bound_pool(Binding(IP, HOST, PROXY, 8080), backend, ctx)

    async def handle_async_request(self, request):
        if str(request.url) != 'https://opencode.ai/v1/chat/completions':
            raise ValueError('TEST_DESTINATION_DENIED')
        url = request.url.copy_with(host=IP)
        extensions = {key: value for key, value in request.extensions.items()
                      if key != 'sni_hostname'}
        core = httpcore.Request(method=request.method, url=httpcore.URL(
            scheme=url.raw_scheme, host=url.raw_host, port=url.port, target=url.raw_path),
            headers={**dict(request.headers), 'host': HOST},
            content=request.stream, extensions=extensions)
        response = await self.pool.handle_async_request(core)
        return httpx.Response(response.status, headers=response.headers,
            stream=ResponseStream(response.stream), extensions=response.extensions)

    async def aclose(self):
        await self.pool.aclose()


class MemoryStream(httpcore.AsyncNetworkStream):
    def __init__(self, backend):
        self.backend = backend
        self.incoming = [backend.connect_response,
                         b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n']

    async def read(self, max_bytes, timeout=None):
        return self.incoming.pop(0) if self.incoming else b''

    async def write(self, buffer, timeout=None):
        self.backend.writes.append(buffer)

    async def aclose(self):
        self.backend.closed += 1

    def get_extra_info(self, info):
        return None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.backend.tls.append({'server_hostname': server_hostname,
                                 'verify_required': ssl_context.verify_mode == ssl.CERT_REQUIRED,
                                 'check_hostname': ssl_context.check_hostname,
                                 'context_identity_preserved': ssl_context is self.backend.context})
        expected = PROXY if self.backend.https and len(self.backend.tls) == 1 else HOST
        if server_hostname != expected or self.backend.bad_certificate:
            raise ssl.SSLCertVerificationError(1, 'SYNTHETIC_CERTIFICATE_REJECTED')
        return self


class MemoryBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, context, *, denied=False, bad_certificate=False, https=False):
        self.context, self.bad_certificate, self.https = context, bad_certificate, https
        self.connect_response = (b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n'
                                 if denied else b'HTTP/1.1 200 Connection established\r\n\r\n')
        self.connections, self.writes, self.tls, self.closed = [], [], [], 0

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connections.append({'host': host, 'port': port})
        return MemoryStream(self)

    async def sleep(self, seconds):
        raise AssertionError('NO_RETRY')


def context():
    # No CA files loaded or modified. Mock TLS only checks preserved API arguments.
    return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


async def send(pool, *, legacy_sni_extension=False):
    extensions = {'timeout': {'connect': 1, 'read': 1, 'write': 1, 'pool': 1}}
    # On the proxy path the immutable backend binding handles target SNI.
    # A target sni_hostname extension also reaches an HTTPS proxy's own TLS
    # connection, so it must not be inherited from the direct request path.
    if legacy_sni_extension:
        extensions['sni_hostname'] = HOST
    async with pool:
        return await pool.request('HEAD', f'https://{IP}/',
            headers={'Host': HOST},
            extensions=extensions)


class TrustedProxyDesignTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.network_guards = [
            patch('socket.socket.connect', side_effect=AssertionError('REAL_NETWORK_FORBIDDEN')),
            patch('socket.socket.connect_ex', side_effect=AssertionError('REAL_NETWORK_FORBIDDEN')),
            patch('socket.getaddrinfo', side_effect=AssertionError('REAL_DNS_FORBIDDEN')),
        ]
        for guard in cls.network_guards:
            guard.start()

    @classmethod
    def tearDownClass(cls):
        for guard in reversed(cls.network_guards):
            guard.stop()

    async def exercise(self, label, *, adapted=True, denied=False, bad_certificate=False, https=False):
        ctx = context()
        backend = MemoryBackend(ctx, denied=denied, bad_certificate=bad_certificate, https=https)
        binding = Binding(IP, HOST, PROXY, 8080, proxy_https=https)
        if adapted:
            pool = bound_pool(binding, backend, ctx)
        else:
            pool = httpcore.AsyncConnectionPool(proxy=httpcore.Proxy(f'http://{PROXY}:8080'),
                network_backend=backend, ssl_context=ctx, retries=0,
                max_connections=1, max_keepalive_connections=0)
        error, status = None, None
        try:
            result = await send(pool, legacy_sni_extension=not adapted)
            status = result.status
        except Exception as exc:
            error = type(exc).__name__
        raw = b''.join(backend.writes)
        evidence = {'case': label, 'mock_http_status': status, 'error_class': error,
                    'connections': backend.connections,
                    'connect_lines': [line.decode('ascii') for line in raw.split(b'\r\n') if line.startswith(b'CONNECT ')],
                    'target_head_sent': b'HEAD / HTTP/1.1' in raw,
                    'official_host_sent': b'Host: opencode.ai\r\n' in raw,
                    'tls_calls': backend.tls, 'closed': backend.closed,
                    'real_provider_requests': 0}
        EVIDENCE.append(evidence)
        return evidence

    async def test_stock_proxy_ignores_sni_extension(self):
        e = await self.exercise('stock-proxy-negative-control', adapted=False)
        self.assertEqual(e['error_class'], 'SSLCertVerificationError')
        self.assertEqual(e['tls_calls'][0]['server_hostname'], IP)
        self.assertFalse(e['target_head_sent'])

    async def test_ip_connect_official_sni_and_host(self):
        e = await self.exercise('http-proxy-ip-connect-official-sni')
        self.assertEqual(e['mock_http_status'], 200)
        self.assertEqual(e['connect_lines'], [f'CONNECT {IP}:443 HTTP/1.1'])
        self.assertEqual(e['connections'], [{'host': PROXY, 'port': 8080}])
        self.assertTrue(e['official_host_sent'])
        self.assertEqual(e['tls_calls'][0]['server_hostname'], HOST)
        self.assertTrue(all(e['tls_calls'][0][k] for k in ['verify_required','check_hostname','context_identity_preserved']))

    async def test_https_proxy_tls_preserves_proxy_then_target_names(self):
        e = await self.exercise('https-proxy-separate-two-tls-stages', https=True)
        self.assertEqual(e['mock_http_status'], 200)
        self.assertEqual([x['server_hostname'] for x in e['tls_calls']], [PROXY, HOST])
        self.assertTrue(all(x['verify_required'] and x['check_hostname'] and x['context_identity_preserved'] for x in e['tls_calls']))

    async def test_proxy_policy_denial_stops_without_tls_or_fallback(self):
        e = await self.exercise('proxy-403-stop', denied=True)
        self.assertEqual(e['error_class'], 'ProxyError')
        self.assertEqual(e['tls_calls'], [])
        self.assertFalse(e['target_head_sent'])
        self.assertEqual(len(e['connections']), 1)

    async def test_bad_certificate_stops_without_target_http(self):
        e = await self.exercise('bad-certificate-stop', bad_certificate=True)
        self.assertEqual(e['error_class'], 'SSLCertVerificationError')
        self.assertFalse(e['target_head_sent'])
        self.assertEqual(len(e['connections']), 1)

    async def test_only_proxy_connection_allowed(self):
        ctx = context()
        backend = MemoryBackend(ctx)
        bound = BoundBackend(backend, Binding(IP, HOST, PROXY, 8080))
        with self.assertRaises(ValueError):
            await bound.connect_tcp(IP, 443)
        self.assertEqual(backend.connections, [])

    async def test_private_destination_and_wrong_domain_rejected(self):
        for ip in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1']:
            with self.assertRaises(ValueError):
                Binding(ip, HOST, PROXY, 8080)
        with self.assertRaises(ValueError):
            Binding(IP, 'alternate.invalid', PROXY, 8080)

    async def test_unverified_tls_context_rejected(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with self.assertRaises(ValueError):
            bound_pool(Binding(IP, HOST, PROXY, 8080), MemoryBackend(ctx), ctx)

    async def test_global_ipv6_is_explicitly_outside_prototype_scope(self):
        with self.assertRaisesRegex(ValueError, 'REVIEW_PROTOTYPE_IPV4_ONLY'):
            Binding('2606:4700:78::90:0:140', HOST, PROXY, 8080)

    async def test_wrong_target_binding_rejected_before_tls(self):
        ctx = context()
        backend = MemoryBackend(ctx)
        bound = BoundBackend(backend, Binding(IP, HOST, PROXY, 8080))
        stream = await bound.connect_tcp(PROXY, 8080)
        with self.assertRaises(ValueError):
            await stream.start_tls(ctx, server_hostname='wrong.invalid')
        self.assertEqual(backend.tls, [])

    async def test_reference_uses_only_explicit_proxy_and_context(self):
        with patch.dict('os.environ', {
                'HTTPS_PROXY': 'http://ambient-forbidden.invalid:9999',
                'HTTP_PROXY': 'http://ambient-forbidden.invalid:9999',
                'ALL_PROXY': 'socks5://ambient-forbidden.invalid:9999',
                'NO_PROXY': '*',
                'SSL_CERT_FILE': '/nonexistent-ambient-cert-forbidden'}):
            evidence = await self.exercise('explicit-deployment-fixture-only')
        self.assertEqual(evidence['mock_http_status'], 200)
        self.assertEqual(evidence['connections'], [{'host': PROXY, 'port': 8080}])
        self.assertTrue(evidence['tls_calls'][0]['context_identity_preserved'])

    async def test_actual_direct_transport_ignores_proxy_and_ca_environment(self):
        ctx = context()
        backend = MemoryBackend(ctx)
        backend.connect_response = b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}'
        owner_checks = []
        with patch.dict('os.environ', {
                'HTTPS_PROXY': 'http://ambient-forbidden.invalid:9999',
                'HTTP_PROXY': 'http://ambient-forbidden.invalid:9999',
                'SSL_CERT_FILE': '/nonexistent-ambient-cert-forbidden'}):
            direct = PinnedChatTransport('https://opencode.ai',
                before_send=lambda: owner_checks.append('current-owner'))
            direct.probe.addresses = lambda destination: [IP]
            # The real production constructor must succeed without reading ambient
            # CA/proxy configuration. Only its network pool is replaced for I/O.
            await direct.transport._pool.aclose()
            direct.transport._pool = httpcore.AsyncConnectionPool(
                network_backend=backend, ssl_context=ctx, retries=0)
            async with httpx.AsyncClient(transport=direct, trust_env=False,
                    follow_redirects=False, auth=None) as client:
                response = await client.post('https://opencode.ai/v1/chat/completions', json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(backend.connections, [{'host': IP, 'port': 443}])
        self.assertEqual(backend.tls[0]['server_hostname'], HOST)
        self.assertEqual(owner_checks, ['current-owner'])
        raw = b''.join(backend.writes)
        self.assertNotIn(b'CONNECT ', raw)
        self.assertIn(b'host: opencode.ai\r\n', raw.lower())

    async def test_actual_direct_owner_revocation_stops_before_transport(self):
        ctx = context()
        backend = MemoryBackend(ctx)
        def revoked():
            raise PermissionError('synthetic-owner-revoked')
        direct = PinnedChatTransport('https://opencode.ai',
            before_send=revoked)
        direct.probe.addresses = lambda destination: [IP]
        await direct.transport._pool.aclose()
        direct.transport._pool = httpcore.AsyncConnectionPool(
            network_backend=backend, ssl_context=ctx, retries=0)
        async with httpx.AsyncClient(transport=direct, trust_env=False, auth=None) as client:
            with self.assertRaises(PermissionError):
                await client.post('https://opencode.ai/v1/chat/completions', json={})
        self.assertEqual(backend.connections, [])

    async def test_proxy_error_is_sanitized_by_existing_model_boundary(self):
        ctx = context()
        backend = MemoryBackend(ctx)
        backend.connect_response = (b'HTTP/1.1 403 synthetic-test-password '
            b'http://fixture-user:fixture-proxy-secret@fixture-proxy.invalid/\r\n'
            b'Content-Length: 0\r\n\r\n')
        model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'fixture-model',
            'baseURL': 'https://opencode.ai/v1'},
            lambda: SecretLease('api-key', FIXTURE_SECRET),
            transport_factory=lambda: ProxyModelFixture(backend, ctx))
        with self.assertRaises(ModelProviderError) as error:
            await model.ainvoke([Message(role='user', content='synthetic fixture')])
        for value in [FIXTURE_SECRET, 'fixture-proxy-secret', PROXY, 'fixture-user']:
            self.assertNotIn(value, str(error.exception))
        self.assertEqual(backend.connections, [{'host': PROXY, 'port': 8080}])
        self.assertEqual(backend.tls, [])
        self.assertNotIn(b'POST ', b''.join(backend.writes))
        self.assertGreaterEqual(backend.closed, 1)

    async def test_proxy_model_owner_recheck_stops_before_wire(self):
        ctx = context()
        backend = MemoryBackend(ctx)
        def revoked():
            raise PermissionError(FIXTURE_SECRET)
        model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'fixture-model',
            'baseURL': 'https://opencode.ai/v1'},
            lambda: SecretLease('api-key', FIXTURE_SECRET), recheck=revoked,
            transport_factory=lambda: ProxyModelFixture(backend, ctx))
        with self.assertRaises(ModelProviderError) as error:
            await model.ainvoke([Message(role='user', content='synthetic fixture')])
        self.assertNotIn(FIXTURE_SECRET, str(error.exception))
        self.assertEqual(backend.connections, [])


if __name__ == '__main__':
    unittest.main()
