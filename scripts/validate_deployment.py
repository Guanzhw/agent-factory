#!/usr/bin/env python3
"""Config-only by default. No credential loading, deployment or exercise mode."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "platform"))

from agent_factory.deployment_validation import (MAX_MANIFEST_BYTES, collect_local_observations,
    parse_manifest, validate_manifest)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    read_only = "--read-only-local" in arguments
    if read_only:
        arguments.remove("--read-only-local")
    try:
        if len(arguments) != 1 or arguments[0].startswith("-"):
            raise ValueError()
        before = os.lstat(arguments[0])
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
            raise ValueError()
        descriptor = os.open(arguments[0], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            opened = os.fstat(descriptor)
            after = os.lstat(arguments[0])
            if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(after.st_mode)
                    or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
                    or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)):
                raise ValueError()
            raw = os.read(descriptor, MAX_MANIFEST_BYTES + 1)
        finally:
            os.close(descriptor)
        manifest = parse_manifest(raw)
        report = collect_local_observations(manifest) if read_only else validate_manifest(manifest)
    except Exception:
        # Paths, document values, OS errors and arbitrary flags never enter output.
        report = validate_manifest(None)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return {"PASS_CONFIG": 0, "FAIL": 2, "BLOCKED": 3, "UNSUPPORTED": 4}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
