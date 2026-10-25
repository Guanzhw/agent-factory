## ADDED Requirements

### Requirement: Omitted generic capabilities preserve preparation-only access
The generic connection binding route SHALL NOT implicitly grant `ssh:execute` when a caller omits capabilities. Explicitly requested SSH execution SHALL still use the existing trusted-capability subset check. Existing preparation-only references SHALL NOT be upgraded.

#### Scenario: An older generic client binds an SSH connection
- **WHEN** a member binds an SSH registration without an explicit capability list
- **THEN** the new reference permits preparation only and cannot authorize training
- **AND** an explicit subsequent execution request is a separate original request

### Requirement: Execution requires an explicit scoped binding
The SSH provider SHALL support `ssh:prepare` and `ssh:execute`. Existing `POST /personal-ssh/{reference}/bind` SHALL bind only `ssh:prepare`; verification or team sharing SHALL NOT grant execution. A member SHALL explicitly invoke `POST /personal-ssh/{reference}/bind-execution` with an original `requestId` to bind prepare and execute for their current identity. This action SHALL NOT open SSH or start a task.

#### Scenario: Existing preparation remains preparation
- **WHEN** a verified personal or shared server has only the member's existing preparation binding
- **THEN** inspection reports `enabled: true` and `executionEnabled: false`, and execution authority is rejected

#### Scenario: Explicit execution consent and receipt recovery
- **WHEN** the member explicitly enables execution and loses the acknowledgement
- **THEN** `GET /personal-ssh/requests/{requestId}?action=bind-execution` reads the original binding receipt without replaying the command; receipt capability sets distinguish prepare-only from prepare-plus-execute and an action mismatch is rejected

### Requirement: Current authority is checked at use
`server(owner, reference, *, required_capability='ssh:prepare')` and `lease(server, configuration=None, *, require_binding=True, required_capability='ssh:prepare')` SHALL recheck the required current capability. SSH execution consumers SHALL pass `ssh:execute`; no-binding probe leases SHALL remain preparation-only. Inspection SHALL derive executionEnabled from actual current authority, independently of verification status.

#### Scenario: Revoked execution or withdrawn shared resource
- **WHEN** a previously obtained execution lease is used after its binding, credential or source sharing authority is revoked
- **THEN** the lease validation rejects use; preparation-only bindings cannot satisfy execution

### Requirement: The existing SSH resource UI exposes explicit consent
The current SSH resource panel SHALL display an explicit “允许执行已配置训练” action and explain that this authorizes configured training on the selected server and is separate from connection checking. It SHALL submit only after the user's click, show the actual executionEnabled projection, and retain original owner/request/action recovery on uncertain outcomes. It SHALL NOT create credentials, start training or add a new navigation/controller.

#### Scenario: Refresh with an uncertain execution grant
- **WHEN** the user refreshes after an unconfirmed bind-execution request
- **THEN** the panel retains that owner's original request and offers receipt reading rather than automatically issuing another grant

### Requirement: SSH connections resolve through the native guarded handle contract
The SSH provider SHALL return an opaque handle supporting the existing ConnectionService `guarded(recheck)` contract. It SHALL NOT expose credential configuration or implement an HTTP/runtime client. A retained handle's `check_authorized` SHALL invoke the original connection's current owner/task/pin/capability guard; execution still uses the separately guarded SSH lease.

#### Scenario: Native resolution and retained execution authority
- **WHEN** the native connection registry resolves an explicitly execution-enabled SSH environment and retains its handle
- **THEN** resolution succeeds without dispatch, and authorization checks reject an insufficient preparation scope or later execution-binding revocation using the original connection identity
