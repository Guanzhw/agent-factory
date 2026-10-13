# Explicit scoped trusted model-proxy deployment mode

Status: implemented but disabled by default. The existing direct route remains
unchanged unless trusted same-process operator configuration installs an explicit
`TrustedModelProxy` grant for one deployment, owner and exact model/credential
reference and version. There is no HTTP, material or ambient-environment loader.
No real credentialed request or live research is authorized by this implementation.

## Problem and minimum proposal

Some managed environments require an already supplied HTTP proxy for HTTPS.
The protected production transport currently connects directly to a checked
public IP. HTTPcore 1.0.9's proxy tunnel uses that IP as its TLS server hostname,
whereas the target needs its credential-bound hostname. This compatibility gap
can be addressed using the public network-backend API, without changing installed
HTTPX/HTTPcore internals or disabling certificate verification.

The optional route is an explicit trusted-gateway deployment mode. Direct is the
default. The implementation accepts a validated, immutable deployment
grant, supplied by a trusted configuration boundary, rather than automatically
reading `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, or CA variables from ambient
process state. Owners, models, request bodies and material definitions must not
provide or enlarge that grant. No arbitrary proxy setting is added to owner UI.

The grant binds the approved gateway endpoint and approved existing TLS
context to the permitted destination and authorization scope. Exact origin,
path, method, owner/lease revision and permission rechecks remain in the current
production guards. Their identity and accounting must not be replaced by a
proxy-specific authority. Rotations/revocations still take effect on every call.

Each invocation resolves and validate all target addresses using the
existing public-address policy, then bind only its first checked address.
CONNECT targets that literal IP; the target TLS handshake and HTTP Host use the
exact credential-bound hostname. For an HTTPS proxy, its outer TLS handshake
uses the approved proxy hostname. The target `sni_hostname` extension must not be
forwarded into the outer handshake; the immutable binding supplies target SNI.
The same approved verification context is passed through without adding CAs,
disabling hostname checks or ignoring verification errors.

Use the public `httpcore.AsyncConnectionPool(proxy=..., network_backend=...)`
interface behind a narrow HTTPX transport bridge. One immutable binding/pool per
invocation avoids connection reuse across owner, origin, SNI or lease changes.
No redirects, retry loops, alternate IP/host or direct fallback after a proxy,
policy, certificate or protocol error. Cancellation closes owned resources.

The narrow bridge uses the public HTTPcore pool/backend API; no general-purpose
proxy framework is added. IPv4-only scope is explicit: a first validated IPv6
address fails closed, with no alternate address selection. A transport is used
once; a second pool connection is rejected. Its approved CA-set fingerprint and
hostname-verification flags are checked before I/O and each TLS handshake.

The grant binds `environment_id`, `owner_id`, `model_reference`, `model_revision`,
`credential_reference`, `credential_revision`, `model_id`, `base_url` and
`protocol`. The address uses the existing owner-model endpoint policy: public
HTTPS `/v1` providers and the already reviewed exact provider prefixes. Protocol
is explicitly `chat-completions` or `responses`; it is never inferred from a
model name. URL, Host and target SNI are derived from that validated address.
Unrelated owners/models retain direct mode. A matching selected model with a
changed revision, credential, model, address or protocol fails closed. Existing
handles also reject replacement/revocation of their grant. Clear the old grant
before updating an approved model configuration, then install a newly reviewed
version-bound grant; never silently retarget it.

The new fields are appended with the historical defaults:
`base_url="https://opencode.ai/zen/go/v1"` and `protocol="chat-completions"`.
Existing positional construction and old grants keep their original scope.
They cannot authorize Responses, another hostname or a different prefix. Missing
protocol in legacy model metadata still means Chat Completions; explicit null or
unknown values are rejected. A new explicit grant can authorize either supported
protocol for a matching configured endpoint without adding a provider framework.

## Different security guarantee

| Property | Direct route | Explicit trusted-gateway route |
| --- | --- | --- |
| Client destination | Checked public IP | Approved gateway; CONNECT names checked public IP |
| Client TLS hostname | Credential-bound provider hostname | Same hostname; an approved interception CA may terminate TLS |
| Secrets and prompts | Protected against intermediaries by provider TLS | An intercepting gateway can read model keys, prompts and responses |
| Upstream route/filter | Client pins the provider connection | Gateway is responsible for upstream routing and filtering |
| End-to-end IP pin | Client transport property | Cannot be inferred from CONNECT200 or a verified TLS/HEAD response |
| Default/automatic enablement | Existing default | Off; never inferred from ambient proxy variables |

TLS interception changes confidentiality and routing trust. This is a new
deployment security mode, not a claim of the same guarantee as direct mode.
Existing CA installation alone is not approval to send owners' model keys.
The gateway operator, upstream-routing/filter contract and approval scope must
be established before activation. A grant for one owner/task does not silently
authorize other owners' credentials.

A minimal user-facing disclosure is: requests use an
explicitly trusted gateway; it may read credentials and request data; upstream
routing follows its deployment policy. The affected owner must accept that boundary before sending data. The constructor
requires `acknowledge_interception=True`, supplied by the trusted operator after
that approval. No UI or generic approval system is added; it does not infer
consent from an installed CA or a chat message, nor read/export any model key.

Provider origin and lease checks remain necessary, but do not certify what an
intercepting proxy does upstream. If policy rejects the destination or the
IP/hostname pair, stop. Do not change domains, add tunnels, disable verification,
or broaden allowlists to make a test pass. Existing UNKNOWN reservations remain
unchanged and cannot be replayed or refunded by transport diagnostics.

Errors must remain finite sanitized codes through the existing model boundary.
Do not persist gateway URLs, credentials, response bodies, exception messages or
raw TLS traces. Useful safe facts are route kind, phase, status and finite error
category; they do not settle an unconfirmed model call.

## DNS timeout is a separate compatibility question

A managed resolver may take longer than the existing three-second isolated
helper deadline. A bounded diagnostic may allocate a larger part of its own
total deadline without changing production configuration. The direct/global default remains three seconds. Only an explicit scoped grant
may select a bounded DNS wait from three through ten seconds, within the existing
model invocation deadline. No resolver/system setting changes. The maximum
address count, every public-address check and child timeout termination/reaping
are retained. The operator must choose this deliberately; it is not enabled by
an ambient environment variable.

## Activation conditions and offline evidence

Before enabling this route for a deployment:

1. Review this explicit confidentiality/routing boundary and its owner/task scope.
2. Confirm the exact deployment gateway and upstream filtering contract; retain
   the weaker gateway-mode guarantee instead of claiming end-to-end client pin.
3. Review a small default-off integration that preserves origin/owner/secret,
   no-replay and accounting guards. Configuration must be trusted and explicit.
4. Obtain the affected owner's authorization before any credentialed request.
   Diagnostic or synthetic success cannot stand in for that authorization.
5. Run the normal product's complete real flow when authorized; synthetic
   transport checks do not establish that flow.

`test_trusted_model_proxy.py` exercises the actual production bridge over in-memory
streams: literal-IP CONNECT and Host/SNI separation, both HTTPS proxy TLS names,
context immutability, no second connection/fallback/reuse, private/IPv6 target
rejection, exact endpoint/protocol and owner/model/credential/deployment scope,
secret redaction and UNKNOWN cache behavior. Both protocols cover a generic
compatible endpoint as well as the existing reviewed prefixes. Direct transport
regressions remain in this suite. The PostgreSQL
suite uses an independent disposable database, actual encrypted custody, normal
owner HTTP configuration and the registered Agno executor with a fake provider.
Required selected cases must execute without skips.

These tests do not verify live provider POST, billing, research results or the
proxy's upstream route. No live-compatibility flag is promoted.

## Explicit activation after independent review

Keep `Settings.owner_model_trusted_proxy=None` for normal direct behavior. For the
approved acceptance process only, declare its environment identity at startup:

```python
settings = Settings(
    # Existing database/workspace/auth/vault registrations stay as configured.
    db_url=existing_db_url,
    owner_model_proxy_environment_id=approved_current_environment_id,
)
```

After normal owner model configuration, trusted same-process operator code can
use metadata from that owner/default model to install the grant. Do not derive
owner identity from a display name; use the authenticated owner ID. Do not
resolve, export, copy or print the model key for this step:

```python
metadata = models.default(approved_owner_id)  # Metadata, never vault.resolve().
grant = TrustedModelProxy(
    environment_id=approved_current_environment_id,
    owner_id=approved_owner_id,
    model_reference=metadata["reference"],
    model_revision=metadata["revision"],
    credential_reference=metadata["credentialRef"],
    credential_revision=metadata["credentialRevision"],
    model_id=metadata["model"],
    base_url=metadata["baseURL"],
    protocol=metadata.get("protocol", "chat-completions"),
    proxy_url=explicitly_approved_existing_proxy_url,
    ssl_context=explicitly_approved_existing_verified_context,
    acknowledge_interception=True,
    dns_timeout_seconds=10,  # Optional scoped value; default is 3.
)
models.install_trusted_model_proxy(grant)
```

Alternatively supply the same grant in `Settings.owner_model_trusted_proxy` when
metadata already exists. It must match the configured environment; fixture
`owner_model_transport_factory` and a real gateway grant cannot coexist. These
configuration objects are redacted and never persisted as user material or
HTTP input. Revocation is `models.install_trusted_model_proxy(None)`; existing
bound handles then stop before another call, and cached UNKNOWN remains held.
The grant never changes the existing vault resolution/ownership/revision checks.

Explicit environment credential/model rebind wrappers retain the exact delegate
gateway grant. Their existing environment/delegate checks still run before and
after credential resolution; revoked or changed bindings cannot inherit a stale
grant or silently switch to direct.


The operator supplies the already approved proxy and existing CA context
explicitly, with full verification. This code does not modify CA files, firewall,
resolver, or environment settings. It does not provision or transport a new key.
If the supporting credential tool requires a secure handoff, use that mechanism
and stop pending it; this grant is not authority to upload plaintext API keys.

Sources: [HTTPcore public network backends](https://www.encode.io/httpcore/network-backends/),
[request extensions](https://www.encode.io/httpcore/extensions/),
[HTTPX proxy API](https://www.python-httpx.org/advanced/proxies/),
and [SSL verification](https://www.python-httpx.org/advanced/ssl/).
