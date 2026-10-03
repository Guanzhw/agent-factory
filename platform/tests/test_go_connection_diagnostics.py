import errno
import json
import socket
import ssl
import unittest

import httpx

from agent_factory.go_connection_diagnostics import safe_connection_diagnostic


class GoConnectionDiagnosticTests(unittest.TestCase):
    def test_nested_cause_categories_errno_and_no_text(self):
        for nested, category in ((socket.gaierror(-2, "private-host"), "DNS"),
                (ssl.SSLCertVerificationError("private-cert"), "TLS"),
                (ConnectionRefusedError(errno.ECONNREFUSED, "private-host"), "TCP"),
                (httpx.ProxyError("403 Forbidden private-proxy"), "PROXY")):
            error = httpx.ConnectError("private-url")
            error.__cause__ = nested
            result = safe_connection_diagnostic(error)
            self.assertEqual(result["category"], category)
            self.assertNotIn("private", json.dumps(result))
            self.assertNotIn("403", json.dumps(result))
            if category == "TCP":
                self.assertEqual(result["safeCauses"][-1]["errnoSymbol"], "ECONNREFUSED")

    def test_groups_cycles_depth_and_node_bounds(self):
        errors = [socket.gaierror(-2, "private") for _ in range(100)]
        group = ExceptionGroup("private", errors)
        group.__context__ = group
        result = safe_connection_diagnostic(group)
        self.assertLessEqual(len(result["safeCauses"]), 8)
        self.assertEqual(result["category"], "DNS")
        error = ValueError("private")
        for _ in range(20):
            parent = ValueError("private")
            parent.__cause__ = error
            error = parent
        self.assertEqual(len(safe_connection_diagnostic(error)["safeCauses"]), 5)

    def test_unknown_subclass_cannot_run_properties_or_expose_name(self):
        class PrivateExceptionName(OSError):
            def __str__(self):
                raise AssertionError("Must not stringify")
            @property
            def errno(self):
                raise AssertionError("Must not invoke custom properties")
        result = safe_connection_diagnostic(PrivateExceptionName("private"))
        self.assertEqual(result["category"], "UNKNOWN")
        self.assertEqual(result["safeCauses"], [{"errorType": "UnknownError", "category": "UNKNOWN"}])

    def test_exact_proxy_status_only_and_generic_connect_is_unlocalized(self):
        for phrase, status in (("403 Forbidden", 403), ("407 Proxy Authentication Required", 407),
                               ("451 Unavailable For Legal Reasons", 451)):
            result = safe_connection_diagnostic(httpx.ProxyError(phrase))
            self.assertEqual(result["safeCauses"][0]["proxyStatus"], status)
        self.assertNotIn("proxyStatus", safe_connection_diagnostic(httpx.ProxyError("403 Forbidden private"))["safeCauses"][0])
        self.assertEqual(safe_connection_diagnostic(httpx.ConnectError("private"))["category"], "CONNECTION")

    def test_dns_errno_symbol_is_platform_constant_allowlisted(self):
        for name in ("EAI_AGAIN", "EAI_NONAME", "EAI_FAIL"):
            if hasattr(socket, name):
                result = safe_connection_diagnostic(socket.gaierror(getattr(socket, name), "private-host"))
                self.assertEqual(result["safeCauses"][0]["errnoSymbol"], name)
