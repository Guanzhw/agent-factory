# Personal remote connection boundary

## Scope and readiness

Implemented: an owner creates an immutable configuration for an existing OpenCode
serve endpoint, verifies it, then binds a narrowed capability set through the
existing `ConnectionService`. Reconfiguration, reverification, revocation,
credential rotation, provider-policy changes, expiry, owner/task mismatch and
native grant removal invalidate stale bindings at resolution.

This is a controlled verification foundation, **not completed end-user onboarding**.
There is no bundled production vault, secure credential entry UI, compute
provisioning, remote execution bridge, or claim of live endpoint compatibility.
No real endpoint, credential, deployment or paid workload was used to validate it.
The documented protocol and synthetic controlled fixtures are the current evidence.

The connection kind is `environment`, provider `opencode-serve-v1`. It is not an
OpenResearch server. Capabilities are `runtime:health`, `project:read` and
`agent:read`; verification does not grant session execution, tool execution,
filesystem access, model spending or permission changes. Existing governed
Factory workload dispatch retains its approval and budget boundaries.

## Operator installation versus owner configuration

Operators install one allowlisted `OpenCodeServeProvider` implementation, a scoped
`SecretProvider`, and global `RemoteNetworkPolicy`, using
`Settings.personal_connection_providers`. Operators do not create per-user resource
records. Without that secure backend integration, the provider registry is empty
and the system must report the feature unavailable rather than fabricate success.

`SecretProvider.authorize` and `resolve` must enforce the entire authenticated
owner, opaque reference, immutable credential revision and exact destination
origin tuple. `resolve` repeats authorization and returns only an ephemeral
`SecretLease`. Rotation/revocation must immediately invalidate the old revision.
The backing vault must provide these guarantees; implementing a global environment
variable lookup keyed by user input would violate the contract. No credential
value belongs in SQL, metadata, logs, prompts, query strings or public responses.

Owners use `/api/factory/personal-remotes` to create/list/read configurations and
`/{registrationRef}/configure`, `/verify`, `/revoke` to manage their lifecycle.
Creation and configuration accept `providerId`, HTTPS `origin`, `credentialRef`,
`credentialRevision`, expected `projectId`, and `requestId`. They never accept
owner overrides, credential values, private CIDR policy, code or adapter objects.
After verification, the returned registration reference is passed to the existing
`/api/factory/user-connections` binding endpoint, with optional task scope and a
narrowed capability set. Verification lasts 15 minutes. A new verification has a
new immutable binding revision; old plans must rebind/replan rather than silently
adopting it. The read-only identity handle requires the complete verified
capability set, rechecked before and after IO; a narrowed reference cannot read
extra project or agent metadata. Revocation is local access revocation, not deletion of remote resources
or proof that already-running upstream processes stopped.

## Network and identity policy

The default accepts only a hostname-based HTTPS origin on port 443 with no path,
query, userinfo or fragment, using system CA verification and hostname SNI. There
are no environment proxies, netrc auth, redirect following or transport retries.
DNS answers are validated as a set and the actual TCP connection uses the selected
numeric address while TLS verifies the original hostname, avoiding a second DNS
lookup and credential-bearing DNS rebinding. DNS runs in a fixed isolated helper
process with a three-second timeout that kills and reaps the helper. Each HTTP
probe has a ten-second absolute deadline covering connect, TLS, status, headers
and body; deadline interruption shuts down the active socket. No unbounded
background resolver or socket worker is left running.

An operator may allow reviewed private targets using both exact hostname and CIDR
classes. That is global provider policy, never a per-user approval or resource
record. Loopback, link-local, multicast, unspecified/reserved addresses, known
metadata addresses and address-translation forms remain denied. A changed network
policy fingerprint invalidates prior configurations. No trust store or network
settings are changed by this implementation.

Verification first requires an unauthenticated health request to return 401, then
checks authenticated `/global/health`, exact `/project/current` identity, and
`/agent` metadata. The identity claim is TLS origin + credential possession +
expected project ID. It is **not a human identity proof**, workload compatibility
certification, server-side tenant-isolation proof, or guarantee that a malicious
remote server genuinely implements OpenCode. The credential backend owns tenant
isolation and destination authorization. Untrusted response/error text is not
published; only bounded allowlisted metadata is stored. Failed fresh verification
invalidates any prior lease for the unchanged configuration.

## Evidence

- Official contract reviewed 2026-10-08: https://opencode.ai/docs/server/
- Current upstream auth wiring: https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/server/routes/instance/httpapi/server.ts
- Offline suite: `test_personal_remote_connections.py` (synthetic transport and
  secrets, actual local HTTP routes and SQL persistence).
- Opt-in native PostgreSQL/native authorization HTTP suite:
  `test_personal_remote_postgres.PersonalRemotePostgresTests`. This requires the
  repository's disposable loopback `FACTORY_TEST_DATABASE_URL` CI service. A skip
  is not acceptance evidence; the aggregate CI gate must run it without skips.
