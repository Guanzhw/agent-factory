"""Finite retrieval failure facts; never inspect command text or infer transport causes."""
from __future__ import annotations

from typing import Any

from .openresearch import CommandResult, OpenResearchError

STAGES = frozenset({"discover", "paper", "text"})
FAILURE_CLASSES = {
    "COMMAND_FAILED": "command-exit",
    "TIMEOUT": "deadline",
    "OUTPUT_LIMIT": "output-bound",
}


def safe_retrieval_diagnostic(error: object, stage: object) -> dict[str, Any]:
    """Extract exact-type bounded fields; UNKNOWN never means a successful call.

    CLI stderr, stdout, argv, exception text and causal chains are intentionally
    untouched. A command failure alone cannot establish DNS/TLS/proxy failure.
    Historical records must not be backfilled with guessed diagnoses.
    """
    if type(stage) is not str or stage not in STAGES:
        raise ValueError("Unsupported retrieval diagnostic stage")
    result: dict[str, Any] = {"schema": 1, "stage": stage, "code": "UNKNOWN",
                              "failureClass": "unknown", "transportCause": "UNKNOWN"}
    if type(error) is not OpenResearchError:
        return result
    # Exact types plus direct instance dictionaries bypass overridden properties,
    # __getattribute__, str/repr, and dict-subclass get hooks.
    fields = object.__getattribute__(error, "__dict__")
    code = dict.get(fields, "code")
    if type(code) is str and code in FAILURE_CLASSES:
        result.update(code=code, failureClass=FAILURE_CLASSES[code])
    command = dict.get(fields, "result")
    if type(command) is CommandResult:
        command_fields = object.__getattribute__(command, "__dict__")
        exit_code = dict.get(command_fields, "returncode")
        if type(exit_code) is int and -255 <= exit_code <= 255:
            result["exitCode"] = exit_code
    return result
