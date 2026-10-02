# Governed assembly and trusted execution bindings

This milestone replaces application-ID selection in the core with approved,
immutable application configurations and bounded material proposals. It extends
the existing Agno3.1/PostgreSQL executor; it creates no second queue or agent loop.

Managers define reusable application versions with named modes, exact material
references, bounded allowed alternatives, tool order, connection requirements and
budget ceilings. Shared publication requires a separate current administrator.
Publication state is separate from immutable content; withdrawal ends current
execution authority while preserving historical evidence.

A user submits a goal. Deterministic discovery searches approved application
metadata and selects approved defaults. The proposal records the exact application,
material closure, execution bindings, connection pins, capabilities, budgets and
missing preflight items. The user can revise, reject or accept it. Revision creates
another immutable proposal; acceptance creates a persisted task plan. Plan approval
policy and native tool confirmation remain separate decisions. No model invents
permissions, installs adapters or publishes shared definitions.

Materials can carry inert `runtimeBinding` data: `adapterId`, `revision`, and a
bounded `config`. Operator-installed factories implement those descriptors. The
registry validates exact material hashes, adapter revisions, adapter configuration,
required capabilities and owner connection pins. Missing adapters or connections
produce specific preflight failures. Actual-service execution has no automatic
synthetic-model substitute.

The single executor holds one stable model dispatcher. Agno's native RunOutput
provides owner/session/run identity; the dispatcher resolves the persisted task
and creates a fresh registered Model for that response. It checks current
permissions and immutable bindings before provider invocation. Tool factories,
scoped knowledge data and enforceable environment limits come from the same
manifest. Concurrent runs do not mutate the shared executor's Model selection.

User connections are owner-scoped opaque references to operator registrations.
HTTP accepts a registration reference and an optional narrowing of its scope,
never a credential, endpoint or provider installation. Stored snapshots contain
redacted metadata, revision and fingerprint. Rotation, revocation, expiry, missing
registrations, task mismatch and current role loss invalidate use. A trusted
same-process factory receives the opaque handle only after these checks.

For the reviewed fixed synthetic program, the bounded local environment enforces
the minimum of operator, plan and selected environment time/output limits, plus
process memory/PID/CPU limits. Real ORX discovery currently enforces time/output
only; its hard CPU/memory/PID containment is a deployment gap. Subtasks inherit
ancestor budget ceilings and share durable root tool-call accounting. Cancellation
and authority loss stop task-owned processes before a known cleanup result releases
capacity. Unknown outcomes remain held and are never blindly replayed.

ORX discovery is a narrow registered tool using the pinned OpenResearch adapter.
It resolves an operator-provided task-scoped handle, records effect/provenance
receipts and rechecks authority while its subprocess runs. Controlled transports
verify the registered path without external model/API calls. ORX agent/OpenCode
session ownership, autonomous experiments and arbitrary executable code remain
outside this adapter; the existing reviewed synthetic experiment exercises actual
process execution, evaluator evidence, approval and cleanup.

The legacy tool contract preserves existing v1 approval fingerprints and its four
registered tool names. Enabling `registered-runtime-v1` requires distinct operator
plan/material policy revisions; existing approvals are never silently widened.
Explicit demo seed adapters remain test adapters. Compatibility with older demo
plans requires an exact recorded bootstrap proof, never a production fallback.

Acceptance results and the FR/AC/AT mapping are recorded after verification in
[VERIFICATION.md](VERIFICATION.md) and [ACCEPTANCE.md](ACCEPTANCE.md).


## Operator configuration and compatibility

The default CLI installs explicit demo factories and safe native primitives.
Trusted extensions supply `AdapterRegistration` entries through
`Settings.runtime_adapters` and `TrustedConnectionBinding` entries through
`Settings.trusted_connections` before `create_app`. Neither is accepted from
request JSON, material content or a prompt. Connection resolution returns a handle
only inside a trusted factory after exact owner/task/pin checks. Controlled
registration examples are in the native binding and ORX PostgreSQL tests.

`FACTORY_RUNTIME_TOOL_CONTRACT=registered-runtime-v1` enables the narrow ORX name
in the governance/approval contract and requires distinct
`FACTORY_POLICY_REVISION` / `FACTORY_MATERIAL_POLICY_REVISION`. It configures no
binary, connection, Model or provider on its own. Old v1 fingerprints and exact
seed material hashes are preserved. Older demo plans can execute only after
explicit trusted `ApplicationService.adopt_legacy_demo_plan` proof; startup never
silently adds proof or adopts a production plan. Receiver transport rejects
connection-bearing manifests until explicit receiver mapping exists.

FR16 discovery is deterministic bounded matching of approved names/keywords,
followed by permitted exact choices. Unrestricted model-based application design,
provider provisioning, automated credential setup, ORX experiment integration and
full scientific autonomy are not implemented. Concurrent user capacity remains
the bounded native two-worker default; twenty accounts do not imply twenty workers.

The status endpoint reports demo/production mode separately from live integration verification: `liveEnabled` indicates production mode only, `liveIntegrationVerified` remains false, and `admissionMode` is `per-plan-preflight`. These status fields are not an execution grant. Production task evidence is labeled by artifact provenance rather than automatically labeled synthetic.
