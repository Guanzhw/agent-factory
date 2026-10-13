"""Actual scoped production route, fake network/provider/custody only."""
import asyncio
from asyncio import proactor_events, selector_events
import json
from pathlib import Path
import ssl
import subprocess
import socket
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agno.exceptions import ModelProviderError
from agno.models.message import Message
import certifi
from fastapi import HTTPException
import httpcore
import httpx

from agent_factory.byok_model import OwnerChatModel, PinnedChatTransport
from agent_factory.config import Settings
from agent_factory.application_environments import ApplicationEnvironments
from agent_factory.environment_bindings import EnvironmentModelHandle
from agent_factory.owner_runtime_broker import OwnerRuntimeBroker
from agent_factory.personal_models import OwnerModelHandle, PersonalModels
from agent_factory.personal_remote_provider import PinnedHTTPSProbe, RemoteConnectionError, SecretLease
from agent_factory.trusted_model_proxy import GO_BASE, TrustedModelProxy
from trusted_proxy_test_streams import HOST, MemoryBackend, MemoryStream, PROXY

IP = '93.184.216.34'
SECRET = 'synthetic-owner-secret'


def guarded_connect(original):
    """Deny model sockets; admit only stdlib Windows event-loop self-pipe IPC."""
    # Windows socket.socketpair aliases _fallback_socketpair; its actual frame
    # name is not "socketpair". Match installed stdlib code objects, not names or
    # synthetic filenames/globals that another function could impersonate.
    pair_codes = {getattr(function,'__code__',None) for function in
        [socket.socketpair,getattr(socket,'_fallback_socketpair',None)]}
    pair_codes.discard(None)
    pipe_codes = {proactor_events.BaseProactorEventLoop._make_self_pipe.__code__,
        selector_events.BaseSelectorEventLoop._make_self_pipe.__code__}
    def connect(sock, address):
        pair, self_pipe = False, False
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code in pair_codes and frame.f_globals is socket.__dict__:
                pair = True
            if frame.f_code in pipe_codes:
                self_pipe = True
            frame = frame.f_back
        local = (isinstance(address,tuple) and len(address)>=2
            and address[0] in {'127.0.0.1','::1'} and type(address[1]) is int)
        if pair and self_pipe and local:
            return original(sock,address)
        raise AssertionError('REAL_NETWORK_DENIED')
    return connect


def body():
    return {'ownerId': 'alice', 'reference': 'owner-model-fixture', 'revision': 'model-revision',
        'credentialRef': 'owner-secret-fixture', 'credentialRevision': 'secret-revision',
        'provider': 'openai-compatible', 'baseURL': GO_BASE, 'model': 'fixture-model'}


def grant(**changes):
    value = body()
    arguments = dict(environment_id='fixture-environment', owner_id=value['ownerId'],
        model_reference=value['reference'], model_revision=value['revision'],
        credential_reference=value['credentialRef'], credential_revision=value['credentialRevision'],
        model_id=value['model'], proxy_url='http://' + PROXY + ':8080',
        ssl_context=ssl.create_default_context(cafile=certifi.where()), acknowledge_interception=True)
    return TrustedModelProxy(**{**arguments, **changes})


class GatewayBackend(MemoryBackend):
    def __init__(self, configuration, *, denied=False, bad_certificate=False, disconnect=False):
        super().__init__(configuration.ssl_context, denied=denied, bad_certificate=bad_certificate,
            https=configuration.proxy_url.startswith('https:'))
        self.disconnect = disconnect
        self.target_response = json.dumps({'choices': [{'finish_reason': 'stop',
            'message': {'role': 'assistant', 'content': 'synthetic gateway completion'}}]}).encode()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connections.append({'host': host, 'port': port})
        backend = self
        class Stream(MemoryStream):
            async def read(self, max_bytes, timeout=None):
                if backend.disconnect and len(self.incoming) == 1:
                    raise httpcore.ReadError(SECRET + ' fixture-proxy-secret ' + PROXY)
                return await super().read(max_bytes, timeout=timeout)
        stream = Stream(self)
        stream.incoming[1] = (b'HTTP/1.1 200 OK\r\nContent-Length: '
            + str(len(self.target_response)).encode() + b'\r\n\r\n' + self.target_response)
        return stream


class TrustedModelProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guards = [patch('socket.socket.connect',new=guarded_connect(socket.socket.connect)),
            patch('socket.socket.connect_ex',new=guarded_connect(socket.socket.connect_ex)),
            patch('socket.getaddrinfo',side_effect=AssertionError('REAL_DNS_DENIED')),
            patch('agent_factory.personal_remote_provider.subprocess.run',
                side_effect=AssertionError('REAL_DNS_SUBPROCESS_DENIED'))]
        for guard in self.guards:
            guard.start()

    async def asyncTearDown(self):
        for guard in reversed(self.guards):
            guard.stop()

    async def post(self, configuration, backend, *, before_send=None, on_dispatch=None):
        transport = PinnedChatTransport('https://opencode.ai', base_path='/zen/go/v1',
            trusted_proxy=configuration, before_send=before_send, on_dispatch=on_dispatch)
        transport.probe.addresses = lambda destination: [IP]
        with patch('agent_factory.trusted_model_proxy.httpcore.AnyIOBackend', return_value=backend):
            async with httpx.AsyncClient(transport=transport, trust_env=False, auth=None,
                    follow_redirects=False) as client:
                return await client.post(GO_BASE + '/chat/completions',
                    json={'model': 'fixture-model', 'stream': False, 'messages': []})

    async def test_actual_gateway_ip_connect_official_sni_and_explicit_context(self):
        configuration = grant(dns_timeout_seconds=10)
        backend = GatewayBackend(configuration)
        marks, checks = [], []
        with patch.dict('os.environ', {'HTTPS_PROXY': 'http://untrusted-ambient.invalid:9999',
                'SSL_CERT_FILE': '/nonexistent-ambient-forbidden', 'NO_PROXY': '*'}):
            response = await self.post(configuration, backend,
                before_send=lambda: checks.append('owner-rechecked'), on_dispatch=lambda: marks.append('dispatch'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(checks, ['owner-rechecked'])
        self.assertEqual(marks, ['dispatch'])
        self.assertEqual(backend.connections, [{'host': PROXY, 'port': 8080}])
        raw = b''.join(backend.writes)
        self.assertIn(('CONNECT ' + IP + ':443 HTTP/1.1').encode(), raw)
        self.assertIn(b'host: opencode.ai\r\n', raw.lower())
        self.assertEqual(backend.tls[0]['server_hostname'], 'opencode.ai')
        self.assertTrue(all(backend.tls[0][key] for key in ['verify_required','check_hostname','context_identity_preserved']))
        self.assertGreaterEqual(backend.closed, 1)

    async def test_network_guard_still_denies_remote_and_non_selfpipe_loopback(self):
        with socket.socket() as sock:
            for address in [('93.184.216.34',443),('127.0.0.1',9),('::1',9)]:
                with self.assertRaises(AssertionError):
                    sock.connect(address)
                with self.assertRaises(AssertionError):
                    sock.connect_ex(address)
        # Exercise the real Windows fallback and real standard event-loop method,
        # including the actual _fallback_socketpair frame identity. No model data
        # is sent; these sockets are only the event loop's internal loopback IPC.
        loop = SimpleNamespace(_internal_fds=0)
        with patch('socket.socketpair',socket._fallback_socketpair):
            proactor_events.BaseProactorEventLoop._make_self_pipe(loop)
        try:
            self.assertEqual(loop._internal_fds,1)
            self.assertIn(loop._ssock.getsockname()[0],{'127.0.0.1','::1'})
        finally:
            loop._ssock.close()
            loop._csock.close()
        # Calling the same fallback outside the standard self-pipe is still denied.
        with self.assertRaises(AssertionError):
            socket._fallback_socketpair()

    def wrapped_environment(self, configuration):
        class Read:
            def __enter__(self): return self
            def __exit__(self,*args): return False
        current = body()
        model_row = {'state':'ACTIVE','revision':current['revision'],'body':current}
        models = object.__new__(PersonalModels)
        models.transport_factory = None
        models.proxy_environment_id = 'fixture-environment'
        models.trusted_model_proxy = None
        models.install_trusted_model_proxy(configuration)
        models.auth = SimpleNamespace(require=lambda owner,action: None)
        models.db = SimpleNamespace(read=Read)
        models.connections = SimpleNamespace(_key=lambda value: None)
        models._row = lambda conn,owner,reference: model_row
        models._authorize = lambda owner,values: True
        resolves = []
        def resolve(**values):
            resolves.append(values)
            return SecretLease('api-key',SECRET)
        models.vault = SimpleNamespace(resolve=resolve)
        environment = {'id':'environment-fixture'}
        effective = {'modelReference':current['reference'],'modelRevision':current['revision'],
            'serverSelection':{'location':'platform','directory':'fixture-changed'}}
        row = {'body':environment,'credential_binding':effective}
        service = object.__new__(ApplicationEnvironments)
        service.models, service.auth, service.db = models, models.auth, models.db
        service._row = lambda conn,owner,identifier: row
        service.bindings = SimpleNamespace(original=lambda value: {**effective,
            'serverSelection':{'location':'platform','directory':'fixture-original'}})
        handle = service.model_handle('alice',environment)
        self.assertIsInstance(handle,EnvironmentModelHandle)
        return handle,models,service,row,model_row,resolves

    async def test_real_environment_rebind_wrapper_preserves_gateway_to_broker(self):
        configuration = grant()
        handle,models,service,row,model_row,resolves = self.wrapped_environment(configuration)
        self.assertIs(handle.trusted_proxy,configuration)
        backend = GatewayBackend(configuration)
        with TemporaryDirectory() as folder:
            broker = OwnerRuntimeBroker(Path(folder)/'broker.sock',handle)
            with patch('agent_factory.byok_model.PinnedHTTPSProbe.addresses',return_value=[IP]), \
                    patch('agent_factory.trusted_model_proxy.httpcore.AnyIOBackend',return_value=backend):
                result = await broker.completion({'model':'owner-model',
                    'messages':[{'role':'user','content':'synthetic rebound goal'}]},'ses_syntheticproxy123')
        self.assertEqual(result['choices'][0]['message']['content'],'synthetic gateway completion')
        self.assertEqual(backend.connections,[{'host':PROXY,'port':8080}])
        self.assertEqual(len(resolves),1)
        self.assertEqual(resolves[0]['owner'],'alice')

    async def test_environment_wrapper_revocation_or_revision_change_never_falls_back(self):
        configuration = grant()
        handle,models,service,row,model_row,resolves = self.wrapped_environment(configuration)
        handle.check()
        models.install_trusted_model_proxy(None)
        with self.assertRaises(HTTPException):
            handle.credential()
        self.assertEqual(resolves,[])
        models.install_trusted_model_proxy(configuration)
        row['credential_binding'] = {**row['credential_binding'],'modelRevision':'changed-binding'}
        with self.assertRaises(HTTPException):
            handle.credential()
        row['credential_binding'] = {**row['credential_binding'],'modelRevision':'changed-model-revision'}
        model_row['revision'] = 'changed-model-revision'
        model_row['body'] = {**model_row['body'],'revision':'changed-model-revision'}
        with self.assertRaises(HTTPException):
            service.model_handle('alice',row['body'])
        self.assertEqual(resolves,[])

    async def test_https_gateway_has_separate_proxy_and_target_tls_names(self):
        configuration = grant(proxy_url='https://' + PROXY + ':8080')
        backend = GatewayBackend(configuration)
        self.assertEqual((await self.post(configuration, backend)).status_code, 200)
        self.assertEqual([item['server_hostname'] for item in backend.tls], [PROXY, 'opencode.ai'])

    async def test_denial_and_certificate_failure_do_not_fallback(self):
        for denied, bad_certificate, expected in [(True, False, httpcore.ProxyError),
                (False, True, ssl.SSLCertVerificationError)]:
            configuration = grant()
            backend = GatewayBackend(configuration, denied=denied, bad_certificate=bad_certificate)
            with self.assertRaises(expected):
                await self.post(configuration, backend)
            self.assertEqual(backend.connections, [{'host': PROXY, 'port': 8080}])
            self.assertNotIn(b'POST ', b''.join(backend.writes))

    async def test_invalid_scope_grants_cannot_be_configured(self):
        for changes in [{'acknowledge_interception': False}, {'proxy_url': 'http://user:secret@proxy.invalid'},
                {'proxy_url': 'http://proxy.invalid/?secret=forbidden'}, {'proxy_url': 'http://proxy.invalid:0'},
                {'dns_timeout_seconds': 11}, {'dns_timeout_seconds': True}, {'dns_timeout_seconds': float('nan')}]:
            with self.assertRaises(ValueError) as error:
                grant(**changes)
            self.assertNotIn('user:secret', str(error.exception))
        invalid = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        invalid.check_hostname = False
        invalid.verify_mode = ssl.CERT_NONE
        with self.assertRaises(ValueError):
            grant(ssl_context=invalid)

    async def test_one_owner_model_version_and_environment_only(self):
        configuration = grant()
        self.assertIs(configuration.select('alice', body(), 'fixture-environment'), configuration)
        self.assertIsNone(configuration.select('bob', {**body(), 'ownerId': 'bob'}, 'fixture-environment'))
        self.assertIsNone(configuration.select('alice', {**body(), 'reference': 'another-model'}, 'fixture-environment'))
        for field in ['ownerId','revision','credentialRef','credentialRevision','model','baseURL']:
            with self.assertRaises(ValueError):
                configuration.select('alice', {**body(), field: 'changed'}, 'fixture-environment')
        with self.assertRaises(ValueError):
            configuration.select('alice', body(), 'different-environment')
        self.assertNotIn(PROXY, repr(configuration))
        self.assertNotIn('owner-secret', repr(configuration))

    async def test_tls_context_mutation_is_rejected_and_other_owner_stays_direct(self):
        configuration = grant()
        configuration.ssl_context.check_hostname = False
        with self.assertRaises(ValueError):
            configuration.select('alice', body(), 'fixture-environment')
        self.assertIsNone(configuration.select('bob', {**body(), 'ownerId': 'bob'}, 'fixture-environment'))

    async def test_private_ipv6_or_changed_origin_rejected_before_dispatch(self):
        for address in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','2606:4700:78::90:0:140']:
            marks = []
            transport = PinnedChatTransport('https://opencode.ai', base_path='/zen/go/v1',
                trusted_proxy=grant(), on_dispatch=lambda: marks.append('dispatch'))
            transport.probe.addresses = lambda destination: [address]
            async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
                with self.assertRaises(ValueError):
                    await client.post(GO_BASE + '/chat/completions', json={'model':'fixture-model','stream':False})
            self.assertEqual(marks, [])
        with self.assertRaises(ValueError):
            PinnedChatTransport('https://other.example.com', trusted_proxy=grant())

    async def test_payload_model_switch_and_reuse_rejected(self):
        configuration = grant()
        backend = GatewayBackend(configuration)
        marks = []
        transport = PinnedChatTransport('https://opencode.ai', base_path='/zen/go/v1',
            trusted_proxy=configuration, on_dispatch=lambda: marks.append('dispatch'))
        transport.probe.addresses = lambda destination: [IP]
        with patch('agent_factory.trusted_model_proxy.httpcore.AnyIOBackend', return_value=backend):
            async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
                with self.assertRaises(ValueError):
                    await client.post(GO_BASE + '/chat/completions', json={'model':'different','stream':False})
                self.assertEqual(marks, [])
                await client.post(GO_BASE + '/chat/completions', json={'model':'fixture-model','stream':False})
                with self.assertRaises(ValueError):
                    await transport.transport.pool._network_backend.connect_tcp(PROXY, 8080)
                with self.assertRaises(ValueError):
                    await client.post(GO_BASE + '/chat/completions', json={'model':'fixture-model','stream':False})
        self.assertEqual(len(backend.connections), 1)
        self.assertEqual(len(marks), 1)

    async def test_sdk_uses_existing_credential_callback_and_sanitizes_proxy_failure(self):
        configuration = grant()
        backend = GatewayBackend(configuration, disconnect=True)
        resolved = []
        def credential():
            resolved.append('existing-owner-vault-callback')
            return SecretLease('api-key', SECRET)
        model = OwnerChatModel(body(), credential, trusted_proxy=configuration)
        with patch('agent_factory.byok_model.PinnedHTTPSProbe.addresses', return_value=[IP]), \
                patch('agent_factory.trusted_model_proxy.httpcore.AnyIOBackend', return_value=backend):
            with self.assertRaises(ModelProviderError) as error:
                await model.ainvoke([Message(role='user', content='synthetic fixture')])
        self.assertEqual(resolved, ['existing-owner-vault-callback'])
        self.assertNotIn(SECRET, str(error.exception))
        self.assertNotIn(PROXY, str(error.exception))
        self.assertEqual(len(backend.connections), 1)

    async def test_sdk_rejects_changed_owner_or_model_before_resolving_key(self):
        configuration = grant()
        with self.assertRaises(ValueError):
            OwnerChatModel({**body(), 'ownerId': 'bob'}, lambda: None, trusted_proxy=configuration)
        resolved = []
        model = OwnerChatModel(body(), lambda: resolved.append('must-not-resolve'), trusted_proxy=configuration)
        model.id = 'changed-model'
        with self.assertRaises(ModelProviderError):
            await model.ainvoke([Message(role='user', content='synthetic fixture')])
        self.assertEqual(resolved, [])

    async def test_runtime_handle_route_revocation_is_rechecked(self):
        configuration = grant()
        service = object.__new__(PersonalModels)
        service.transport_factory = None
        service.proxy_environment_id = 'fixture-environment'
        service.trusted_model_proxy = None
        service.install_trusted_model_proxy(configuration)
        handle = OwnerModelHandle(service, 'alice', body())
        self.assertIs(handle.trusted_proxy, configuration)
        class Read:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        service.auth = SimpleNamespace(require=lambda owner, action: None)
        service.db = SimpleNamespace(read=Read)
        service._row = lambda conn, owner, reference: {'state':'ACTIVE','revision':'model-revision','body':body()}
        service._authorize = lambda owner, values: True
        handle.check()
        service.install_trusted_model_proxy(None)
        with self.assertRaises(HTTPException):
            handle.check()

    async def test_default_settings_and_explicit_environment_config(self):
        self.assertIsNone(Settings(db_url='sqlite:///:memory:').owner_model_trusted_proxy)
        configuration = grant()
        Settings(db_url='sqlite:///:memory:', owner_model_trusted_proxy=configuration,
            owner_model_proxy_environment_id='fixture-environment')
        for values in [{'owner_model_proxy_environment_id':'different'},
                {'owner_model_proxy_environment_id':'fixture-environment', 'owner_model_transport_factory': lambda: None}]:
            with self.assertRaises(ValueError):
                Settings(db_url='sqlite:///:memory:', owner_model_trusted_proxy=configuration, **values)

    async def test_dns_deadline_default_retained_and_scoped_override_is_bounded(self):
        self.assertEqual(PinnedHTTPSProbe().dns_timeout_seconds, 3)
        for value in [True, 0, 11, float('inf')]:
            with self.assertRaises(ValueError):
                PinnedHTTPSProbe(dns_timeout_seconds=value)
        for timeout in [3, 10]:
            with patch('agent_factory.personal_remote_provider.subprocess.run',
                    return_value=SimpleNamespace(stdout=json.dumps([IP]))) as run:
                self.assertEqual(PinnedHTTPSProbe(dns_timeout_seconds=timeout).addresses('https://opencode.ai'), [IP])
            self.assertEqual(run.call_args.kwargs['timeout'], timeout)
        with patch('agent_factory.personal_remote_provider.subprocess.run',
                side_effect=subprocess.TimeoutExpired('synthetic helper',10)):
            with self.assertRaises(RemoteConnectionError):
                PinnedHTTPSProbe(dns_timeout_seconds=10).addresses('https://opencode.ai')

    async def test_native_unknown_is_not_replayed_or_redirected(self):
        configuration = grant()
        backend = GatewayBackend(configuration, disconnect=True)
        revoked = [False]
        def check():
            if revoked[0]:
                raise ValueError('synthetic route revoked')
        handle = SimpleNamespace(body=body(), check=check,
            credential=lambda: SecretLease('api-key', SECRET), trusted_proxy=configuration,
            service=SimpleNamespace(transport_factory=None))
        with TemporaryDirectory() as folder:
            broker = OwnerRuntimeBroker(Path(folder)/'broker.sock', handle)
            request = {'model':'owner-model','messages':[{'role':'user','content':'synthetic goal'}]}
            diagnostics = []
            safe_failures = []
            original_run = asyncio.run
            def observed_run(coroutine):
                try:
                    return original_run(coroutine)
                except BaseException as failure:
                    chain,seen = [],set()
                    while failure is not None and id(failure) not in seen:
                        seen.add(id(failure))
                        trace = failure.__traceback__
                        frames = []
                        while trace is not None:
                            frames.append({'file':Path(trace.tb_frame.f_code.co_filename).name,
                                'function':trace.tb_frame.f_code.co_name,'line':trace.tb_lineno})
                            trace = trace.tb_next
                        item = {'class':type(failure).__module__+'.'+type(failure).__name__,
                            'frames':frames[-12:]}
                        if isinstance(getattr(failure,'errno',None),int):
                            item['errno'] = failure.errno
                        chain.append(item)
                        failure = failure.__cause__ or failure.__context__
                    safe_failures.append(chain)
                    raise
            with patch('agent_factory.byok_model.PinnedHTTPSProbe.addresses', return_value=[IP]), \
                    patch('agent_factory.trusted_model_proxy.httpcore.AnyIOBackend', return_value=backend), \
                    patch('agent_factory.owner_runtime_broker.asyncio.run',side_effect=observed_run):
                for _ in range(2):
                    with self.assertRaises(ValueError) as error:
                        # native_completion owns a fresh loop in its existing worker.
                        await asyncio.to_thread(broker.native_completion, request,
                            'ses_syntheticproxy123', 'msg_syntheticproxy123')
                    diagnostics.append(error.exception.diagnostic_id)
                    self.assertEqual(error.exception.code, 'OWNER_MODEL_CALL_UNCONFIRMED')
                    self.assertNotIn(SECRET, json.dumps(error.exception.response()))
            self.assertEqual(diagnostics[0], diagnostics[1])
            self.assertEqual(broker.remaining, 63)
            self.assertEqual(len(backend.connections), 1,
                'SAFE_NATIVE_WORKER_FAILURES='+json.dumps(safe_failures))
            original_errors = [record.error for record in broker.native_calls.values()]
            revoked[0] = True
            with self.assertRaises(ValueError):
                await asyncio.to_thread(broker.native_completion, request,
                    'ses_syntheticproxy123', 'msg_syntheticproxy123')
            self.assertEqual([record.error for record in broker.native_calls.values()], original_errors)
            self.assertEqual(broker.remaining, 63)
            self.assertEqual(len(backend.connections), 1)

    async def test_actual_direct_transport_ignores_proxy_and_ca_environment(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
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
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
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
