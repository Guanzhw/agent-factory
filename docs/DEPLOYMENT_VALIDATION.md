# Deployment declaration validation

This tool validates a **non-secret declaration**, not a deployed service. It does
not initialize Factory Settings, read environment credentials, open PostgreSQL,
contact an IdP/runtime, obtain tokens, launch processes, write cgroups, provision
resources or deploy services. There is no exercise mode.

Run from the repository using the pinned environment:

```sh
.venv/bin/python scripts/validate_deployment.py /operator/path/deployment.json
```

The default is config-only. Only this explicit option reads current-machine
metadata:

```sh
.venv/bin/python scripts/validate_deployment.py /operator/path/deployment.json --read-only-local
```

Current-machine observations are not observations of a selected remote target.
CPU affinity and `/proc/meminfo` describe visible CPUs and host physical memory;
they do not establish container allocation, available memory, concurrency or
workload capacity. Delegated-cgroup validation only reads pinned boot/device/inode,
filesystem/controller/domain metadata through the existing descriptor-pinned
adapter. It does not create child groups, write limits, move tasks, exercise
`cgroup.kill`, prove write delegation or verify kernel enforcement under load.

## Current deployment choices

Linux is the selected target platform. Exact host capacity and production runtime
remain unspecified. The existing unified-login service is not currently supplied;
development uses an explicitly enabled mock identity provider only. Mock login is
not production IdP/TLS/identity acceptance and does not unblock those checks.

Config-only CLI reading also supports platforms without POSIX `O_NOFOLLOW`:
regular-file and symlink checks plus pre/post-open file identity checks protect
the bounded read. This fallback is not claimed equivalent to kernel no-follow
semantics. Read-only local host/cgroup observations remain Linux-specific; the
pure configuration API does not probe the host.

## Start with unknown choices

Save this sanitized template outside the public repository. Unknown selections
remain null and produce BLOCKED; no production selection is inferred:

```json
{
  "schema": 1,
  "deploymentId": null,
  "configurationRevision": null,
  "targetHost": null,
  "identity": null,
  "runtimeAttachment": null,
  "computeBackend": null,
  "policy": null
}
```

Do not put passwords, database URLs, private keys, API keys, JWT signing keys,
access/refresh tokens, cookies or Authorization headers in this document. Public
JWKS contain public RSA parameters only. The parser rejects duplicate JSON keys,
non-finite numbers, oversized/deep inputs, unknown fields and secret field names.
The manifest limit is 65,536 UTF-8 bytes. Reports contain only fixed codes and
sections, never supplied URLs, paths, owner identities, keys or exception text.

## Schema 1

All listed fields are required. Each top-level selection can remain null while
unknown. Optional identity mechanisms use explicit null; otherwise supply the
complete public configuration. No unspecified constructor defaults are filled in.

| Section | Fields |
| --- | --- |
| Top-level metadata | `deploymentId`, `configurationRevision`: bounded opaque identifiers |
| `targetHost` | `platform` = `linux`; positive integer `expectedCpuCount`, `expectedMemoryBytes` |
| `identity` | `accessToken`, `browserLogin`; at least one selected for configuration completeness |
| `runtimeAttachment` | Explicit `{ "kind": "none" }`, or the native-runtime fields below |
| `computeBackend` | Explicit `{ "kind": "none" }`, or a selected backend below |
| `policy` | `temporaryPolicy`, `materialReviewMode`, `policyRevision`, `materialPolicyRevision`, `runtimeToolContract`, `maxWorkers`, `planReviewTtlSeconds` |

Runtime attachment and compute allocation are independent axes. A runtime-only
configuration may explicitly select compute `none`; no allocator is then required.
A null compute selection is unknown, while `none` is an intentional choice.

