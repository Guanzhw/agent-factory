"""Real local HTTP fixtures for member-owned resource endpoints."""
import asyncio
import base64
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from agno.models.message import Message

from agent_factory.byok_model import OwnerChatModel
from agent_factory.personal_remote_provider import OpenCodeServeProvider, PinnedHTTPSProbe, RemoteConnectionError, SecretLease


class CustomResourceEndpointTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        observed = self.requests
        auth = 'Basic ' + base64.b64encode(b'fixture:synthetic-local-password').decode()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def respond(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def do_GET(self):
                observed.append((self.path, self.headers.get('Host'), self.headers.get('Authorization')))
                if self.headers.get('Authorization') != auth:
                    return self.respond(401, {})
                return self.respond(200, {'/global/health': {'healthy': True, 'version': 'fixture-v1'},
                    '/project/current': {'id': 'fixture-project'}, '/agent': [{'name': 'fixture-agent'}]}[self.path])
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                observed.append((self.path, self.headers.get('Host'), self.headers.get('Authorization'), body))
                self.respond(200, {'choices': [{'finish_reason': 'stop', 'message':
                    {'role': 'assistant', 'content': 'local fixture completion'}}]})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.addCleanup(self.close_server)
        self.destination = 'http://127.0.0.1:' + str(self.server.server_port)

    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)

    def test_remote_onboarding_uses_private_http_custom_port_and_exact_credential_destination(self):
        destination = self.destination
        scopes = []
        class Secrets:
            def authorize(self, **scope):
                scopes.append(scope)
                return scope == dict(owner='alice', reference='fixture-key', revision='v1', destination=destination)
            def resolve(self, **scope):
                if not self.authorize(**scope): raise ValueError('owner or destination changed')
                return SecretLease('fixture', 'synthetic-local-password')
        provider = OpenCodeServeProvider(Secrets())
        configuration = dict(origin=destination, credentialRef='fixture-key', credentialRevision='v1', projectId='fixture-project')
        proof = provider.verify('alice', configuration)
        self.assertEqual(proof['projectId'], 'fixture-project')
        self.assertEqual([r[0] for r in self.requests], ['/global/health', '/global/health', '/project/current', '/agent'])
        self.assertIsNone(self.requests[0][2])
        self.assertTrue(all(r[1] == destination.removeprefix('http://') for r in self.requests))
        self.assertTrue(all(s['destination'] == destination for s in scopes))
        before = len(self.requests)
        self.assertFalse(provider.authorized('bob', configuration))
        self.assertFalse(provider.authorized('alice', configuration | {'origin': destination.replace('127.0.0.1', 'localhost')}))
        self.assertEqual(len(self.requests), before)

    def test_model_actual_http_custom_path_and_host_port_preserve_selected_model(self):
        model = OwnerChatModel({'provider': 'openai-compatible', 'model': 'local/fixture-model',
            'baseURL': self.destination + '/custom/model/api'},
            lambda: SecretLease('api-key', 'synthetic-model-key'))
        result = asyncio.run(model.ainvoke([Message(role='user', content='local fixture')]))
        self.assertEqual(result.content, 'local fixture completion')
        self.assertEqual(len(self.requests), 1)
        path, host, credential, body = self.requests[0]
        self.assertEqual(path, '/custom/model/api/chat/completions')
        self.assertEqual(host, self.destination.removeprefix('http://'))
        self.assertEqual(credential, 'Bearer synthetic-model-key')
        self.assertEqual(body['model'], 'local/fixture-model')


    def test_real_https_custom_port_preserves_host_identity_and_rejects_untrusted_or_wrong_name(self):
        with TemporaryDirectory() as folder:
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
            now = datetime.now(timezone.utc)
            certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
            certfile, keyfile = Path(folder) / 'certificate.pem', Path(folder) / 'key.pem'
            certfile.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
            keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile, keyfile)
            names = []
            context.set_servername_callback(lambda socket, name, original: names.append(name))
            server = ThreadingHTTPServer(('127.0.0.1', 0), self.server.RequestHandlerClass)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
            try:
                destination = 'https://localhost:' + str(server.server_port)
                probe = PinnedHTTPSProbe()
                with self.assertRaisesRegex(RemoteConnectionError, '^REMOTE_PROBE_FAILED$'):
                    probe.get(destination, '127.0.0.1', '/global/health')
                self.assertEqual(self.requests, [])
                with patch.dict(os.environ, {'SSL_CERT_FILE': str(certfile), 'SSL_CERT_DIR': folder}):
                    status, _ = probe.get(destination, '127.0.0.1', '/global/health',
                        SecretLease('fixture', 'synthetic-local-password'))
                    self.assertEqual(status, 200)
                    self.assertEqual(self.requests[-1][1], 'localhost:' + str(server.server_port))
                    before = len(self.requests)
                    with self.assertRaisesRegex(RemoteConnectionError, '^REMOTE_PROBE_FAILED$'):
                        probe.get('https://wrong.example:' + str(server.server_port), '127.0.0.1', '/global/health')
                    self.assertEqual(len(self.requests), before)
                self.assertEqual(names, ['localhost', 'localhost', 'wrong.example'])
            finally:
                server.shutdown(); server.server_close(); worker.join(timeout=2)
