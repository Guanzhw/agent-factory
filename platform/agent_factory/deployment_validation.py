"""Non-secret deployment declarations and opt-in, read-only local observations.

This module never constructs Settings, opens a database, sends network requests,
loads credentials, launches a process, or writes to a delegated cgroup.
"""
from __future__ import annotations

import json
import math
import os
import re
import stat
from typing import Any, cast
from urllib.parse import urlsplit

from .browser_oidc import BrowserOIDCConfig
from .delegated_cgroup_fs import DelegatedCgroupConfig, LinuxDelegatedCgroupFS
from .material_governance import GovernanceConfig
from .oidc_identity import OIDCAccessTokenVerifier, OIDCIdentityConfig
from .plan_policy import PlanPolicyConfig
from .process_enforcement import ProcessLimits
from .resources import ComputePool

MAX_MANIFEST_BYTES = 65536
ROOT_FIELDS = {"schema", "deploymentId", "configurationRevision", "targetHost", "identity",
               "runtimeAttachment", "computeBackend", "policy"}
_SECRET = re.compile(r"^(?:api_?key|secret|password|authorization|cookie|credential(?:s)?|private_?key|client_?secret|jwt_?key|access_?token|refresh_?token)$", re.I)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z")


class ValidationInputError(ValueError):
    def __init__(self):
        super().__init__("MANIFEST_INPUT_INVALID")


def _require(value):
    if not value:
        raise ValidationInputError()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _bounded(value, depth=0):
    _require(depth <= 12)
    if type(value) is dict:
        _require(len(value) <= 128)
        for key, child in value.items():
            _require(type(key) is str and len(key) <= 128 and (not _SECRET.fullmatch(key)
                     or key == "accessToken" and type(child) in {dict, type(None)}))
            _bounded(child, depth + 1)
    elif type(value) is list:
        _require(len(value) <= 1024)
        for child in value:
            _bounded(child, depth + 1)
    elif type(value) is str:
        _require(len(value) <= 4096 and all(ord(c) >= 32 for c in value))
    else:
        _require(type(value) in {int, float, bool, type(None)})
        if type(value) in {int, float}:
            _require(math.isfinite(value) and abs(value) <= 2**53)


def parse_manifest(raw: bytes | str) -> dict[str, Any]:
    try:
        _require(type(raw) in {bytes, str})
        encoded = raw.encode("utf-8") if type(raw) is str else raw
        _require(len(encoded) <= MAX_MANIFEST_BYTES)
        value = json.loads(encoded, object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValidationInputError()))
        _bounded(value)
        _require(type(value) is dict and set(value) == ROOT_FIELDS and type(value["schema"]) is int and value["schema"] == 1)
        return value
    except Exception:
        raise ValidationInputError() from None


def _fields(value, fields):
    _require(type(value) is dict and set(value) == set(fields))


def _identifier(value):
    _require(type(value) is str and _ID.fullmatch(value) is not None)


def _integer(value, low, high):
    _require(type(value) is int and low <= value <= high)


def _https(value):
    _require(type(value) is str and value.isascii() and "\\" not in value and not any(c.isspace() for c in value))
    parsed = urlsplit(value)
    _require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
             and not parsed.query and not parsed.fragment and (parsed.port is None or 1 <= parsed.port <= 65535))


def _mapping(value, fields):
    _require(type(value) is list and 1 <= len(value) <= 1024)
    seen = set()
    for raw_row in value:
        row = cast(dict[str, Any], raw_row)
        _fields(row, fields)
        for key in fields:
            _require(type(row[key]) is str and 1 <= len(row[key]) <= 512)
        identity = tuple(row[key] for key in fields[:-1])
        _require(identity not in seen)
        seen.add(identity)
    return value


