"""Pure deployment declarations and mocked read-only host metadata; no deployment."""
import copy
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from typing import Any
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from agent_factory.deployment_validation import (MAX_MANIFEST_BYTES, ValidationInputError,
    collect_local_observations, parse_manifest, validate_manifest)


class DeploymentValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.jwk = RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
        cls.jwk["kid"] = "synthetic-public-key"
        path = Path(__file__).resolve().parents[2] / "scripts" / "validate_deployment.py"
        spec = importlib.util.spec_from_file_location("fixture_validation_cli", path)
        assert spec is not None and spec.loader is not None
        cls.cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.cli)

    def manifest(self):
        return {"schema": 1, "deploymentId": "synthetic-deployment", "configurationRevision": "reviewed-v1",
            "targetHost": {"platform": "linux", "expectedCpuCount": 2, "expectedMemoryBytes": 1024**3},
            "identity": {"accessToken": {"issuer": "https://identity.example.test", "audience": "factory-api",
                "jwks": {"keys": [copy.deepcopy(self.jwk)]},
                "subjectOwners": [{"issuer": "https://identity.example.test", "subject": "synthetic-subject", "owner": "alice"}],
                "clockSkewSeconds": 30, "maxTokenLifetimeSeconds": 3600}, "browserLogin": None},
            "runtimeAttachment": {"kind": "native-agno", "httpsBaseUrl": "https://runtime.example.test",
                "expectedAgnoVersion": "3.1.0", "executorId": "factory-executor", "configurationRevision": "runtime-v1",
                "ownerMapping": [{"originOwner": "alice", "receiverOwner": "receiver-alice"}]},
            "computeBackend": {"kind": "none"},
            "policy": {"temporaryPolicy": "admin-review", "materialReviewMode": "separate-admin",
                "policyRevision": "reviewed-plan-v1", "materialPolicyRevision": "reviewed-material-v1",
                "runtimeToolContract": "bounded-process-v1", "maxWorkers": 1, "planReviewTtlSeconds": 3600}}

    def delegated(self):
        return {"kind": "delegated-cgroup-v2", "configurationRevision": "cgroup-v1", "owners": ["alice"],
            "delegatedCgroupPath": "/sys/fs/cgroup/synthetic-delegation", "rootDevice": 1, "rootInode": 2,
            "bootId": "00000000-0000-0000-0000-000000000001",
            "pool": {"poolId": "synthetic-pool", "cpu": 2, "memoryMb": 256, "diskMb": 1, "maxLeases": 2, "maxOwnerLeases": 1},
            "limits": {"cpuQuotaMicros": 100000, "cpuPeriodMicros": 100000, "memoryMaxBytes": 128*1024**2,
                "swapMaxBytes": 0, "pidsMax": 4}}

    def test_runtime_only_configuration_never_requires_compute_or_claims_acceptance(self):
        data = self.manifest()
        with patch("os.getenv", side_effect=AssertionError("No environment reads")), \
             patch("os.open", side_effect=AssertionError("Config validation must not read files")), \
             patch("httpx.AsyncClient", side_effect=AssertionError("No network")), \
             patch("subprocess.Popen", side_effect=AssertionError("No processes")):
            report = validate_manifest(data)
        self.assertTrue(report["configurationValid"], report)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["productionAccepted"])
        self.assertFalse(report["networkAttempted"])
        self.assertFalse(report["hostChangesPerformed"])
        self.assertIn("COMPUTE_CONFIG_VALID", [row["code"] for row in report["checks"]])
        output = json.dumps(report)
        for private_value in ["identity.example.test", "runtime.example.test", "synthetic-subject", self.jwk["n"]]:
            self.assertNotIn(private_value, output)

    def test_unknown_choices_remain_blocked_without_defaults(self):
        data: dict[str, Any] = {key: None for key in self.manifest()}
        data["schema"] = 1
        report = validate_manifest(data)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertFalse(report["configurationValid"])
        self.assertIn("HOST_INPUT_MISSING", [row["code"] for row in report["checks"]])
        self.assertIn("IDENTITY_INPUT_MISSING", [row["code"] for row in report["checks"]])
        with patch("os.open", side_effect=AssertionError("Missing inputs must not probe host")):
            self.assertEqual(collect_local_observations(data)["mode"], "read-only-local")

    def test_strict_json_duplicates_size_types_and_secret_rejection_are_sanitized(self):
        raw = json.dumps(self.manifest())
        self.assertEqual(parse_manifest(raw)["schema"], 1)
        for invalid in [raw.replace('"schema": 1', '"schema": 1, "schema": 1'),
                        raw.replace('"schema": 1', '"schema": true'),
                        "x"*(MAX_MANIFEST_BYTES+1), '{"schema":NaN}', '[]']:
            with self.subTest(), self.assertRaisesRegex(ValidationInputError, "^MANIFEST_INPUT_INVALID$"):
                parse_manifest(invalid)
        for field in ["password", "authorization", "clientSecret", "jwt_key", "privateKey"]:
            data = self.manifest()
            data["identity"]["accessToken"][field] = "synthetic-private-value"
            report = validate_manifest(data)
            self.assertEqual(report["status"], "FAIL")
            self.assertNotIn("synthetic-private-value", json.dumps(report))
        data = self.manifest()
        data["policy"]["maxWorkers"] = True
        self.assertFalse(validate_manifest(data)["configurationValid"])
        data = self.manifest()
        data["schema"] = 1.0
        self.assertEqual(validate_manifest(data)["status"], "FAIL")

    def test_existing_public_identity_contracts_reject_unsafe_configuration(self):
        for changes in [{"issuer": "http://identity.example.test"}, {"clockSkewSeconds": True},
                        {"jwks": {"keys": [{**self.jwk, "d": "private"}]}}]:
            data = self.manifest()
            data["identity"]["accessToken"].update(changes)
            self.assertEqual(validate_manifest(data)["status"], "FAIL")
        data = self.manifest()
        access = data["identity"]["accessToken"]
        browser = {key: value for key, value in access.items() if key != "audience"}
        browser.update(authorizationEndpoint="https://identity.example.test/authorize", tokenEndpoint="https://identity.example.test/token",
            clientId="browser-client", redirectUri="https://factory.example.test/api/factory/auth/callback", maxAuthAgeSeconds=None)
        data["identity"] = {"accessToken": None, "browserLogin": browser}
        self.assertTrue(validate_manifest(data)["configurationValid"])
        browser["redirectUri"] = "https://factory.example.test/wrong-callback"
        self.assertFalse(validate_manifest(data)["configurationValid"])

    def test_runtime_pins_and_production_policy_are_exact(self):
        for key, value in [("expectedAgnoVersion", "3.2.0"), ("httpsBaseUrl", "http://runtime.example.test"),
                           ("httpsBaseUrl", "https://user:password@runtime.example.test"), ("ownerMapping", [])]:
            data = self.manifest()
            data["runtimeAttachment"][key] = value
            self.assertFalse(validate_manifest(data)["configurationValid"])
        for key, value in [("temporaryPolicy", "bounded-synthetic"), ("materialReviewMode", "demo-self-review"),
                           ("maxWorkers", 5), ("planReviewTtlSeconds", True)]:
            data = self.manifest()
            data["policy"][key] = value
            self.assertFalse(validate_manifest(data)["configurationValid"])

    def test_backend_configuration_never_proves_enforcement(self):
        data = self.manifest()
        data["computeBackend"] = self.delegated()
        with patch("agent_factory.deployment_validation.LinuxDelegatedCgroupFS", side_effect=AssertionError("Config only")):
            report = validate_manifest(data)
        self.assertTrue(report["configurationValid"], report)
        self.assertIn("COMPUTE_BACKEND_NOT_VERIFIED", [row["code"] for row in report["checks"]])
        for key, value in [("pidsMax", True), ("cpuPeriodMicros", 0), ("memoryMaxBytes", 1), ("swapMaxBytes", -1)]:
            bad = copy.deepcopy(data)
            bad["computeBackend"]["limits"][key] = value
            self.assertFalse(validate_manifest(bad)["configurationValid"])
        data["computeBackend"] = {key: value for key, value in self.delegated().items()
                                   if key not in {"delegatedCgroupPath", "rootDevice", "rootInode", "bootId"}}
        data["computeBackend"].update(kind="cooperative-process", limits={"cpuSeconds": 1, "addressSpaceMb": 128,
            "fileSizeBytes": 65536, "wallSeconds": 3})
        report = validate_manifest(data)
        self.assertTrue(report["configurationValid"])
        self.assertEqual(report["status"], "UNSUPPORTED")
        self.assertIn("AGGREGATE_ISOLATION_NOT_PROVIDED", [row["code"] for row in report["checks"]])

    def test_compute_owner_names_match_existing_printable_owner_contract(self):
        data = self.manifest()
        data["computeBackend"] = self.delegated()
        data["computeBackend"]["owners"] = ["researcher@example.test", "研发用户"]
        self.assertTrue(validate_manifest(data)["configurationValid"])
        data["computeBackend"]["owners"] = ["x" * 201]
        self.assertFalse(validate_manifest(data)["configurationValid"])

    def test_local_observation_is_mocked_read_only_and_not_target_acceptance(self):
        data = self.manifest()
        data["computeBackend"] = self.delegated()
        with patch("agent_factory.deployment_validation._read_public_file", return_value="MemTotal: 4194304 kB\n"), \
             patch("os.sched_getaffinity", return_value={0, 1}), \
             patch("agent_factory.deployment_validation.LinuxDelegatedCgroupFS") as filesystem:
            report = collect_local_observations(data)
            filesystem.assert_called_once()
            filesystem.return_value.validate.assert_called_once_with()
        self.assertEqual(report["mode"], "read-only-local")
        self.assertFalse(report["productionAccepted"])
        self.assertIn("CGROUP_WRITE_AUTHORITY_UNVERIFIED", [row["code"] for row in report["checks"]])
        with patch("agent_factory.deployment_validation._read_public_file", side_effect=OSError("private-path-error")):
            report = collect_local_observations(self.manifest())
        self.assertIn("LOCAL_METADATA_UNAVAILABLE", [row["code"] for row in report["checks"]])
        self.assertNotIn("private-path-error", json.dumps(report))

    def test_config_cli_without_posix_nofollow_uses_checked_regular_file_fallback(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-manifest.json"
            path.write_text(json.dumps(self.manifest()))
            with patch.dict(self.cli.os.__dict__), patch("sys.stdout", new_callable=io.StringIO) as output:
                self.cli.os.__dict__.pop("O_NOFOLLOW", None)
                self.cli.os.__dict__.pop("O_NONBLOCK", None)
                self.assertEqual(self.cli.main([str(path)]), 3)
                self.assertTrue(json.loads(output.getvalue())["configurationValid"])

    def test_cli_default_is_config_only_and_flags_never_echo_input(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-manifest.json"
            path.write_text(json.dumps(self.manifest()))
            with patch.object(self.cli, "collect_local_observations", side_effect=AssertionError("No implicit host probe")), \
                 patch("sys.stdout", new_callable=io.StringIO) as output:
                code = self.cli.main([str(path)])
                report = json.loads(output.getvalue())
            self.assertEqual(code, 3)
            self.assertEqual(report["mode"], "config-only")
            for arguments in [[str(path), "--exercise"], ["private-nonexistent-path"], ["--secret-value"]]:
                with patch("sys.stdout", new_callable=io.StringIO) as output:
                    self.assertEqual(self.cli.main(arguments), 2)
                    self.assertNotIn("private-nonexistent-path", output.getvalue())
                    self.assertNotIn("secret-value", output.getvalue())
            with patch.object(self.cli, "collect_local_observations", return_value=validate_manifest(self.manifest())) as observe, \
                 patch("sys.stdout", new_callable=io.StringIO):
                self.cli.main([str(path), "--read-only-local"])
                observe.assert_called_once()


if __name__ == "__main__":
    unittest.main()
