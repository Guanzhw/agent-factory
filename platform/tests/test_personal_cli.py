"""Real offline CLI adapter regressions; every credential and effect is synthetic."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Literal, cast
import unittest
from unittest.mock import AsyncMock, Mock, patch

import agent_factory.personal_cli as personal_cli
from agent_factory.personal_cli import CliCredentialDelivery, PersonalCliAdapter
from agent_factory.personal_remote_provider import SecretLease
from agent_factory.personal_tool_contract import ToolDescriptor, ToolInvocation, ToolInvocationError


FIXTURE = Path(__file__).parent / "fixtures/personal_cli_fixture.py"
Mode = Literal["stdin", "file", "home", "environment"]
OPTIONS = {"value": "--value", "delay": "--delay-seconds", "cache": "--cache-file",
    "state": "--state-file", "inspect": "--inspect-runtime", "leak": "--leak",
    "exitCode": "--exit-code", "spawnChild": "--spawn-child",
    "ignoreSigterm": "--ignore-sigterm", "writeEffect": "--write-effect"}
INPUT_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    **{key: {"type": "string", "maxLength": 8192} for key in
       ("value", "cache", "state", "leak", "writeEffect")},
    **{key: {"type": "boolean"} for key in ("inspect", "spawnChild", "ignoreSigterm")},
    "delay": {"type": "number", "minimum": 0, "maximum": 300},
    "exitCode": {"type": "integer", "minimum": 0, "maximum": 125},
}}


def lease(account: str = "alice") -> SecretLease:
    return SecretLease("synthetic-" + account, "synthetic-token-" + account)


@unittest.skipUnless(os.name == "posix", "CLI process groups require POSIX")
class PersonalCliAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="personal-cli-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.private = self.root / "private"
        self.private.mkdir()
        self.descriptor = ToolDescriptor(adapter_id="synthetic-cli", revision="fixture-v1",
            tool_name="synthetic_lookup", description="Offline synthetic lookup",
            input_schema=INPUT_SCHEMA, transport="cli",
            credential_provider_id="synthetic-cli", credential_destination="synthetic-service",
            capabilities=("lookup",), timeout_seconds=8, max_output_bytes=65536)

    def adapter(self, mode: Mode = "stdin", *, fixed: tuple[str, ...] = (),
                options: dict[str, str] | None = None, **overrides: Any) -> PersonalCliAdapter:
        settings: dict[str, Any] = dict(descriptor=self.descriptor, executable=sys.executable,
            fixed_arguments=("-I", str(FIXTURE.resolve()), "--credential-source", mode, *fixed),
            probe_arguments=("--probe",), business_options=OPTIONS if options is None else options,
            credential=CliCredentialDelivery(mode=mode,
                home_relative_path=".config/personal-cli-fixture/credentials.json",
                environment_variable="PERSONAL_CLI_FIXTURE_CREDENTIALS",
                home_argument="--fixture-home"),
            verify_identity=lambda value, credential: (
                value.get("account") == credential.username.removeprefix("synthetic-")
                and value.get("credentialSource") == mode),
            unauthenticated_exit_codes=frozenset({77}), temporary_root=self.private)
        settings.update(overrides)
        return PersonalCliAdapter(**settings)

    def invocation(self, *, account="alice", arguments=None, **overrides) -> ToolInvocation:
        settings: dict[str, Any] = dict(owner_id="owner-" + account, connection_ref="connection-" + account,
            connection_revision="revision-1", call_id="original-call-" + account,
            arguments={} if arguments is None else arguments, run_context=object(),
            check_authorized=Mock(), resolve_credential=Mock(return_value=lease(account)))
        settings.update(overrides)
        return ToolInvocation(**settings)

    def record_processes(self, *, after=None):
        """Record public routing only; execute the real process helper unchanged."""
        calls: list[dict[str, Any]] = []
        real_run = personal_cli.run_cli_process

        async def run(**kwargs):
            calls.append({"argv": kwargs["argv"], "cwd": str(kwargs["cwd"])})
            result = await real_run(**kwargs)
            if after is not None:
                after(len(calls))
            return result

        return calls, patch.object(personal_cli, "run_cli_process", side_effect=run)

    async def wait_for_state(self, path: Path) -> dict[str, Any]:
        async with asyncio.timeout(4):
            while True:
                try:
                    state = json.loads(path.read_text())
                    if state["phase"] == "running":
                        return state
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                await asyncio.sleep(.01)

    def assert_private_cleaned(self):
        self.assertEqual(list(self.private.iterdir()), [])

    async def test_four_credential_sources_real_subprocess_with_original_invocation(self):
        for mode in ("stdin", "file", "home", "environment"):
            with self.subTest(mode=mode):
                adapter = self.adapter(mode)
                invocation = self.invocation(arguments={"value": "business-value"})
                before = (invocation.call_id, invocation.connection_ref, invocation.connection_revision,
                    invocation.owner_id, invocation.run_context, dict(invocation.arguments))
                calls, recording = self.record_processes()
                with recording:
                    result = await adapter.invoke(invocation)
                self.assertIs(adapter.descriptor, self.descriptor)
                self.assertEqual(result, {"account": "alice", "credentialSource": mode,
                    "value": "business-value"})
                self.assertEqual(len(calls), 3)  # Missing auth, supplied auth, one business command.
                self.assertTrue(all("--probe" in call["argv"] for call in calls[:2]))
                self.assertNotIn("--probe", calls[2]["argv"])
                self.assertEqual(before, (invocation.call_id, invocation.connection_ref,
                    invocation.connection_revision, invocation.owner_id, invocation.run_context,
                    dict(invocation.arguments)))
                self.assertEqual(cast(Mock, invocation.resolve_credential).call_count, 1)
                self.assert_private_cleaned()

    async def test_two_owners_and_same_connection_use_distinct_private_cache(self):
        for accounts in (("alice", "bob"), ("alice", "alice")):
            with self.subTest(accounts=accounts):
                adapter = self.adapter("home")
                invocations = [self.invocation(account=account, call_id=f"original-call-{index}",
                    arguments={"value": f"call-{index}", "cache": "business-cache.json",
                        "delay": .2, "inspect": True}) for index, account in enumerate(accounts)]
                results = await asyncio.gather(*(adapter.invoke(value) for value in invocations))
                self.assertEqual([result["account"] for result in results], list(accounts))
                self.assertEqual([result["value"] for result in results], ["call-0", "call-1"])
                self.assertEqual([result["cacheCount"] for result in results], [1, 1])
                self.assertNotEqual(results[0]["runtime"]["cwd"], results[1]["runtime"]["cwd"])
                self.assert_private_cleaned()

    async def test_missing_vault_lease_never_starts_process(self):
        for resolver in (Mock(return_value=None), Mock(side_effect=RuntimeError("synthetic-vault-denied"))):
            with self.subTest(resolver=resolver), patch.object(personal_cli, "run_cli_process", new_callable=AsyncMock) as run:
                with self.assertRaises(ToolInvocationError) as caught:
                    await self.adapter().invoke(self.invocation(resolve_credential=resolver))
                self.assertEqual(caught.exception.outcome, "failed")
                self.assertNotIn("synthetic-vault-denied", str(caught.exception))
                run.assert_not_called()
                self.assert_private_cleaned()

    async def test_missing_probe_rejects_unsafe_host_fallback_before_business(self):
        state = self.root / "unsafe-business.json"
        calls, recording = self.record_processes()
        with recording, self.assertRaises(ToolInvocationError) as caught:
            await self.adapter(fixed=("--unsafe-host-fallback",)).invoke(
                self.invocation(arguments={"state": str(state)}))
        self.assertEqual((caught.exception.code, caught.exception.outcome),
            ("CLI_AMBIENT_AUTH_REJECTED", "failed"))
        self.assertEqual(len(calls), 1)
        self.assertFalse(state.exists())
        self.assert_private_cleaned()

    async def test_probe_identity_or_source_mismatch_never_runs_business(self):
        for fixed in (("--probe-account", "other-account"), ("--probe-source", "file")):
            with self.subTest(fixed=fixed):
                state = self.root / "mismatch-business.json"
                calls, recording = self.record_processes()
                with recording, self.assertRaises(ToolInvocationError) as caught:
                    await self.adapter(fixed=fixed).invoke(self.invocation(arguments={"state": str(state)}))
                self.assertEqual((caught.exception.code, caught.exception.outcome),
                    ("CLI_IDENTITY_REJECTED", "failed"))
                self.assertEqual(len(calls), 2)
                self.assertFalse(state.exists())
                self.assert_private_cleaned()

    async def test_unknown_or_identity_arguments_rejected_before_lease_or_spawn(self):
        for arguments in ({"username": "synthetic-bob"}, {"credentials-file": "other.json"},
                {"argv": ["--account=other"]}, {"value": {"nested": "unsupported"}},
                {"value": float("nan")}, {"value": "nul\0value"}):
            with self.subTest(arguments=arguments):
                invocation = self.invocation(arguments=arguments)
                with patch.object(personal_cli, "run_cli_process", new_callable=AsyncMock) as run:
                    with self.assertRaises(ToolInvocationError) as caught:
                        await self.adapter().invoke(invocation)
                self.assertEqual(caught.exception.code, "CLI_ARGUMENTS_REJECTED")
                self.assertEqual(caught.exception.outcome, "failed")
                cast(Mock, invocation.resolve_credential).assert_not_called()
                run.assert_not_called()
                self.assert_private_cleaned()

    async def test_option_looking_value_is_passed_literally_without_shell(self):
        marker = self.root / "must-not-exist"
        value = f"--credential-source=home --username=other; $(touch {marker})"
        result = await self.adapter().invoke(self.invocation(arguments={"value": value}))
        self.assertEqual(result["value"], value)
        self.assertEqual(result["account"], "alice")
        self.assertFalse(marker.exists())
        self.assert_private_cleaned()

    def test_registration_rejects_identity_flags_and_unsafe_delivery(self):
        for flag in ("--username", "--credentials-file", "--credential-source", "--fixture-home",
                "--endpoint", "--command"):
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, "CLI_REGISTRATION_INVALID"):
                self.adapter(options={"value": flag})
        invalid = [dict(executable="python"), dict(unauthenticated_exit_codes=frozenset({0})),
            dict(descriptor=replace(self.descriptor, transport="mcp")),
            dict(credential=CliCredentialDelivery(mode="home", home_relative_path="../escape")),
            dict(credential=CliCredentialDelivery(mode="environment", environment_variable="PYTHONPATH"))]
        for settings in invalid:
            with self.subTest(settings=settings), self.assertRaisesRegex(ValueError, "CLI_REGISTRATION_INVALID"):
                self.adapter(**settings)

    async def test_rotation_or_revocation_after_probe_prevents_business(self):
        for change in ("rotation", "revocation"):
            with self.subTest(change=change):
                authority = {"current": True}

                def check():
                    if not authority["current"]:
                        raise ToolInvocationError("SYNTHETIC_AUTHORITY_CHANGED", outcome="failed", stopped=True)

                def after(count):
                    if count == 2:
                        authority["current"] = False

                state = self.root / (change + ".json")
                calls, recording = self.record_processes(after=after)
                with recording, self.assertRaises(ToolInvocationError) as caught:
                    await self.adapter().invoke(self.invocation(check_authorized=check,
                        arguments={"state": str(state)}))
                self.assertEqual(caught.exception.outcome, "failed")
                self.assertEqual(len(calls), 2)
                self.assertFalse(state.exists())
                self.assert_private_cleaned()

    async def test_adapter_resolves_current_lease_for_each_invocation(self):
        adapter = self.adapter("file")
        resolver = Mock(side_effect=[lease("alice"), lease("alice-r2")])
        first = await adapter.invoke(self.invocation(resolve_credential=resolver))
        second = await adapter.invoke(self.invocation(resolve_credential=resolver,
            connection_revision="revision-2", call_id="original-second-call"))
        self.assertEqual([first["account"], second["account"]], ["alice", "alice-r2"])
        self.assertEqual(resolver.call_count, 2)
        self.assert_private_cleaned()

    async def test_stdout_or_stderr_credential_echo_is_unknown_and_sanitized(self):
        for leak_target in ("stdout", "stderr", "both"):
            with self.subTest(leak=leak_target):
                calls, recording = self.record_processes()
                with recording, self.assertRaises(ToolInvocationError) as caught:
                    await self.adapter().invoke(self.invocation(arguments={"leak": leak_target}))
                error = caught.exception
                self.assertEqual((error.code, error.outcome, error.stopped),
                    ("CLI_INVOCATION_REJECTED", "unknown", True))
                self.assertNotIn(lease().password, str(error))
                self.assertNotIn(lease().password, repr(vars(error)))
                self.assertEqual(len(calls), 3)
                self.assert_private_cleaned()

    async def test_nonzero_business_exit_is_unknown_and_never_retried(self):
        calls, recording = self.record_processes()
        with recording, self.assertRaises(ToolInvocationError) as caught:
            await self.adapter().invoke(self.invocation(arguments={"exitCode": 43}))
        self.assertEqual((caught.exception.code, caught.exception.outcome), ("CLI_COMMAND_FAILED", "unknown"))
        self.assertEqual(len(calls), 3)
        self.assert_private_cleaned()

    async def test_private_permissions_environment_and_directory_cleanup(self):
        canaries = {"SYNTHETIC_HOST_TOKEN": "synthetic-host-token", "HTTP_PROXY": "synthetic-proxy",
            "HTTPS_PROXY": "synthetic-proxy", "PYTHONPATH": "/synthetic/imports",
            "AWS_SHARED_CREDENTIALS_FILE": "/synthetic/credentials", "HOME": "/synthetic/host-home"}
        for mode in ("stdin", "file", "home", "environment"):
            with self.subTest(mode=mode), patch.dict(os.environ, canaries):
                result = await self.adapter(mode).invoke(self.invocation(arguments={"inspect": True}))
                runtime = result["runtime"]
                directory = Path(runtime["cwd"])
                self.assertEqual(directory.parent, self.private)
                self.assertEqual(runtime["rootMode"], 0o700)
                self.assertEqual(runtime["credentialMode"], 0o600 if mode in {"file", "home"} else None)
                self.assertEqual(runtime["home"], str(directory / "home"))
                self.assertEqual(runtime["tmpdir"], str(directory / "tmp"))
                self.assertFalse((set(canaries) - {"HOME"}) & set(runtime["environmentNames"]))
                self.assertFalse(directory.exists())
                self.assert_private_cleaned()

    async def test_revocation_while_business_runs_stops_locally_without_replay(self):
        state = self.root / "revoke-running.json"
        authorized = True

        def check():
            if not authorized:
                raise ToolInvocationError("SYNTHETIC_AUTHORITY_CHANGED", outcome="failed", stopped=True)

        calls, recording = self.record_processes()
        with recording:
            task = asyncio.create_task(self.adapter().invoke(self.invocation(check_authorized=check,
                arguments={"state": str(state), "delay": 20})))
            try:
                await self.wait_for_state(state)
                authorized = False
                with self.assertRaises(ToolInvocationError) as caught:
                    await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertEqual((caught.exception.outcome, caught.exception.stopped), ("unknown", True))
        self.assertEqual(len(calls), 3)
        self.assert_private_cleaned()

    async def test_cancelled_business_retains_original_call_and_external_effect(self):
        state = self.root / "cancel-running.json"
        effect = self.root / "synthetic-external-effect.jsonl"
        invocation = self.invocation(arguments={"state": str(state), "value": "one-effect",
            "writeEffect": True, "delay": 20, "spawnChild": True, "ignoreSigterm": True})
        original = (invocation.call_id, invocation.connection_ref, invocation.connection_revision,
            invocation.owner_id, dict(invocation.arguments))
        calls, recording = self.record_processes()
        with recording:
            task = asyncio.create_task(self.adapter(fixed=("--effect-file", str(effect))).invoke(invocation))
            try:
                running = await self.wait_for_state(state)
                task.cancel()
                with self.assertRaises(ToolInvocationError) as caught:
                    await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertEqual((caught.exception.outcome, caught.exception.stopped), ("unknown", True))
        self.assertEqual(len(calls), 3)
        self.assertEqual(original, (invocation.call_id, invocation.connection_ref,
            invocation.connection_revision, invocation.owner_id, dict(invocation.arguments)))
        self.assertEqual([json.loads(line) for line in effect.read_text().splitlines()],
            [{"account": "alice", "value": "one-effect"}])
        for pid in (running["pid"], running["childPid"]):
            status = Path(f"/proc/{pid}/stat")
            if sys.platform == "linux" and status.exists():
                self.assertIn(status.read_text().rsplit(")", 1)[1].split()[0], {"Z", "X"})
        self.assert_private_cleaned()


if __name__ == "__main__":
    unittest.main()
