#!/usr/bin/env python3
"""Offline subprocess fixture for personal CLI adapter tests; synthetic data only.

Credentials are JSON {"username": "synthetic-alice", "password":
"synthetic-token-alice"}. The public account is "alice", never the password.
Success includes credentialSource. --probe emits only account/credentialSource
after the same credential validation, without business work or fault injection.

  --credential-source stdin              read one bounded JSON document on stdin
  --credential-source file --credentials-file PATH
  --credential-source environment         read PERSONAL_CLI_FIXTURE_CREDENTIALS
  --credential-source home --fixture-home PATH
      require HOME == PATH and read PATH/.config/personal-cli-fixture/credentials.json

Credentials are read only from the explicitly selected source. HOME is inspected
only after an explicit fixture-home argument; the child receives an empty environment.
--unsafe-host-fallback deliberately succeeds without credentials using a fixed
synthetic account, so adapter probes can demonstrate rejection of unsafe tools.

--cache-file PATH uses PATH.active as an exclusive overlap detector and increments
the public JSON count on completion; it deliberately does not serialize callers.
--state-file PATH publishes PID, optional child PID and running/completed phase.
--spawn-child starts a same-process-group child. --ignore-sigterm makes both
processes ignore SIGTERM; cancellation tests must clean up the entire group.
Normal completion reaps the child. Every child also has a bounded lifetime.

Exit codes: 0 success; 2 invalid arguments; 75 concurrent cache access;
77 missing/invalid synthetic credentials; 74 fixture file I/O failure.
--leak stdout|stderr|both and --exit-code deliberately exercise failure handling.
--probe-account/--probe-source inject synthetic attestation mismatches.
--inspect-runtime reports only private paths, modes and environment variable names.
--effect-file PATH with business --write-effect appends a synthetic external effect
before the delay; killing the local process does not undo that marker.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time


MAX_CREDENTIAL_BYTES = 8192
HOME_CONFIG = Path(".config/personal-cli-fixture/credentials.json")


class CredentialRejected(Exception):
    pass


class CredentialMissing(CredentialRejected):
    pass


def duration(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 <= seconds <= 120:
        raise argparse.ArgumentTypeError("duration must be between 0 and 120 seconds")
    return seconds


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-source", choices=("stdin", "file", "home", "environment"), default="stdin")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--probe-account", choices=("other-account",))
    parser.add_argument("--probe-source", choices=("stdin", "file", "home", "environment"))
    parser.add_argument("--credentials-file", type=Path)
    parser.add_argument("--fixture-home", type=Path)
    parser.add_argument("--value", default="fixture-ok")
    parser.add_argument("--delay-seconds", type=duration, default=0.0)
    parser.add_argument("--cache-file", type=Path)
    parser.add_argument("--state-file", type=Path)
    parser.add_argument("--inspect-runtime", action="store_true")
    parser.add_argument("--effect-file", type=Path)
    parser.add_argument("--write-effect", action="store_true")
    parser.add_argument("--unsafe-host-fallback", action="store_true")
    parser.add_argument("--leak", choices=("stdout", "stderr", "both"))
    parser.add_argument("--exit-code", type=int, choices=range(126), default=0)
    parser.add_argument("--spawn-child", action="store_true")
    parser.add_argument("--ignore-sigterm", action="store_true")
    parser.add_argument("--child-lifetime-seconds", type=duration, default=60.0)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if len(args.value) > 1024:
        parser.error("value is too long")
    if args.credentials_file is not None and args.credential_source != "file":
        parser.error("credentials-file requires credential-source file")
    return args


def credential_document(args: argparse.Namespace) -> bytes:
    if args.credential_source == "stdin":
        return sys.stdin.buffer.read(MAX_CREDENTIAL_BYTES + 1)
    if args.credential_source == "environment":
        return os.environ.get("PERSONAL_CLI_FIXTURE_CREDENTIALS", "").encode("utf-8")
    if args.credential_source == "file":
        path = args.credentials_file
        if path is None:
            raise CredentialMissing()
    else:
        # No expanduser(), default HOME, XDG configuration or environment-token
        # fallback: home mode must name the isolated synthetic fixture directory.
        if args.fixture_home is None:
            raise CredentialMissing()
        home = args.fixture_home.resolve()
        if os.environ.get("HOME") != str(home):
            raise CredentialRejected()
        path = home / HOME_CONFIG
    try:
        with path.open("rb") as stream:
            return stream.read(MAX_CREDENTIAL_BYTES + 1)
    except FileNotFoundError:
        raise CredentialMissing() from None
    except OSError:
        raise CredentialRejected() from None


def credentials(args: argparse.Namespace) -> tuple[str, str]:
    try:
        raw = credential_document(args)
        if not raw.strip():
            raise CredentialMissing()
    except CredentialMissing:
        if args.unsafe_host_fallback:
            return "host-fallback", "synthetic-host-fallback-token"
        raise
    try:
        value = json.loads(raw)
        if len(raw) > MAX_CREDENTIAL_BYTES or not isinstance(value, dict):
            raise CredentialRejected()
        username, password = value.get("username"), value.get("password")
        if (not isinstance(username, str) or not re.fullmatch(r"synthetic-[a-zA-Z0-9_.-]{1,80}", username)
                or not isinstance(password, str) or not re.fullmatch(r"synthetic-[a-zA-Z0-9_.:-]{1,200}", password)):
            raise CredentialRejected()
        return username.removeprefix("synthetic-"), password
    except (ValueError, TypeError):
        raise CredentialRejected() from None


def write_state(path: Path | None, account: str, phase: str, child: subprocess.Popen | None) -> None:
    if path is not None:
        path.write_text(json.dumps({"pid": os.getpid(), "childPid": child.pid if child else None,
            "account": account, "phase": phase}) + "\n", encoding="utf-8")


def start_child(args: argparse.Namespace) -> subprocess.Popen:
    command = [sys.executable, "-I", str(Path(__file__).resolve()), "--child",
        "--delay-seconds", str(args.child_lifetime_seconds)]
    if args.ignore_sigterm:
        command.append("--ignore-sigterm")
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env={}, text=True)
    # The marker is emitted after installing signal behavior, so the state file
    # never claims the cancellation target is ready before its child is ready.
    if child.stdout is None or child.stdout.readline().strip() != "fixture-child-ready":
        child.kill()
        child.wait()
        raise OSError("child startup failed")
    child.stdout.close()
    return child


def stop_child(child: subprocess.Popen | None) -> None:
    if child is None:
        return
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            child.kill()
    child.wait()


def run(args: argparse.Namespace, account: str, password: str) -> int:
    child = None
    active_path = None
    count = None
    try:
        if args.write_effect:
            if args.effect_file is None:
                raise OSError("effect fixture requires its trusted destination")
            with args.effect_file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"account": account, "value": args.value}) + "\n")
        if args.cache_file is not None:
            active_path = Path(str(args.cache_file) + ".active")
            try:
                descriptor = os.open(active_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                active_path = None  # The marker belongs to the other invocation.
                print('{"error":"CACHE_CONCURRENT_ACCESS"}', file=sys.stderr, flush=True)
                return 75
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(str(os.getpid()))
            previous = json.loads(args.cache_file.read_text(encoding="utf-8")) if args.cache_file.exists() else {}
            count = previous.get("count", 0) + 1
        if args.spawn_child:
            child = start_child(args)
        write_state(args.state_file, account, "running", child)
        time.sleep(args.delay_seconds)
        output = {"account": account, "credentialSource": args.credential_source, "value": args.value}
        if args.inspect_runtime:
            cwd = Path.cwd()
            credential = (args.credentials_file if args.credential_source == "file" else
                args.fixture_home / HOME_CONFIG if args.credential_source == "home" else None)
            output["runtime"] = {"cwd": str(cwd), "rootMode": cwd.stat().st_mode & 0o777,
                "environmentNames": sorted(os.environ),
                "home": os.environ.get("HOME"), "tmpdir": os.environ.get("TMPDIR"),
                "credentialMode": credential.stat().st_mode & 0o777 if credential else None}
        if count is not None:
            output["cacheCount"] = count
            args.cache_file.write_text(json.dumps({"count": count, "account": account}) + "\n", encoding="utf-8")
        if args.leak in {"stdout", "both"}:
            output["token"] = password
        if args.leak in {"stderr", "both"}:
            print("fixture-token=" + password, file=sys.stderr, flush=True)
        write_state(args.state_file, account, "completed", child)
        print(json.dumps(output), flush=True)
        return args.exit_code
    finally:
        stop_child(child)
        if active_path is not None:
            active_path.unlink(missing_ok=True)


def main() -> int:
    args = arguments()
    if args.ignore_sigterm:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if args.child:
        print("fixture-child-ready", flush=True)
        time.sleep(args.delay_seconds)
        return 0
    try:
        account, password = credentials(args)
    except CredentialRejected:
        print('{"error":"SYNTHETIC_CREDENTIAL_REQUIRED"}', file=sys.stderr, flush=True)
        return 77
    if args.probe:
        print(json.dumps({"account": args.probe_account or account,
            "credentialSource": args.probe_source or args.credential_source}), flush=True)
        return 0
    try:
        return run(args, account, password)
    except (OSError, ValueError, TypeError):
        print('{"error":"FIXTURE_IO_FAILURE"}', file=sys.stderr, flush=True)
        return 74


if __name__ == "__main__":
    raise SystemExit(main())
