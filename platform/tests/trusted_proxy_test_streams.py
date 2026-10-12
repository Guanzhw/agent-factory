"""In-memory HTTPcore wire only; no real networking or credentials."""
import ssl

import httpcore

HOST = 'opencode.ai'
PROXY = 'fixture-proxy.invalid'

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
