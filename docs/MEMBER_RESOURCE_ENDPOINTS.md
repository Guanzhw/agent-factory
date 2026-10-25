# Member resource endpoints

Members connect resources from **Credentials and connections**. Connections start
as personal. Their owner can share them with the team; another member binds the
shared resource using their own account. Resource ownership and credential
ownership remain with the creator. Account administrators manage accounts and
receive the same resource access as other members.

## HTTP and model services

Supported HTTP adapters accept HTTP or HTTPS, DNS names, IPv4 and IPv6, local or
private addresses, and custom ports. Model bases also accept custom API paths:

```text
http://127.0.0.1:8000/custom/api
http://model-server:8080/v1
https://models.example.com:8443/api/model
http://[::1]:9000/v1
```

Select the model and its supported protocol, such as Chat Completions or
Responses. The model adapter appends the protocol route to the configured base
path and sends the selected model ID. A service using another protocol needs its
corresponding adapter.

Leave credentials empty for a service that accepts unauthenticated requests.
When credentials are provided, save them separately in the encrypted vault and
select the saved credential for the connection. URL fields do not accept embedded
usernames, passwords or authentication query strings. A service that requires
authentication reports an authentication failure so the owner can supply it.

HTTPS retains certificate and hostname verification, including custom ports and
connections pinned to resolved IP addresses. An untrusted certificate or wrong
hostname fails. The configured HTTP authority, port and model path remain intact.
Credentials are scoped to their owner, stored revision and destination; redirects
are not followed. Timeouts, response bounds and explicit connection failures
remain operational controls.

The generic OpenCode adapter checks health, the configured project identity and
available agents. These checks establish the adapter's actual protocol contract;
the retired Research application is not installed.

## SSH servers

Enter the server's DNS name or IP, SSH port, account, working directory and host
public key. Copy the host key from the server's trusted local console, for example
from the matching `/etc/ssh/ssh_host_*_key.pub`, and confirm its fingerprint.
The platform uses that identity for strict host-key verification.

Enroll an already authorized, unencrypted OpenSSH private key. Key acceptance
follows the installed cryptography parser and OpenSSH serialization, including
RSA, ECDSA and Ed25519. The parser rejects malformed or passphrase-protected keys
under this credential-input contract. The SSH account may be `root` when that is
the server's configured account. Addresses, ports and accounts need no operator
allowlist.

**Check connection and directory** authenticates over SSH and checks whether the
configured directory exists. It uses shell builtins and does not require Python,
Docker or an installed research application. It creates no remote directory.
The configured directory is the generic resource's directory; an application may
select its own subdirectory when preparing its environment.

An explicitly installed application must separately validate its preparation
requirements. A successful generic SSH directory check does not establish those
requirements or install an application. Unavailable preparation reports
`SSH_CHECK_UNCONFIRMED`.

The private key is encrypted in the owner's vault. Execution loads a bounded
lease into a private local `ssh-agent` over stdin. Only public identity and
known-host files are written for SSH; the key is not returned in shared resource
responses. Runtime SSH custody requires the POSIX OpenSSH client and agent.

## Team use and withdrawal

The owner controls configuration, verification, sharing and revocation. Team
members can discover and bind a shared resource without receiving its credential
references or private key. For example, Bob's SSH operation uses Alice's server
credential while the calling member remains Bob.

The actual-use boundary checks the calling member, current sharing state,
connection binding and credential revision. Withdrawing sharing, disabling Bob,
or revoking Alice's credential prevents a retained Bob handle from starting a
new operation. Restoring access requires an explicit owner/member action; the
platform does not substitute another credential.

The database and persistent vault master key must be backed up together; see the
deployment's credential-custody instructions. Losing the key prevents decrypting
the saved credentials.

## Repeatable local verification

The following tests generate synthetic credentials and use isolated loopback
services. They do not contact external model providers or user SSH servers:

```sh
PYTHONPATH=platform:platform/tests \
  uv run python -m unittest \
  test_custom_resource_endpoints test_personal_ssh test_byok_model \
  test_trusted_model_proxy -v

# An installed or task-owned extracted sshd executable is required:
FACTORY_TEST_SSHD=/absolute/path/to/sshd \
PYTHONPATH=platform:platform/tests \
  uv run python -W error::ResourceWarning -m unittest \
  test_personal_ssh_live -v
```

The live SSH fixture generates its own RSA/ECDSA/Ed25519 host and login keys,
starts loopback-only servers on temporary ports, and reaps them after each test.
Its remote shell has no Python or Docker on `PATH`. It checks real shared use,
host-key mismatch, missing application dependencies, and retained-handle denial
before another remote command. A missing SSH daemon causes an explicit test skip;
that skip does not establish SSH acceptance.