def _identity_config(value, browser):
    common = {"issuer", "jwks", "subjectOwners", "clockSkewSeconds", "maxTokenLifetimeSeconds"}
    fields = common | ({"authorizationEndpoint", "tokenEndpoint", "clientId", "redirectUri", "maxAuthAgeSeconds"}
                       if browser else {"audience"})
    _fields(value, fields)
    owners = _mapping(value["subjectOwners"], ("issuer", "subject", "owner"))
    arguments: dict[str, Any] = dict(issuer=value["issuer"], jwks=value["jwks"],
        subject_owners={(row["issuer"], row["subject"]): row["owner"] for row in owners},
        clock_skew_seconds=value["clockSkewSeconds"], max_token_lifetime_seconds=value["maxTokenLifetimeSeconds"])
    if browser:
        BrowserOIDCConfig(**arguments, authorization_endpoint=value["authorizationEndpoint"],
            token_endpoint=value["tokenEndpoint"], client_id=value["clientId"], redirect_uri=value["redirectUri"],
            max_auth_age_seconds=value["maxAuthAgeSeconds"])
    else:
        OIDCAccessTokenVerifier(OIDCIdentityConfig(**arguments, audience=value["audience"]))


def _check_host(value):
    _fields(value, {"platform", "expectedCpuCount", "expectedMemoryBytes"})
    _require(value["platform"] == "linux")
    _integer(value["expectedCpuCount"], 1, 65536)
    _integer(value["expectedMemoryBytes"], 1, 2**53)


def _check_identity(value):
    _fields(value, {"accessToken", "browserLogin"})
    for key, browser in (("accessToken", False), ("browserLogin", True)):
        if value[key] is not None:
            _identity_config(value[key], browser)


def _check_runtime(value):
    if value == {"kind": "none"}:
        return
    _fields(value, {"kind", "httpsBaseUrl", "expectedAgnoVersion", "executorId", "configurationRevision", "ownerMapping"})
    _require(value["kind"] == "native-agno" and value["expectedAgnoVersion"] == "3.1.0")
    _https(value["httpsBaseUrl"])
    _identifier(value["executorId"])
    _identifier(value["configurationRevision"])
    _mapping(value["ownerMapping"], ("originOwner", "receiverOwner"))


def _pool(value):
    _fields(value, {"poolId", "cpu", "memoryMb", "diskMb", "maxLeases", "maxOwnerLeases"})
    return ComputePool(value["poolId"], value["cpu"], value["memoryMb"], value["diskMb"],
                       max_leases=value["maxLeases"], max_owner_leases=value["maxOwnerLeases"])


def _check_compute(value):
    if value == {"kind": "none"}:
        return
    fields = {"kind", "configurationRevision", "owners", "pool", "limits"}
    kind = value.get("kind") if type(value) is dict else None
    _fields(value, fields | ({"delegatedCgroupPath", "rootDevice", "rootInode", "bootId"} if kind == "delegated-cgroup-v2" else set()))
    _require(kind in {"cooperative-process", "delegated-cgroup-v2"})
    _identifier(value["configurationRevision"])
    owners = value["owners"]
    _require(type(owners) is list and 1 <= len(owners) <= 1024)
    for owner in owners:
        _require(type(owner) is str and 1 <= len(owner) <= 200 and all(ord(char) >= 32 and ord(char) != 127 for char in owner))
    _require(len(set(owners)) == len(owners))
    pool = _pool(value["pool"])
    limits = value["limits"]
    if kind == "cooperative-process":
        _fields(limits, {"cpuSeconds", "addressSpaceMb", "fileSizeBytes", "wallSeconds"})
        ProcessLimits(cpu_seconds=limits["cpuSeconds"], address_space_mb=limits["addressSpaceMb"],
                      file_size_bytes=limits["fileSizeBytes"], wall_seconds=limits["wallSeconds"])
        _require(limits["addressSpaceMb"] <= pool.memory_mb and math.ceil(limits["fileSizeBytes"] / (1024*1024)) <= pool.disk_mb)
    else:
        delegated = _delegated_config(value)
        _require(delegated.cpu_quota_us <= pool.cpu * delegated.cpu_period_us
                 and delegated.memory_bytes <= pool.memory_mb * 1024 * 1024)


