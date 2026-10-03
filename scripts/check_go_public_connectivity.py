"""One unauthenticated fixed-endpoint GET; no body, redirects, retries or inference."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
import logging
import os
import re
from pathlib import Path
import stat
import time

from agent_factory.go_connection_diagnostics import safe_connection_diagnostic
from agent_factory.go_http import open_go_client

URL = "https://opencode.ai/zen/go/v1/models"
USER_AGENT = "agent-factory-dev/0.1 (+https://github.com/Guanzhw/agent-factory)"
MARKER = "public-connectivity-attempt.json"
RESULT = "public-connectivity-result.json"


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_private(path, value):
    if os.name != "posix" or not getattr(os, "O_NOFOLLOW", 0):
        raise ValueError("Private POSIX evidence required")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW"), 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_stored(value, depth=0):
    # Inspect is read-only but still must not echo arbitrary edits to local files.
    keys = {"phase", "startedUtc", "finishedUtc", "timestampUtc", "method", "target", "execution",
            "phases", "httpStatus", "outcome", "diagnostic", "elapsedMilliseconds", "diagnosticPersistence",
            "category", "proxyErrorPresent", "safeCauses", "summary", "errorType", "errnoSymbol", "proxyStatus"}
    words = {"PREPARED", "DISPATCH_STARTED", "RESPONSE_HEADERS", "GET", "opencode-go-models",
             "public-connectivity", "HTTP_RESPONSE", "FAILED", "DNS", "TCP", "TLS", "PROXY", "TIMEOUT",
             "CONNECTION", "UNKNOWN", "CANCELLED", "gaierror", "SSLCertVerificationError", "SSLError",
             "ProxyError", "ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout",
             "TimeoutException", "TimeoutError", "ConnectionRefusedError", "ConnectionResetError",
             "ConnectionAbortedError", "BrokenPipeError", "OSError", "CancelledError", "ExceptionGroup",
             "BaseExceptionGroup", "UnknownError", "ECONNREFUSED", "ECONNRESET", "ECONNABORTED",
             "ETIMEDOUT", "ENETUNREACH", "EHOSTUNREACH", "EPIPE", "EACCES", "EPERM",
             "EAI_AGAIN", "EAI_NONAME", "EAI_FAIL", "EAI_NODATA",
             "Local connection diagnostics do not establish socket or server receipt."}
    if depth > 6:
        raise ValueError("Invalid stored connectivity evidence")
    if type(value) is dict:
        if not set(value).issubset(keys):
            raise ValueError("Invalid stored connectivity evidence")
        for child in value.values():
            validate_stored(child, depth + 1)
    elif type(value) is list:
        if len(value) > 8:
            raise ValueError("Invalid stored connectivity evidence")
        for child in value:
            validate_stored(child, depth + 1)
    elif type(value) is str:
        if value not in words and not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?\+00:00", value):
            raise ValueError("Invalid stored connectivity evidence")
    elif type(value) is bool:
        pass
    elif type(value) is int and 0 <= value <= 2147483647:
        pass
    else:
        raise ValueError("Invalid stored connectivity evidence")


def read_private(path):
    if os.name != "posix" or not getattr(os, "O_NOFOLLOW", 0):
        raise ValueError("Private POSIX evidence required")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise ValueError("Private evidence required")
        value = json.loads(handle.read(32769))
        validate_stored(value)
        return value


def inspect(directory):
    marker = read_private(directory / MARKER)
    result = read_private(directory / RESULT) if os.path.lexists(directory / RESULT) else None
    return {"execution": "inspection-only", "attempt": marker, "result": result,
            "outcome": "recorded" if result is not None else "UNKNOWN"}


async def probe(evidence_directory):
    directory = Path(evidence_directory).absolute()
    if os.path.lexists(directory / MARKER):
        return inspect(directory)
    # Any prior directory contents are evidence, never a fresh retry location.
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("A fresh empty evidence directory is required")
    started = utc()
    write_private(directory / MARKER, {"phase": "PREPARED", "startedUtc": started,
                                       "method": "GET", "target": "opencode-go-models"})
    began = time.monotonic()
    result = {"execution": "public-connectivity", "startedUtc": started,
              "method": "GET", "target": "opencode-go-models", "phases": ["PREPARED"]}
    try:
        async with asyncio.timeout(10):
            async with open_go_client(timeout=10) as client:
                write_private(directory / "dispatch-started.json", {"phase": "DISPATCH_STARTED", "timestampUtc": utc()})
                result["phases"].append("DISPATCH_STARTED")
                async with client.stream("GET", URL, headers={"User-Agent": USER_AGENT}) as response:
                    result["httpStatus"] = response.status_code
                    result["phases"].append("RESPONSE_HEADERS")
                    write_private(directory / "response-headers.json", {"phase": "RESPONSE_HEADERS", "timestampUtc": utc(),
                                                                      "httpStatus": response.status_code})
                    # Deliberately never consume response body or header values.
            result["outcome"] = "HTTP_RESPONSE"
    except BaseException as error:
        result["outcome"] = "FAILED"
        result["diagnostic"] = safe_connection_diagnostic(error)
    result["finishedUtc"] = utc()
    result["elapsedMilliseconds"] = round((time.monotonic() - began) * 1000)
    try:
        write_private(directory / RESULT, result)
    except BaseException as error:
        result["diagnosticPersistence"] = safe_connection_diagnostic(error)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-directory", required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            result = asyncio.run(probe(args.evidence_directory))
        except BaseException as error:
            result = {"outcome": "SETUP_FAILED", "diagnostic": safe_connection_diagnostic(error)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
