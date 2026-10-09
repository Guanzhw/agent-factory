# Personal remote connection boundary

## Scope and readiness

Implemented: an owner creates an immutable configuration for an existing OpenCode
serve endpoint, verifies it, then binds a narrowed capability set through the
existing `ConnectionService`. Reconfiguration, reverification, revocation,
credential rotation, provider-policy changes, expiry, owner/task mismatch and
native grant removal invalidate stale bindings at resolution.

This is a controlled verification foundation, **not completed end-user onboarding**.
An opt-in encrypted SQL credential backend and authenticated credential-entry API
are implemented; a secure credential entry UI, compute provisioning, remote
execution bridge, and live endpoint compatibility remain unverified or absent.
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
variable lookup keyed by user input would violate the contract. No plaintext credential
value belongs in SQL, metadata, logs, prompts, query strings or public responses.
The optional encrypted vault stores only authenticated ciphertext for the
username/password payload; other SQL tables retain opaque references only.

Owners use `/api/factory/personal-remotes` to create/list/read configurations and
`/{registrationRef}/configure`, `/verify`, `/revoke` to manage their lifecycle.
Creation and configuration accept `providerId`, HTTPS `origin`, `credentialRef`,
`credentialRevision`, expected `projectId`, and `requestId`. They never accept
owner overrides, credential values, private CIDR policy, code or adapter objects.
After verification, the returned registration reference is passed to the existing
`/api/factory/user-connections` binding endpoint, with optional task scope and a
narrowed capability set. Verification lasts 15 minutes. A new verification has a
new immutable binding revision; old plans never silently adopt it. The ordinary
OpenResearch journey can refresh an unchanged owner's lease and derive an equally
scoped future binding internally, then use the existing guarded session rebind
for a new explicit continuation. Rotation, revocation or scope/target/policy change
requires explicit selection; unknown work is never replayed. See
`PERSONAL_OPENRESEARCH_JOURNEY.md`. The read-only identity handle requires the complete verified
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

## Optional encrypted credential custody

`CredentialVault` is a pluggable owner/revision/destination-scoped interface; an
organization vault may implement it. `VaultSecretProvider(vault, provider_id)`
adapts it to a single installed remote provider. The optional
`EncryptedCredentialVault(engine, master_key, provider_policies)` uses the pinned
`cryptography` AES-256-GCM implementation. Its 32-byte master key must be injected
by trusted operator configuration outside SQL, request bodies and catalog data.
There is no key generation, key-file reading, automatic key rotation, or fallback
credential source. Missing configuration disables the feature. Key repr is
redacted. Operators must protect the key independently from database backups and
review runtime/process and observability access before deployment.

The configured provider-policy callbacks are trusted application code, never user
inputs. The OpenCode origin policy admits canonical HTTPS hostname origins; global
network policy still checks resolved addresses during actual verification. Saving
a credential performs no remote IO. An organization may supply a stricter callback
(e.g. exact-host allowlisting), but owners do not need a separate operator-created
resource record for each personal endpoint. Every saved credential is pinned to
its exact owner, generated opaque reference, immutable revision, installed provider
and canonical destination. Those five values plus a version tag are AES-GCM
additional authenticated data. Each create or rotation uses a fresh random nonce.
The username and password are encrypted together; neither is persisted separately.

The authenticated API is `/api/factory/personal-credentials`:

- POST accepts only `providerId`, `destination`, `username`, `password`, `requestId` and returns
  opaque `credentialRef` and `credentialRevision` plus non-secret scope/status.
- POST `/{credentialRef}/rotate` accepts `credentialRevision`, `username`,
  `password`, `requestId`. The expected revision is a compare-and-swap guard. It cannot change
  owner, provider or destination; creating a new credential is required for those.
- POST `/{credentialRef}/revoke` accepts `requestId` and the expected `credentialRevision` and
  invalidates it locally, removing stored ciphertext. It does not rotate or
  delete credentials on the remote service.