def _delegated_config(value):
    limits = value["limits"]
    _fields(limits, {"cpuQuotaMicros", "cpuPeriodMicros", "memoryMaxBytes", "swapMaxBytes", "pidsMax"})
    return DelegatedCgroupConfig(root_path=value["delegatedCgroupPath"], root_device=value["rootDevice"],
        root_inode=value["rootInode"], boot_id=value["bootId"], cpu_quota_us=limits["cpuQuotaMicros"],
        cpu_period_us=limits["cpuPeriodMicros"], memory_bytes=limits["memoryMaxBytes"],
        swap_bytes=limits["swapMaxBytes"], pids_max=limits["pidsMax"])


def _check_policy(value):
    _fields(value, {"temporaryPolicy", "materialReviewMode", "policyRevision", "materialPolicyRevision",
                    "runtimeToolContract", "maxWorkers", "planReviewTtlSeconds"})
    _require(value["temporaryPolicy"] in {"admin-review", "read-only-auto"}
             and value["materialReviewMode"] == "separate-admin")
    _integer(value["maxWorkers"], 1, 4)
    PlanPolicyConfig(name=value["temporaryPolicy"], revision=value["policyRevision"],
        review_ttl_seconds=value["planReviewTtlSeconds"], tool_contract=value["runtimeToolContract"])
    GovernanceConfig(review_mode=value["materialReviewMode"], revision=value["materialPolicyRevision"],
                     tool_contract=value["runtimeToolContract"])


def _issue(section, code, status, scope="configuration"):
    return {"section": section, "code": code, "status": status, "scope": scope}


def _report(checks, mode="config-only"):
    failed = any(row["status"] == "FAIL" for row in checks)
    blocked = any(row["status"] == "BLOCKED" for row in checks)
    unsupported = any(row["status"] == "UNSUPPORTED" for row in checks)
    return {"schema": 1, "mode": mode, "status": "FAIL" if failed else "UNSUPPORTED" if unsupported else "BLOCKED" if blocked else "PASS_CONFIG",
        "configurationValid": not any(row["scope"] == "configuration" and row["status"] != "PASS_CONFIG" for row in checks),
        "productionAccepted": False, "networkAttempted": False, "hostChangesPerformed": False, "checks": checks}


def validate_manifest(data: Any) -> dict[str, Any]:
    try:
        # A JSON round-trip also rejects object instances/cycles and bounds the
        # direct Python API exactly like CLI input. Never serialize in a report.
        value = parse_manifest(json.dumps(data, allow_nan=False, ensure_ascii=False))
    except Exception:
        return _report([_issue("manifest", "MANIFEST_INPUT_INVALID", "FAIL")])
    checks = []
    for key in ("deploymentId", "configurationRevision"):
        try:
            if value[key] is None:
                checks.append(_issue("manifest", "DEPLOYMENT_METADATA_MISSING", "BLOCKED"))
            else:
                _identifier(value[key])
        except Exception:
            checks.append(_issue("manifest", "DEPLOYMENT_METADATA_INVALID", "FAIL"))
    validators = (("targetHost", _check_host, "HOST"), ("identity", _check_identity, "IDENTITY"),
                  ("runtimeAttachment", _check_runtime, "RUNTIME"), ("computeBackend", _check_compute, "COMPUTE"),
                  ("policy", _check_policy, "POLICY"))
    for section, validator, code in validators:
        item = value[section]
        if item is None:
            checks.append(_issue(section, code + "_INPUT_MISSING", "BLOCKED"))
            continue
        try:
            validator(item)
        except Exception:
            checks.append(_issue(section, code + "_CONFIG_INVALID", "FAIL"))
            continue
        if section == "identity" and item == {"accessToken": None, "browserLogin": None}:
            checks.append(_issue(section, "IDENTITY_INPUT_MISSING", "BLOCKED"))
            continue
        checks.append(_issue(section, code + "_CONFIG_VALID", "PASS_CONFIG"))
        if section == "identity":
            checks.append(_issue(section, "IDENTITY_TLS_AND_SQL_MAPPING_UNVERIFIED", "BLOCKED", "acceptance"))
        elif section == "runtimeAttachment" and item["kind"] != "none":
            checks.append(_issue(section, "RUNTIME_AUTH_VERSION_EXECUTOR_UNVERIFIED", "BLOCKED", "acceptance"))
        elif section == "computeBackend" and item["kind"] != "none":
            checks.append(_issue(section, "COMPUTE_BACKEND_NOT_VERIFIED", "BLOCKED", "acceptance"))
            if item["kind"] == "cooperative-process":
                checks.append(_issue(section, "AGGREGATE_ISOLATION_NOT_PROVIDED", "UNSUPPORTED", "acceptance"))
        elif section == "targetHost":
            checks.append(_issue(section, "TARGET_CAPACITY_NOT_ACCEPTED", "BLOCKED", "acceptance"))
    return _report(checks)


