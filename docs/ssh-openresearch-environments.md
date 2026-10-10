# OpenResearch on an owned Linux server

Choose **My Linux server**, an already authorized server and a private research
directory, then enter a goal. Factory installs its fixed original OpenResearch
package automatically, preserves project/session/files on that server, and uses
the existing ordinary native command queue. The server does not need an ORX
service or OpenCode deployment in advance. Preparation and page reload never
submit research; a goal is sent only through the owner's explicit start click.

## Explicit prerequisites and registration

This adapter requires Linux x86-64, Python 3.12 or newer, existing non-root Docker access,
and an existing owner SSH-agent credential binding. It installs the application
package and loads its pinned image when missing. It never runs apt, sudo, changes
accounts or system services, grants Docker access, learns a host key, changes
firewalls, or opens an application TCP port. Missing infrastructure fails closed.

The current resource/vault API has no SSH-agent binding type. Server registration
therefore stays an opt-in trusted operator integration through
`Settings.ssh_openresearch: SSHOpenResearchConfig`. It supplies:

- The same fixed ORX/OpenCode artifact paths and immutable image as the platform
  package; binaries are verified against the reviewed hashes before transfer.
- `SSHServer` entries: opaque reference, owner, revision, display name, fixed IP,
  port, username, verified ed25519 host public key, private allowed root, and the
  existing credential reference/revision. The root must already belong to the
  server account with mode 0700. Selected child directories are created privately.
- A trusted `credentials(owner, reference, revision, destination)` resolver which
  returns `SSHAgentLease(socket, public_key, check)`. It must authorize that exact
  owner/revision/server pin, and `check` must reject revocation. The Unix agent
  socket is owned by the Factory account, mode 0600, in a private directory. The
  selected public key stays fixed in the persisted environment identity.

No access grant is inferred from environment variables, `~/.ssh`, uploaded
materials, model input, or user-supplied keys/commands. Only existing agent access
is used; the private SSH key never enters Factory's application package. HTTP
lists owner-filtered server names/default directories and accepts `location=ssh`,
`serverRef` and `directory` alongside the existing prepare request. Hostnames,
images, shell commands, credentials and arbitrary destinations are not HTTP fields.
There is no new self-service SSH credential enrollment UI in this increment.

The directory must remain inside the pinned private root without symlinks,
traversal or Docker-mount/SSH-forward separators. Linux Unix sockets bound the
remote control address to fewer than 104 bytes, including its generated suffix;
an overlong directory is rejected before effects. Installation and recovery
retain the same server, directory, model revision and native project. A changed
server/agent/package/model identity requires explicit migration and is rejected.

## What is automatic and what still needs preparation

| Item | Current responsibility and evidence |
| --- | --- |
| Linux x86-64, Python 3.12+, Docker CLI/daemon, SSH account and non-root Docker access | Must already exist on the selected server. Factory does not install or grant these. |
| Owner-private root directory (0700), fixed host public key, server/IP/account registration and existing SSH-agent binding | Trusted deployment operator must prepare/register these. There is no self-service registration UI. |
| Fixed original ORX/OpenCode application binaries, bridge, supervisor and notices | Factory transfers, verifies and installs these into the selected private child directory. No existing ORX service/runtime package is required on the target. Actual localhost SSH acceptance used a fresh child directory. |
| Immutable native image | Factory must already hold the reviewed image. The installer transfers it and loads it if absent. Transfer/verification passed on localhost; the truly image-absent cold-host branch remains unverified. |
| Start, private connection, original project/session/files, explicit restoration | Factory performs these within the existing infrastructure; controlled actual SSH/native/browser acceptance passed with a synthetic model. |
| External owner device and production credential enrollment | Unverified. This increment is application assembly on prepared infrastructure, not automated preparation of an arbitrary new server. |

## Installation, connection and custody

The installer runs fixed Python code through authenticated OpenSSH and receives
a bounded manifest plus exact file bytes over stdin. It allows only the reviewed
package filenames, verifies hashes, fsyncs pending files and atomically publishes
them inside the owned private directory. Existing files must match; unrelated or
changed package files are never overwritten. Original ORX/OpenCode MIT notices,
Factory's license and the notice inventory travel with the package. Their hashes
and the declared activation limits also form its frozen version. It streams a compressed export of
the already cached immutable image; successful Docker inventory proves whether
loading is needed, then exact image inspection verifies the selected ID. It
does not pull from a registry or upgrade dependencies.

OpenSSH runs with `-F none`, strict pinned known-hosts, the explicit public
identity and agent socket, no agent forwarding, password fallback, proxy,
multiplexed connection, implicit credentials or inherited forwards. The native
ORX API travels over bounded JSON RPC on SSH stdio. A private Unix socket reverse
forward connects the remote model bridge to the existing platform owner broker.
The socket is a separate read-only `/trusted/model-broker.sock` bind, outside the
application's writable mount. Real model credentials stay in the platform vault;
both owner/model authorization and the original SSH binding are rechecked before
each provider call. No provider key is transferred to the server or command line.

The remote stdlib supervisor reuses the same Docker receipt, original-container
inspection, immutable project, native startup guard, in-flight mutation fence,
idle lease and absolute activation budget as the platform package. It has no
remote Agno/PostgreSQL dependency: core plans and queue stay in Factory. Its
native application container is non-root, network-none, read-only, drops all
capabilities and has only its own writable persistent data mount. The configured
capacity bound is per supervisor directory, not a whole-server or fleet scheduler.

An SSH disconnect attempts to stop the owned runtime; no lost acknowledgement
is called a confirmed stop. Cleanup and a replacement SSH process hold the same
remote custody file lock before reading or writing the original receipt. Cleanup also matches the process's captured container generation and forwarding socket; a replacement that wins the lock cannot be stopped by delayed old cleanup. Lease timers capture their own generation, including within one process. Nested
stop during preparation reuses the admitted lock; repeated disconnect signals
cannot interrupt its bounded cleanup. A new explicit prepare reconciles the exact receipt
and original project before creating a replacement. Neither read recovery nor
reconnection retries a message. Stored unfinished native work prevents restart
and remains preserved. In-flight host/server crashes and interrupted-work
continuation have no durable remote watchdog guarantee in this increment.
Explicit stop does not delete project, transcript, worktree or application data.

## Verification limits

Required automated tests cover owner scope, frozen selections, revocation,
host-key/config policy, path traversal, symlinks, and saved forwarding-mount
identity. Controlled acceptance separately uses an ephemeral localhost sshd and
ssh-agent, original fixed ORX/OpenCode, an isolated PostgreSQL database, and a
synthetic model to exercise installation, native tools, persistence and desktop
pixels. This is actual SSH transport and original application execution, not a
DOM-only or client-import check. It does not prove real external-server access,
production SSH-agent provisioning, public-network research, or paid-model billing.

The local fixture's root-directory ownership differs from a standard host, so
only that ephemeral loopback sshd disables StrictModes after its exact private
authorization file is checked. System/production sshd configuration is untouched;
production directory-permission acceptance remains unverified. Controlled tests
do not start real research, call an external model, expose public services, or
alter shared databases.
