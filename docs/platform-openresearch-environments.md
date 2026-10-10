# Platform OpenResearch environments (first increment)

Ordinary research may use a platform-provided environment after its operator
installs the reviewed runtime package. The owner configures a default model once,
chooses **platform**, and starts with a goal. Preparation creates or restores the
same native project, then the existing owner-submit command channel creates a
native session and sends the goal. Preparation, GET recovery and page reload
never send or replay a goal. Original OpenResearch and its coding harness own the
tool loop. There is no replacement Agno research agent in this path.

This location is distinct from both existing user-deployed remote services and
the managed one-turn attachment probe. It has no platform model account, fee
management or ordinary task administrator review. An owner's own provider may
charge their account. Local call/output limits are resource bounds, not a hard
external spending guarantee. OpenCode Go is not part of this runtime package.

## Platform custody and application package

`ApplicationEnvironments` persists owner, package version, original project ID,
original owner-model revision and prepare/stop request identity before effects.
Its installed package implements prepare, health, stop and connection descriptors.
The original connection registry, native session adapter, immutable plans and
AgentOS command queue remain the admission and observation paths.

`PlatformOpenResearchPackage` is the first installed package. It declares:

- Original ORX 0.2.13, source commit
  `f336b121525d99364e2dee4fe90b2784894a54e6`, reviewed Linux binary SHA-256
  `a847d07e8c4c3f2efc47c3549fd27f52c9999b46a21451d4c07ec12de292b8cd`.
- OpenCode 1.18.35 as this package's coding harness, binary SHA-256
  `77b2cfe4b97df6f15c3673b22100b9f79c711f25ecb9bf513bb82526b15d24fa`.
  Other application packages can declare another harness; core custody does not
  require OpenCode globally.
- An operator-selected immutable local Docker image ID. Preparation uses
  `--pull never`; it cannot select a mutable image or download unreviewed software.
- A private native ORX API bridge and an owner Chat Completions broker, both Unix
  sockets. No host TCP listener, public URL, Docker socket or host service secret
  enters the application. The HTTPS-shaped connection locator is opaque platform
  metadata, not a URL resolved through the external remote TLS adapter.

The operator wires an existing secure vault and the runtime artifacts through
trusted `Settings`, for example:

```python
from agent_factory.platform_openresearch import PlatformOpenResearchConfig

settings.platform_openresearch = PlatformOpenResearchConfig(
    orx_path="/opt/factory/packages/orx-f336b121/orx",
    opencode_path="/opt/factory/packages/opencode-1.18.35/opencode",
    image="sha256:<reviewed-local-image-id>",
)
settings.personal_agent_commands_enabled = True
```

The native personal-command application must be published through existing
application governance once by the operator. The runtime setting is Linux-only;
when absent, preparation advertises no platform location. Owners do not provide
paths, installation scripts, image choices, shell commands or deployment keys.
Cached executables must be regular non-linked files, immutable to other users,
and match the fixed hashes. The package rejects a missing or changed artifact.
The existing public `build_orx_linux.py` recipe records the original source and
build pins; operator artifact delivery is separate from owner preparation.

## Isolation, credentials and recovery

Each active environment has a separate non-root container, no network, no
capabilities, no new privileges, a read-only root and only its own writable data
mount. Defaults are one CPU, 1 GiB memory, 256 processes, two active environments
per configured supervisor, and a 30-minute renewal interval. At renewal, native durable state is read without
dispatching: idle environments stop; an active or unresolved turn/run/queue keeps
the same container within a fixed six-hour activation budget (operator configurable
up to 24 hours). The broker capability also expires at that absolute budget.
No automatic restart or goal replay extends the budget. At the hard limit the
container stops and data remains; interrupted work recovery is still unsupported.
Owners see these limits and should interrupt/finish native work before an explicit stop. This is bounded local container isolation;
capacity on the larger target servers has not been measured.

Supervisor identity markers and container receipts stay outside the writable
application mount. Before stop/reclaim the package checks the original container
name, exact ID, owner/body labels, network, user and mounts; an exited container
must have a Docker termination timestamp. An unknown stop never clears research
custody or declares research complete. No API deletes project data.