Native runtime fields are `kind: "native-agno"`, `httpsBaseUrl`,
`expectedAgnoVersion: "3.1.0"`, `executorId`, `configurationRevision`, and
`ownerMapping`: a list of `{ "originOwner": "...", "receiverOwner": "..." }`.
The base URL must be HTTPS without user information, query or fragment. This
validation does not call `/info` or `/config`, verify TLS, authenticate users,
confirm the executor or claim boot-epoch fencing.

Access-token identity fields are `issuer`, `audience`, `jwks`, `subjectOwners`,
`clockSkewSeconds`, `maxTokenLifetimeSeconds`. `subjectOwners` is a list of
`{ "issuer": "...", "subject": "...", "owner": "..." }`, converted to the
existing immutable issuer/subject mapping. Validation reuses `OIDCIdentityConfig`
and `OIDCAccessTokenVerifier`; it does not mint or validate a real access token.

Browser identity has the same common fields except audience; supply
`authorizationEndpoint`, `tokenEndpoint`, `clientId`, `redirectUri` and
`maxAuthAgeSeconds` (explicit null is allowed). It reuses `BrowserOIDCConfig`.
The callback path must be `/api/factory/auth/callback`. ID-token and RFC9068 access
token contracts remain separate. Config validity does not prove existing owners
or current SQL permissions, real IdP registration, login or deployment TLS.

Policy validation reuses `PlanPolicyConfig` and `GovernanceConfig`. Production
choices are `admin-review` or `read-only-auto`, with `separate-admin` material
review. Worker concurrency remains within the currently implemented 1–4 bound;
this is not target-host capacity acceptance.

Both compute backends require `kind`, `configurationRevision`, `owners`, `pool`
and `limits`. `pool` requires `poolId`, `cpu`, `memoryMb`, `diskMb`, `maxLeases`,
`maxOwnerLeases`; validation reuses `ComputePool`. Pools are admission accounting,
not kernel enforcement.

- `cooperative-process`: `limits` requires `cpuSeconds`, `addressSpaceMb`,
  `fileSizeBytes`, `wallSeconds`, validated by existing `ProcessLimits`. This
  profile cannot supply aggregate quota, hostile-code sandbox or network
  isolation; that limitation is explicitly UNSUPPORTED.
- `delegated-cgroup-v2`: additionally requires `delegatedCgroupPath`, `rootDevice`,
  `rootInode`, `bootId`. `limits` requires `cpuQuotaMicros`, `cpuPeriodMicros`,
  `memoryMaxBytes`, `swapMaxBytes`, `pidsMax`. These map directly to
  `DelegatedCgroupConfig`, including its strict types and bounds. CPU/memory
  budgets must fit the declared pool. This backend concerns CPU, memory/swap and
  process-count controls only; no network/filesystem/security isolation is
  implied. The declaration alone does not establish availability or enforcement.

## Read the result

`configurationValid` only answers whether all required declarations passed their
configuration rules. `productionAccepted` is always false. Check entries state a
scope (`configuration`, `local-observation`, `acceptance`) and fixed status:

- `PASS_CONFIG`: a declaration passed its configuration rules.
- `PASS_OBSERVATION`: one limited local read succeeded.
- `BLOCKED`: a choice or independent acceptance evidence is missing.
- `UNSUPPORTED`: a requested/recorded property is outside the implemented contract.
- `FAIL`: malformed or inconsistent configuration.

Overall precedence is FAIL, UNSUPPORTED, BLOCKED, PASS_CONFIG. CLI exit codes are
2, 4, 3 and 0 respectively. A fully specified config normally still exits 3
because live identity/TLS, native runtime and target capacity remain unverified.
An unsupported cooperative isolation property exits 4. Do not turn configuration
or read-only success into a production acceptance claim.

Public API: `parse_manifest(raw)`, `validate_manifest(data)`, and explicitly
opted-in `collect_local_observations(data)` in
`platform/agent_factory/deployment_validation.py`. Tests use synthetic public
keys, mocked host metadata and in-process CLI calls; no real deployment is run.
