# Explicit trusted model-proxy deployment mode (design only)

Status: proposed security boundary, disabled and not implemented. This draft adds
documentation and offline test fixtures only. It does not register a runtime
route, read proxy configuration, change provider schemas, or enable network use.
The existing direct `PinnedChatTransport` remains the only production route.

## Problem and minimum proposal

Some managed environments require an already supplied HTTP proxy for HTTPS.
The protected production transport currently connects directly to a checked
public IP. HTTPcore 1.0.9's proxy tunnel uses that IP as its TLS server hostname,
whereas the target needs its credential-bound hostname. This compatibility gap
can be addressed using the public network-backend API, without changing installed
HTTPX/HTTPcore internals or disabling certificate verification.

The proposed route is an explicit trusted-gateway deployment mode. Direct is the
default. A future implementation would accept a validated, immutable deployment
grant, supplied by a trusted configuration boundary, rather than automatically
reading `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, or CA variables from ambient
process state. Owners, models, request bodies and material definitions must not
provide or enlarge that grant. No arbitrary proxy setting is added to owner UI.

The grant would bind the approved gateway endpoint and approved existing TLS
context to the permitted destination and authorization scope. Exact origin,
path, method, owner/lease revision and permission rechecks remain in the current
production guards. Their identity and accounting must not be replaced by a
proxy-specific authority. Rotations/revocations still take effect on every call.

Each invocation would resolve and validate all target addresses using the
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

No activation flag, production bridge, configuration loader or general-purpose
proxy framework is introduced in this draft. The tests contain only a reference
adapter and in-memory streams. Its IPv4-only scope is explicit; IPv6 CONNECT
authority formatting needs separate review before general production support.

## Different security guarantee

| Property | Direct route | Proposed trusted-gateway route |
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

A minimal user-facing disclosure for a later implementation is: requests use an
explicitly trusted gateway; it may read credentials and request data; upstream
routing follows its deployment policy. The deployment route must be identifiable
for an affected owner before sending data, without exposing gateway credentials.
That disclosure and consent scope require product/security review; no UI or
approval system is added here.

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
total deadline without changing production configuration. This draft does not
increase a global timeout or change resolver settings. A production deadline
change requires separate evidence and review, while preserving the maximum
address count, every public-address check and child timeout termination/reaping.

## Activation conditions and offline evidence

Before a later production implementation is enabled:

1. Review this explicit confidentiality/routing boundary and its owner/task scope.
2. Confirm the exact deployment gateway and upstream filtering contract; retain
   the weaker gateway-mode guarantee instead of claiming end-to-end client pin.
3. Review a small default-off integration that preserves origin/owner/secret,
   no-replay and accounting guards. Configuration must be trusted and explicit.
4. Obtain the affected owner's authorization before any credentialed request.
   Diagnostic or synthetic success cannot stand in for that authorization.
5. Run the normal product's complete real flow when authorized. PR80 remains
   unmerged until its separate complete-real-flow condition is met.

`test_trusted_model_proxy_design.py` exercises the installed HTTPcore protocol
state machine over in-memory network streams: CONNECT/SNI/Host separation,
HTTPS proxy's two TLS names, denial/certificate failure without fallback,
full-verification-context preservation, rejected private targets, explicit
IPv6 scope and untrusted input rejection. Additional tests use the actual direct
transport and existing model error boundary to verify direct behavior and secret
redaction. Real sockets and DNS are blocked in these tests.

This does not verify a real gateway's certificate chain, upstream routing,
provider POST, credentials, billing or research result. No implementation status
or acceptance matrix is promoted by this design draft.

Sources: [HTTPcore public network backends](https://www.encode.io/httpcore/network-backends/),
[request extensions](https://www.encode.io/httpcore/extensions/),
[HTTPX proxy API](https://www.python-httpx.org/advanced/proxies/),
and [SSL verification](https://www.python-httpx.org/advanced/ssl/).