def _read_public_file(path: str) -> str:
    # Fixed public proc/cgroup metadata only. No arbitrary path traversal,
    # symlink following, environment credentials or readability probes.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW") | getattr(os, "O_NONBLOCK"))
    try:
        _require(stat.S_ISREG(os.fstat(descriptor).st_mode))
        data = os.read(descriptor, 65537)
        _require(len(data) <= 65536)
        return data.decode("ascii")
    finally:
        os.close(descriptor)


def collect_local_observations(data: Any) -> dict[str, Any]:
    report = validate_manifest(data)
    checks = list(report["checks"])
    if not report["configurationValid"]:
        checks.append(_issue("localHost", "LOCAL_OBSERVATION_REQUIRES_VALID_CONFIG", "BLOCKED", "local-observation"))
        return _report(checks, "read-only-local")
    if os.name != "posix" or not hasattr(os, "uname") or os.uname().sysname != "Linux":
        checks.append(_issue("localHost", "LOCAL_PLATFORM_UNSUPPORTED", "UNSUPPORTED", "local-observation"))
        return _report(checks, "read-only-local")
    try:
        memory = _read_public_file("/proc/meminfo")
        match = re.search(r"^MemTotal:\s+([0-9]+) kB$", memory, re.M)
        _require(match is not None)
        assert match is not None
        total_bytes = int(match.group(1)) * 1024
        cpus = len(os.sched_getaffinity(0))
        expected = data["targetHost"]
        sufficient = cpus >= expected["expectedCpuCount"] and total_bytes >= expected["expectedMemoryBytes"]
        checks.append(_issue("localHost", "LOCAL_DECLARED_SIZE_OBSERVED" if sufficient else "LOCAL_DECLARED_SIZE_NOT_MET",
                             "PASS_OBSERVATION" if sufficient else "BLOCKED", "local-observation"))
        checks.append(_issue("localHost", "LOCAL_OBSERVATION_IS_NOT_TARGET_ACCEPTANCE", "BLOCKED", "acceptance"))
    except Exception:
        checks.append(_issue("localHost", "LOCAL_METADATA_UNAVAILABLE", "BLOCKED", "local-observation"))
    compute = data["computeBackend"]
    if compute["kind"] == "delegated-cgroup-v2":
        # Existing descriptor-pinned validation only reads boot/root identity,
        # cgroup2 filesystem type and delegated controller prerequisites.
        try:
            LinuxDelegatedCgroupFS(_delegated_config(compute)).validate()
            checks.append(_issue("computeBackend", "CGROUP_DELEGATION_METADATA_OBSERVED",
                                 "PASS_OBSERVATION", "local-observation"))
        except Exception:
            checks.append(_issue("computeBackend", "CGROUP_METADATA_UNAVAILABLE", "BLOCKED", "local-observation"))
        checks.append(_issue("computeBackend", "CGROUP_WRITE_AUTHORITY_UNVERIFIED", "BLOCKED", "acceptance"))
    return _report(checks, "read-only-local")
