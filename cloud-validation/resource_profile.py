#!/usr/bin/env python3
"""Strict, offline resource arithmetic. Passing is not runtime/capacity evidence."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
import sys
from typing import Any

MIB = 1_048_576
GB = 1_000_000_000
CPU_SCALE = 1_000_000
MAX_INPUT_BYTES = 1_048_576
MAX_TREE_DEPTH = 32
MAX_TREE_NODES = 4096
KINDS = frozenset({"runtime", "tool", "browser", "mcp", "experiment"})


class ProfileError(ValueError):
    """Invalid, incomplete, or overcommitted planning input."""


def _object(value: Any, required: set[str], path: str,
            optional: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise ProfileError(f"{path}: expected object")
    missing = required - value.keys()
    unknown = value.keys() - required - (optional or set())
    if missing:
        raise ProfileError(f"{path}: missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ProfileError(f"{path}: unknown fields: {', '.join(sorted(map(str, unknown)))}")
    return value


def _integer(value: Any, path: str, minimum: int = 1,
             maximum: int = 1_000_000_000) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProfileError(f"{path}: expected integer in [{minimum}, {maximum}]")
    return value


def _scaled(value: Any, scale: int, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ProfileError(f"{path}: expected finite positive number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ProfileError(f"{path}: expected finite positive number")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ProfileError(f"{path}: expected finite positive number") from exc
    if not number.is_finite() or number <= 0 or number > 1_000_000:
        raise ProfileError(f"{path}: must be finite, > 0 and <= 1000000")
    # Bound precision before doing arithmetic, including adversarial exponents.
    if number.as_tuple().exponent < -6:
        raise ProfileError(f"{path}: at most six decimal places supported")
    scaled = number * scale
    if scaled != scaled.to_integral_value():
        raise ProfileError(f"{path}: value is smaller than supported unit")
    return int(scaled)


def _name(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ProfileError(f"{path}: expected nonempty string of at most 120 characters")
    return value


@dataclass(frozen=True)
class Resources:
    cpu: int  # integer millionths of one CPU core
    memory: int  # bytes

    def __add__(self, other: Resources) -> Resources:
        return Resources(self.cpu + other.cpu, self.memory + other.memory)

    def times(self, count: int) -> Resources:
        return Resources(self.cpu * count, self.memory * count)

    def as_dict(self) -> dict:
        return {"cpu_cores": self.cpu / CPU_SCALE,
                "memory_bytes": self.memory, "memory_mib": self.memory / MIB}


def _resources(value: Any, path: str) -> Resources:
    value = _object(value, {"cpu_cores", "memory_mib"}, path)
    return Resources(_scaled(value["cpu_cores"], CPU_SCALE, f"{path}.cpu_cores"),
                     _integer(value["memory_mib"], f"{path}.memory_mib") * MIB)


def _fits(actual: Resources, limit: Resources, path: str) -> None:
    if actual.cpu > limit.cpu:
        raise ProfileError(f"{path}: CPU overcommit ({actual.cpu / CPU_SCALE:g} > "
                           f"{limit.cpu / CPU_SCALE:g} cores)")
    if actual.memory > limit.memory:
        raise ProfileError(f"{path}: memory overcommit ({actual.memory} > "
                           f"{limit.memory} bytes)")


def _process_tree(value: Any, path: str, names: set[str], depth: int,
                  by_kind: dict[str, Resources]) -> Resources:
    if depth > MAX_TREE_DEPTH:
        raise ProfileError(f"{path}: process tree exceeds depth {MAX_TREE_DEPTH}")
    value = _object(value, {"name", "kind", "state", "reservation", "children"},
                    path, {"subtree_budget"})
    name = _name(value["name"], f"{path}.name")
    if name in names:
        raise ProfileError(f"{path}: duplicate process name {name!r}")
    names.add(name)
    if len(names) > MAX_TREE_NODES:
        raise ProfileError(f"{path}: too many process nodes")
    if not isinstance(value["kind"], str) or value["kind"] not in KINDS:
        raise ProfileError(f"{path}.kind: expected one of {', '.join(sorted(KINDS))}")
    if value["state"] not in ("running", "waiting"):
        raise ProfileError(f"{path}.state: expected running or waiting")
    if not isinstance(value["children"], list):
        raise ProfileError(f"{path}.children: expected list")
    own = _resources(value["reservation"], f"{path}.reservation")
    by_kind[value["kind"]] = by_kind[value["kind"]] + own
    total = own
    for index, child in enumerate(value["children"]):
        total += _process_tree(child, f"{path}.children[{index}]", names,
                               depth + 1, by_kind)
    if "subtree_budget" in value:
        _fits(total, _resources(value["subtree_budget"], f"{path}.subtree_budget"),
              f"{path}.subtree_budget")
    return total


def validate_profile(profile: Any) -> dict:
    """Validate strict schema and all planned grants, without creating resources.

    Each process reservation is its OWN cost. A subtree budget is a shared cap,
    never another grant. Host admission charges worker tree budgets, not only
    the currently enumerated processes. Waiting costs exactly as much as running.
    """
    profile = _object(profile, {"schema_version", "name", "purpose", "runtime",
                                 "host", "reserved", "workers"}, "profile")
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ProfileError("profile.schema_version: expected 1")
    name = _name(profile["name"], "profile.name")
    if profile["purpose"] != "synthetic-planning-example":
        raise ProfileError("profile.purpose: expected synthetic-planning-example")
    runtime = _object(profile["runtime"], {"engine", "version", "persistence",
                                          "remote_compute_separate"}, "runtime")
    if runtime != {"engine": "agno-agentos", "version": "3.1.0",
                   "persistence": "postgresql", "remote_compute_separate": True}:
        raise ProfileError("runtime: expected Agno AgentOS 3.1.0, PostgreSQL, "
                           "and separate remote compute")
    if type(runtime["remote_compute_separate"]) is not bool:
        raise ProfileError("runtime.remote_compute_separate: expected true boolean")
    host = _object(profile["host"], {"cpu_cores", "memory_gb"}, "host")
    host_limit = Resources(_scaled(host["cpu_cores"], CPU_SCALE, "host.cpu_cores"),
                           _scaled(host["memory_gb"], GB, "host.memory_gb"))
    reserved = _object(profile["reserved"], {"os", "postgres", "control"}, "reserved")
    reserved_by_role = {role: _resources(value, f"reserved.{role}")
                        for role, value in reserved.items()}
    base = sum(reserved_by_role.values(), Resources(0, 0))
    _fits(base, host_limit, "host infrastructure reservations")
    if not isinstance(profile["workers"], list) or not profile["workers"]:
        raise ProfileError("workers: expected nonempty list")
    worker_names: set[str] = set()
    all_kinds = {kind: Resources(0, 0) for kind in sorted(KINDS)}
    grants = Resources(0, 0)
    inventory = Resources(0, 0)
    workers = []
    for index, worker in enumerate(profile["workers"]):
        path = f"workers[{index}]"
        worker = _object(worker, {"name", "replicas", "tree_budget", "process_tree"}, path)
        worker_name = _name(worker["name"], f"{path}.name")
        if worker_name in worker_names:
            raise ProfileError(f"{path}: duplicate worker name {worker_name!r}")
        worker_names.add(worker_name)
        replicas = _integer(worker["replicas"], f"{path}.replicas", maximum=1_000_000)
        budget = _resources(worker["tree_budget"], f"{path}.tree_budget")
        kinds = {kind: Resources(0, 0) for kind in KINDS}
        names: set[str] = set()
        actual = _process_tree(worker["process_tree"], f"{path}.process_tree", names, 0, kinds)
        if worker["process_tree"]["kind"] != "runtime":
            raise ProfileError(f"{path}.process_tree.kind: root must be runtime")
        _fits(actual, budget, f"{path}.tree_budget")
        grants += budget.times(replicas)
        inventory += actual.times(replicas)
        for kind, resources in kinds.items():
            all_kinds[kind] += resources.times(replicas)
        workers.append({"name": worker_name, "replicas": replicas,
                        "processes_per_replica": len(names),
                        "tree_budget_per_replica": budget.as_dict(),
                        "process_inventory_per_replica": actual.as_dict()})
    _fits(base + grants, host_limit, "host infrastructure + all worker tree grants")
    total = base + grants
    return {"valid": True, "name": name, "evidence_level": "synthetic-arithmetic-only",
            "capacity_claim": False, "runtime_verified": False,
            "host": host_limit.as_dict(),
            "reserved": {k: v.as_dict() for k, v in reserved_by_role.items()},
            "worker_tree_grants": grants.as_dict(), "process_inventory": inventory.as_dict(),
            "process_inventory_by_kind": {k: v.as_dict() for k, v in all_kinds.items()},
            "total_reserved": total.as_dict(),
            "unallocated": Resources(host_limit.cpu - total.cpu,
                                       host_limit.memory - total.memory).as_dict(),
            "workers": workers,
            "warning": "Planning arithmetic only; no measured concurrency, throughput, "
                       "deployment settings, live runtime compatibility, or enforced limits."}


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _no_constant(value: str) -> None:
    raise ProfileError(f"non-finite JSON number: {value}")


def load_json(path: Path) -> Any:
    try:
        # Limit actual bytes read, including files that change after stat().
        with path.open("rb") as stream:
            contents = stream.read(MAX_INPUT_BYTES + 1)
        if len(contents) > MAX_INPUT_BYTES:
            raise ProfileError(f"input exceeds {MAX_INPUT_BYTES} bytes")
        return json.loads(contents.decode("utf-8"), parse_float=Decimal,
                          object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ProfileError(f"cannot read valid JSON from {path.name}: {exc}") from exc


def check_observed_capacity(report: dict, observation: Any) -> dict:
    """Compare nominal host plan with operator-supplied effective limits, read-only.

    Observation is deliberately external input, not a claim this CLI surveyed the
    deployment. No SSH, cloud APIs, provisioning, credentials, or process launching.
    """
    observation = _object(observation, {"cpu_cores", "memory_bytes", "source"}, "capacity")
    source = _name(observation["source"], "capacity.source")
    available = Resources(_scaled(observation["cpu_cores"], CPU_SCALE, "capacity.cpu_cores"),
                          _integer(observation["memory_bytes"], "capacity.memory_bytes",
                                   maximum=1_000_000 * GB))
    requested = Resources(_scaled(report["host"]["cpu_cores"], CPU_SCALE, "host.cpu_cores"),
                          report["host"]["memory_bytes"])
    _fits(requested, available, "planned host versus observed effective capacity")
    return {"fits_observation": True, "source": source, "observed": available.as_dict(),
            "warning": "Operator-supplied snapshot only; this does not measure spare "
                       "capacity, enforcement, runtime performance, or concurrent tenants."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path, help="strict synthetic planning JSON profile")
    parser.add_argument("--capacity", type=Path,
                        help="optional sanitized JSON snapshot of effective existing-host limits")
    args = parser.parse_args(argv)
    try:
        report = validate_profile(load_json(args.profile))
        if args.capacity:
            report["capacity_check"] = check_observed_capacity(report, load_json(args.capacity))
    except ProfileError as exc:
        print(json.dumps({"valid": False, "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