Only a short-lived local model capability enters the container. The host broker
checks the original owner/model/vault revision before every call, resolves the
credential there, pins the destination using the existing BYOK TLS transport,
and rejects known credential echoes. It has bounded concurrent handlers, calls,
input/output and deadlines, with no fallback provider. Native files, logs and
configuration receive no provider API key. A new host process cannot reuse an
old broker capability; explicit preparation reconciles the original container
and restores the same project without dispatching work.

A prepare replay returns the original request custody. An unknown preparation
requires a new explicit prepare request, which reconciles the same environment.
The original request remains unknown; GET recovery does not pretend it retried.
The blank project initializer uses the pinned native SQLite shape because this
ORX revision's project-create API starts an unconditional model warmup. It can
recover its own interrupted blank initialization and validates an existing native
project; it never fabricates session, experiment or run history.

Model revision changes and package updates currently fail closed and retain the
original data, requiring an explicit migration implementation. They do not
silently substitute another model, project or runtime version. Existing unresolved
research remains unresolved after stop/restart; it must be read or explicitly
continued through the existing native session custody rules.

This pinned ORX revision automatically drains persisted queues and resumes active
experiments on startup. Before restarting it, both the host package and container
entry read its native database and refuse launch when queued chat messages,
unfinished turns, nonterminal runs, undelivered wakeups or unfinished child spawns exist. They
preserve those records and never clear them or start a broker/container to recover
the goal. Explicit native queue/experiment recovery is not implemented in this
increment; those environments remain unresolved with their stored evidence.

## Current limits and verification

This first package allows local file/bash tools inside the constrained container
and the owner's model proxy. External web tools, plugins, skills, model discovery
and downloads are disabled. A future reviewed egress/research-tool descriptor is
needed for broader online research. Container execution and controlled model
fixtures prove the native wire and local tool mechanisms, not scientific results,
real-provider compatibility or complete online research acceptance.

Owned Linux servers now have an opt-in [SSH package assembly path](ssh-openresearch-environments.md).
External equipment acceptance remains separate from controlled local SSH testing. In-place
runtime/model migration, a scheduler with durable capacity reservations across
multiple supervisors and production artifact delivery
also remain separate work. The current Docker scope bounds one configured
supervisor; it is not a cluster capacity claim.

The private first-message call allows up to 120 seconds for the pinned coding
harness to start. A late or lost acknowledgement still remains unknown; the
platform only observes that original session and never retries its goal.

Run `npm run check`, Python checks and the disposable PostgreSQL suite. Controlled
browser/container reports are private task artifacts; public tests use synthetic
owners, credentials, runtime peers and model responses. No real model or remote
deployment is required by the automated suite.

`check_owner_byok_postgres.py` requires all 40 owner-model, platform and SSH-boundary
cases with no skips. The runtime startup gate checks both merged configuration
and the final executable tools of the native factory/build/plan agents. Controlled
original-binary testing has exercised one local bash tool, a persisted worktree
file, stop, and restoration by a new supervisor with identical original project,
session and transcript, zero model calls during preparation, and no goal replay.

## Deployment acknowledgement and socket custody

A pre-create receipt with no container ID can be reconciled only after a successful
exact-name Docker inventory proves absence. Inventory errors remain unknown.
Positive stopped-container custody is persisted before removal; if rm succeeds
but the final receipt write is lost, that saved stop intent plus authoritative
absence can complete cleanup. An acknowledged container missing without saved
stop evidence stays unresolved. None of these paths submits a research message.

The broker retains its original socket directory descriptor and socket inode.
Cleanup uses relative no-follow stat and unlink through that descriptor. Replacing
the writable sockets directory with another owner’s path, or replacing the socket
inode, cannot redirect host cleanup.

Local mutating requests register under the same environment lock used by lease
expiry, before releasing it for private HTTP IO. Until all such requests finish,
idle reclamation retains the same container without relying on a native database
that may not yet contain the command. The marker is released on response or error;
durable native work or unknown native state then governs renewal. The absolute
activation budget and explicit owner stop still apply; no request is replayed.