Create/rotation require native run authority; revocation requires authenticated
owner read authority. There is no plaintext credential read/decrypt HTTP endpoint. GET on the root
returns at most 100 owner-only metadata records; GET `/capabilities` returns
`enabled` and installed `providerIds`. GET `/requests/{requestId}` recovers the
exact immutable operation result for that authenticated owner, or returns 404.
Recovered status describes the original operation; list metadata supplies current
status. Mutation `requestId` is mandatory, bounded, and unique per owner. Replaying
the same request returns its stored result; changed intent is rejected. Command
reservation and credential mutation commit atomically. Intent fingerprints use
HMAC-SHA256 with a domain-separated key derived from the external master key,
never unkeyed password hashes or secret plaintext. An unknown acknowledgement
should be resolved by this read-only lookup before the client proposes any retry.
Manual streamed JSON parsing is bounded to 24,576 bytes, rejects duplicate fields,
extra fields and non-string values, and does not use secret-bearing Pydantic
validation errors. All failures return fixed diagnostic text; success and failure
responses are no-store. The production API must remain behind the existing
`BrowserAuthBridge`: cookie writes require HTTPS, same-origin and the exact session
CSRF token before reading credentials. Native bearer ingress must use the trusted
TLS deployment path. Never configure request-body tracing, exception-local capture,
or proxy credential-body logging. The application cannot erase immutable Python
strings from process memory; decrypted leases are transient runtime objects.

Rotation/revocation does not edit remote configurations, verified revisions,
approved plans or unknown-workload custody. Existing remote authorization checks
reject the previous revision, requiring explicit reconfiguration, verification and
rebinding. This is local invalidation, not proof that upstream work stopped.
Database transactions use compare-and-swap for concurrent mutation; master-key
changes need a separately reviewed migration and are not implemented here.

Evidence: `test_credential_vault.py` covers synthetic encrypted persistence, logs,
nonces, restart, owner/provider/destination isolation, AAD/ciphertext tampering,
rotation/revocation, stale remote binding invalidation, bounded/redacted HTTP
validation and CSRF-before-processing. `test_credential_vault_postgres.py` exercises
real disposable PostgreSQL persistence/restart and revision invalidation; a skipped
run is not acceptance evidence. These tests use synthetic bytes and credentials,
not live endpoints or production secrets.

## Opt-in application wiring

`Settings.credential_vault_factory` is trusted code called with the Factory SQL
engine. It returns a `CredentialVault` implementation; the built-in encrypted SQL
implementation requires an externally supplied 32-byte master key and installed
provider destination policies. The setting and all provider factory closures are
excluded from Settings repr. No key is generated or read from the user's machine.

`Settings.personal_connection_provider_factories` maps installed provider IDs to
trusted factories receiving that vault. For OpenCode, the factory constructs
`OpenCodeServeProvider(VaultSecretProvider(vault, PROVIDER_ID))`, optionally with a
reviewed `RemoteNetworkPolicy`. Duplicate registrations fail startup rather than
silently changing a provider. Existing direct `personal_connection_providers`
remain supported for organizational secret backends. Users still create their
own endpoint records; these settings install implementations and global policy.

Without a vault factory, authenticated credential capabilities return
`{enabled:false,providerIds:[]}` and no secret mutation routes exist. With a vault,
only provider IDs installed in both the vault policy and remote provider registry
should be offered by the UI. Deployment must terminate HTTPS and use the existing
authenticated browser bridge/CSRF protections before accepting real credentials.
This branch's tests use synthetic keys/passwords and controlled probes only.

Lost replies are recovered without resubmission through owner-only GET
`/personal-credentials/requests/{requestId}`, `/personal-remotes/requests/{requestId}`,
and `/user-connections/requests/{requestId}`. Credential responses are immutable
historical receipts; remote/binding responses expose the original object's current
state. Recovery does not probe the remote server, rotate secrets, or create a new
connection. Never persist a password in browser storage to enable retries.
