"""Run a public-code development example from an operator-acquired live snapshot.

The snapshot is data, not authorization. Existing Go campaign policy governs calls.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import logging
from pathlib import Path

from agent_factory.go_diagnostics import safe_diagnostic
from agent_factory.public_code_knowledge import validate_snapshot
from run_go_project_workflow import MODELS, require, run


def load_snapshot(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(65537)
    require(len(raw) <= 65536)
    snapshot = json.loads(raw)
    require(snapshot["evidenceMode"] == "live-public-fetch")
    for source in snapshot["sources"]:
        source["content"] = source["content"].encode("utf-8")
    validate_snapshot(snapshot)
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("campaign", "evidence-directory", "database-url", "snapshot"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--model", choices=MODELS, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            result = run(args, research_snapshot=load_snapshot(args.snapshot))
        except BaseException as error:
            result = {"status": "stopped", "diagnostic": safe_diagnostic("RUNNER_FAILED", error=error)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
