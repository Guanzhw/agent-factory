"""Trusted personal CLI adapter with invocation-owned authentication state.

The shared core owns the connection, credential revisions and original effect.
This adapter never caches a lease, retries a business command or writes to the
vault. Every call gets a private HOME/config/temp directory, even for old CLIs.
Static registrations must supply a read-only authentication probe which reports
the actual account and credential source. These are ordinary same-UID processes,
not a sandbox for hostile executables or proof of remote effect termination.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any, Callable, Literal, Mapping

from ._personal_cli_process import CLIProcessError, CLIProcessResult, run_cli_process
from .personal_remote_provider import SecretLease, reject_credential_echo
from .personal_tool_contract import ToolDescriptor, ToolInvocation, ToolInvocationError


def _json_credential(lease: SecretLease) -> bytes:
    return json.dumps({"username": lease.username, "password": lease.password}).encode()


@dataclass(frozen=True)
class CliCredentialDelivery:
    """Operator configuration; no credential value belongs in this object.

    Prefer stdin or an explicit file argument. Environment and HOME are for CLIs
    whose documented authentication interface requires them. ``encode`` is a
    trusted format adapter, not callable material supplied by an application.
    """

    mode: Literal["stdin", "file", "environment", "home"] = "stdin"
    file_argument: str = "--credentials-file"
    home_relative_path: str = ".config/personal-cli/credentials.json"
    environment_variable: str | None = None
    home_argument: str | None = None
    encode: Callable[[SecretLease], bytes] = field(default=_json_credential, repr=False)


_RESERVED_OPTIONS = frozenset({
    "--credentials", "--credentials-file", "--credential-source", "--config", "--config-dir",
    "--home", "--profile", "--account", "--user", "--username", "--password", "--token",
    "--api-key", "--endpoint", "--host", "--server", "--shell", "--command", "--exec",
})


def _option(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"--[a-z][a-z0-9-]{0,63}", value) is not None


class PersonalCliAdapter:
    """One registered executable/command, with explicitly mapped business flags.

    ``fixed_arguments`` and ``probe_arguments`` come only from trusted assembly.
    Callers provide named scalar values, never argv, environment or executable
    paths. Values use --option=value, preventing option injection through values.
    ``verify_identity`` must attest both the actual account and authentication
    source using the probe's output and this invocation's lease. A positive probe
    alone is insufficient: the same probe must explicitly reject absent auth.

    This initial implementation deliberately has no persistent refresh/cache
    state. A future persistent mode needs an owner+connection cross-process lock
    and revision-scoped directories; temporary calls do not share mutable files.
    Asyncio debug tracing can log pipe payloads before echo filtering, so calls
    require a loop whose debug setting remains disabled throughout execution.
    This adapter never changes shared loop or logging configuration.
    """

    def __init__(self, *, descriptor: ToolDescriptor, executable: str,
                 fixed_arguments: tuple[str, ...] = (), probe_arguments: tuple[str, ...],
                 business_options: Mapping[str, str], credential: CliCredentialDelivery,
                 verify_identity: Callable[[Any, SecretLease], bool],
                 unauthenticated_exit_codes: frozenset[int],
                 parse_output: Callable[[bytes], Any] = json.loads,
                 temporary_root: str | Path | None = None):
        path = Path(executable)
        home_path = Path(credential.home_relative_path)
        protected = _RESERVED_OPTIONS | {credential.file_argument, credential.home_argument}
        if (descriptor.transport != "cli" or not path.is_absolute() or not path.is_file()
                or not os.access(path, os.X_OK) or not callable(verify_identity)
                or not callable(parse_output) or not callable(credential.encode)
                or credential.mode not in {"stdin", "file", "environment", "home"}
                or not _option(credential.file_argument)
                or (credential.home_argument is not None and not _option(credential.home_argument))
                or home_path.is_absolute() or ".." in home_path.parts or not home_path.parts
                or (credential.mode == "environment" and (
                    not credential.environment_variable
                    or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", credential.environment_variable)
                    or credential.environment_variable in {"PATH", "HOME", "TMPDIR", "LD_PRELOAD", "PYTHONPATH"}
                    or credential.environment_variable.startswith(("XDG_", "LD_", "DYLD_", "PYTHON"))))
                or not unauthenticated_exit_codes or 0 in unauthenticated_exit_codes
                or any(type(code) is not int or not 1 <= code <= 125 for code in unauthenticated_exit_codes)
                or any(not isinstance(arg, str) or "\0" in arg for arg in (*fixed_arguments, *probe_arguments))
                or any(not isinstance(key, str) or not _option(option) or option in protected
                       for key, option in business_options.items())
                or len(set(business_options.values())) != len(business_options)
                or not math.isfinite(descriptor.timeout_seconds) or not 0 < descriptor.timeout_seconds <= 300
                or not 1024 <= descriptor.max_output_bytes <= 1048576):
            raise ValueError("CLI_REGISTRATION_INVALID")
        self.descriptor = descriptor
        self._executable = str(path.resolve(strict=True))
        self._executable_digest = self._digest()
        self._fixed = tuple(fixed_arguments)
        self._probe = tuple(probe_arguments)
        self._options = dict(business_options)
        self._credential = credential
        self._verify_identity = verify_identity
        self._unauthenticated_codes = frozenset(unauthenticated_exit_codes)
        self._parse_output = parse_output
        self._temporary_root = str(temporary_root) if temporary_root is not None else None

    def _digest(self) -> bytes:
        with open(self._executable, "rb") as stream:
            return hashlib.file_digest(stream, "sha256").digest()

    def _arguments(self, arguments: Mapping[str, Any]) -> tuple[str, ...]:
        if not isinstance(arguments, Mapping) or set(arguments) - self._options.keys():
            raise ToolInvocationError("CLI_ARGUMENTS_REJECTED", outcome="failed", stopped=True)
        output = []
        for key, value in arguments.items():
            if isinstance(value, bool):
                if value:
                    output.append(self._options[key])
            elif (type(value) in {str, int, float} and len(str(value)) <= 8192
                  and "\0" not in str(value) and (not isinstance(value, float) or math.isfinite(value))):
                output.append(self._options[key] + "=" + str(value))
            else:
                raise ToolInvocationError("CLI_ARGUMENTS_REJECTED", outcome="failed", stopped=True)
        return tuple(output)

    @staticmethod
    def _environment(root: Path) -> dict[str, str]:
        # Do not copy os.environ: that imports host login, proxy, keychain and
        # interpreter injection settings. These paths are invocation-owned.
        result = {"PATH": os.defpath, "LANG": "C.UTF-8", "HOME": str(root / "home"),
                  "XDG_CONFIG_HOME": str(root / "home/.config"), "XDG_CACHE_HOME": str(root / "cache"),
                  "XDG_DATA_HOME": str(root / "data"), "XDG_STATE_HOME": str(root / "state"),
                  "XDG_RUNTIME_DIR": str(root / "runtime"), "TMPDIR": str(root / "tmp")}
        for key, value in result.items():
            if key not in {"PATH", "LANG"}:
                Path(value).mkdir(mode=0o700, parents=True, exist_ok=True)
        return result

    def _auth_arguments(self, root: Path) -> tuple[str, ...]:
        if self._credential.mode == "file":
            return (self._credential.file_argument + "=" + str(root / "credentials"),)
        if self._credential.mode == "home" and self._credential.home_argument:
            return (self._credential.home_argument + "=" + str(root / "home"),)
        return ()

    def _write_credential(self, root: Path, env: dict[str, str], lease: SecretLease) -> bytes:
        payload = self._credential.encode(lease)
        if not isinstance(payload, bytes) or not payload or len(payload) > 16384:
            raise ToolInvocationError("CLI_CREDENTIAL_FORMAT_REJECTED", outcome="failed", stopped=True)
        if self._credential.mode == "stdin":
            return payload
        if self._credential.mode == "environment":
            value = payload.decode("utf-8")
            if "\0" in value:
                raise ToolInvocationError("CLI_CREDENTIAL_FORMAT_REJECTED", outcome="failed", stopped=True)
            env[str(self._credential.environment_variable)] = value
            return b""
        destination = root / ("credentials" if self._credential.mode == "file"
                              else "home/" + self._credential.home_relative_path)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        return b""

    def _result(self, result: CLIProcessResult, lease: SecretLease) -> Any:
        # Inspect stderr too, including successful exits. Do not include raw
        # output, parse exceptions or matched credentials in errors or logs.
        reject_credential_echo(result.stdout.decode("utf-8", errors="replace"), lease)
        reject_credential_echo(result.stderr.decode("utf-8", errors="replace"), lease)
        value = self._parse_output(result.stdout)
        reject_credential_echo(value, lease)
        encoded = json.dumps(value, allow_nan=False).encode()
        if len(encoded) > self.descriptor.max_output_bytes:
            raise ValueError("CLI_OUTPUT_REJECTED")
        # Normalize parser results to plain JSON without retaining custom objects.
        return json.loads(encoded)

    async def invoke(self, invocation: ToolInvocation) -> Any:
        root: Path | None = None
        stopped, business_dispatched = True, False
        deadline = time.monotonic() + self.descriptor.timeout_seconds

        def check_authorized() -> None:
            if asyncio.get_running_loop().get_debug():
                raise ToolInvocationError("CLI_DEBUG_LOGGING_UNSAFE", outcome="failed", stopped=True)
            invocation.check_authorized()

        try:
            arguments = self._arguments(invocation.arguments)
            check_authorized()
            lease = invocation.resolve_credential()
            if not isinstance(lease, SecretLease):
                raise ToolInvocationError("CLI_CREDENTIAL_UNAVAILABLE", outcome="failed", stopped=True)
            check_authorized()
            root = Path(tempfile.mkdtemp(prefix="personal-cli-", dir=self._temporary_root))
            env = self._environment(root)
            auth_arguments = self._auth_arguments(root)

            def guard() -> None:
                check_authorized()
                if self._digest() != self._executable_digest:
                    raise ToolInvocationError("CLI_EXECUTABLE_CHANGED", outcome="failed")

            async def run(extra: tuple[str, ...], stdin: bytes, *, business: bool = False) -> CLIProcessResult:
                nonlocal stopped, business_dispatched
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ToolInvocationError("CLI_TIMEOUT", outcome="unknown" if business_dispatched else "failed")
                try:
                    result = await run_cli_process(executable=self._executable,
                        argv=(*self._fixed, *auth_arguments, *extra), env=env, cwd=root, stdin=stdin,
                        timeout_seconds=remaining, max_output_bytes=self.descriptor.max_output_bytes,
                        before_spawn=guard, check_authorized=check_authorized)
                    stopped = result.stopped
                    if business:
                        business_dispatched = result.dispatched
                    if not stopped:
                        raise ToolInvocationError("CLI_STOP_UNCONFIRMED", stopped=False)
                    return result
                except CLIProcessError as error:
                    stopped = error.stopped or not error.dispatched
                    if business:
                        business_dispatched = error.dispatched
                    raise
                except (Exception, asyncio.CancelledError):
                    # Only the process helper's typed result/error can prove
                    # whether dispatch happened and local custody was closed.
                    # An unexpected helper failure must not inherit stop proof
                    # from the preceding probe or permit credential deletion.
                    stopped = False
                    if business:
                        business_dispatched = True
                    raise ToolInvocationError("CLI_PROCESS_STATE_UNCONFIRMED",
                        outcome="unknown" if business else "failed", stopped=False) from None

            missing = await run(self._probe, b"")
            reject_credential_echo(missing.stdout.decode("utf-8", errors="replace"), lease)
            reject_credential_echo(missing.stderr.decode("utf-8", errors="replace"), lease)
            if missing.returncode not in self._unauthenticated_codes:
                raise ToolInvocationError("CLI_AMBIENT_AUTH_REJECTED", outcome="failed", stopped=True)
            # A failed probe can still write state; remove it before installing
            # the supplied lease so its cache cannot become the active identity.
            shutil.rmtree(root)
            root.mkdir(mode=0o700)
            env = self._environment(root)
            guard()
            stdin = self._write_credential(root, env, lease)
            probe = await run(self._probe, stdin)
            if probe.returncode != 0 or self._verify_identity(self._result(probe, lease), lease) is not True:
                raise ToolInvocationError("CLI_IDENTITY_REJECTED", outcome="failed", stopped=True)
            guard()
            result = await run(arguments, stdin, business=True)
            # An exit status cannot prove whether a remote mutation happened.
            value = self._result(result, lease)
            if result.returncode != 0:
                raise ToolInvocationError("CLI_COMMAND_FAILED", outcome="unknown", stopped=True)
            check_authorized()
            return value
        except ToolInvocationError as error:
            if business_dispatched:
                # Local process termination cannot prove that a CLI's remote
                # operation was cancelled. Preserve the original effect as
                # UNKNOWN even when credential cleanup is safe locally.
                raise ToolInvocationError(error.code, outcome="unknown", stopped=stopped) from None
            # Probes are registered read-only operations. Their process-level
            # uncertainty does not make an undispatched business effect UNKNOWN.
            # Keep local stop evidence separate: an unconfirmed probe still
            # retains its private directory, and cannot be reported cancelled.
            outcome = "cancelled" if error.outcome == "cancelled" and stopped else "failed"
            raise ToolInvocationError(error.code, outcome=outcome, stopped=stopped) from None
        except Exception:
            raise ToolInvocationError("CLI_INVOCATION_REJECTED",
                outcome="unknown" if business_dispatched else "failed", stopped=stopped) from None
        finally:
            # Never delete credentials out from under a process whose stop was
            # not proved, independently of whether business was dispatched.
            if root is not None and stopped:
                try:
                    shutil.rmtree(root)
                except FileNotFoundError:
                    pass
                except OSError:
                    raise ToolInvocationError("CLI_CREDENTIAL_CLEANUP_FAILED",
                        outcome="unknown" if business_dispatched else "failed", stopped=True) from None
