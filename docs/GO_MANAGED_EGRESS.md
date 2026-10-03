# Go managed egress compatibility

Base: PR17 `4fc83fbe8bddf5e14a7f62d80f82d150de8d6aff` (all ten CI jobs passed).
Both historical DeepSeek attempts remain UNKNOWN, consuming two slots; Luna
count remains zero. This stage authorizes no inference or credential access.

## Application configuration

The development adapter previously forced `trust_env=False`. Local HTTPX source
and offline checks confirmed that this ignores both environment proxy selection
and `SSL_CERT_FILE`. The existing environment has HTTP/HTTPS proxy variables and
an SSL CA variable; values, credentials and certificate paths are not logged.
Neither their presence nor the earlier ConnectError proves the precise cause of
the failed requests or an explicit network-policy denial.

The shared Go client now honors existing HTTPX proxy/NO_PROXY and CA settings
when no fixture transport is supplied. TLS verification stays enabled; no host
environment variables, proxy endpoints, CA files, network policies or account
settings are changed. The helper accepts no arbitrary proxy/URL/verification
option. Request hooks enforce the exact HTTPS official origin, allowed Go paths
and matching methods; redirects are disabled. There is no application retry or
direct/alternate-route fallback after an error or denial. A route selected
initially by the environment's NO_PROXY is distinct from a fallback after a
failed proxy request. Synthetic transports retain isolation from ambient proxy
configuration, including the existing credential-stripping loopback fixture.

Sources: [HTTPX environment configuration](https://www.python-httpx.org/environment_variables/)
and [official cloud environment guidance](https://learn.chatgpt.com/docs/environments/cloud-environments).
The latter documents environment domain policy and, in its VPN connectivity
troubleshooting, checking that a client uses the configured HTTP/HTTPS proxy.
Using existing controlled egress does not grant permission to bypass a deny.

## One-shot unauthenticated check

The separate connectivity script uses the same client for a fixed public models
GET, without Authorization, API-key lookup, request body or model invocation.
The whole operation is bounded to ten seconds. A private exclusive attempt marker
is written first; an existing marker is inspection-only, including after a crash.
No second probe, retry, redirect or alternative host is allowed in this stage.
It records only HTTP status, bounded phases/times and finite safe cause/errno
categories, never exception messages, proxy URLs, credentials or response bodies.

Offline coverage and independent review must pass before root executes the single
check. Success or failure cannot settle/refund either inference UNKNOWN and does
not authorize the remaining model request. If an explicit denial is received,
stop and report the required official hostname `opencode.ai`; do not modify or
work around the rule. Safe outcome and final exact-head CI are recorded in the
draft PR. No merge or deployment is authorized.

## Recorded outcome

On 2026-10-03, after review and offline tests, root executed exactly one
unauthenticated GET with OPENCODE_GO removed from the child process environment.
The shared client used existing environment proxy/CA selection without changing
any host configuration. PREPARED, DISPATCH_STARTED and RESPONSE_HEADERS were
recorded. HTTP 200 was received; elapsed time was 282 ms, from
08:29:24.427351 to 08:29:24.710514 UTC. No exception/cause/errno was observed.
Response content was not consumed or retained. No follow-up request was made.

This demonstrates reachability of the unauthenticated public endpoint through
the environment-compatible client at that time. It does not prove authenticated
inference, subscription billing, the exact cause of the earlier direct-path
failures, or production acceptance. Both prior UNKNOWN reservations remain held;
DeepSeek2/Luna0. Seven budget/historical evidence files retain identical bytes
and modification times.

Independent review found no blocker; 22 focused offline tests passed in 0.115s.
Full offline suite: 727 tests, 298 skips, 53.323s. Native Factory/PostgreSQL with
synthetic HTTP responses passed (one test, 7.097s). Ruff and Windows-target
Pyright pass. Nine changed files passed credential-pattern scanning. Production
provider registration, API/schema and lifecycle permissions are unchanged;
only the development Go client and the standalone no-auth diagnostic are affected.
