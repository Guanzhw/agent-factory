# Browser authentication and bounded process enforcement

Continuation of PR25 (`a61898a5b92e1584e4adf7cf35bcdcc14b3948b5`). These are
implemented integration contracts with synthetic/local acceptance, not production
IdP or target-host capacity certification. Existing scientific/Go UNKNOWN records
and all earlier receipts remain unchanged.

## Browser contract

An operator can set `Settings.browser_oidc` to a frozen `BrowserOIDCConfig` in
production mode. It pins HTTPS issuer, authorization/token endpoints, public-client
ID, exact `/api/factory/auth/callback` redirect URI, RSA public keys and existing
SQL-owner mappings. Endpoints share the issuer origin. No discovery, automatic
user creation, real client registration or environment credential discovery occurs.
The initial profile uses public-client authentication (`none`) with S256 PKCE;
an IdP requiring confidential-client authentication needs an explicit further
adapter, not a silently invented client secret.

`POST /api/factory/auth/login` requires the configured HTTPS Origin. It returns a
fixed-provider authorization URL and creates a Secure, HttpOnly, host-only flow
cookie. The request uses authorization code, `openid`, random state/nonce and S256
challenge. One-time state is stored as a hash and bound to the browser cookie;
PKCE verifier/nonce context is encrypted using a domain-separated key derived
from the existing configured native signing key. No new persistent credential is
created. Pending state expires after300 seconds. A new login cancels the previous
flow for that browser. Active flow/session counts and cleanup batches are bounded.

The callback atomically consumes matching, unexpired state before a single
10-second, retry0 token exchange. A wrong browser cannot consume another browser's
state. Network failure, cancellation, restart or lost callback receipt cannot
replay that code. Strict ID-token validation is distinct from RFC9068 access-token
validation: pinned RS256/JWT key, issuer, audience/azp, nonce and timestamps are
checked; duplicate JSON/key URLs are rejected. Access/refresh tokens are discarded,
never stored in the database, local storage or frontend responses.

Successful login rotates the session atomically and issues an opaque
`__Host-factory_session` Secure/HttpOnly/SameSite=Strict cookie. Only its hash,
existing owner, configuration fingerprint, expiry and revocation status persist.
Absolute session lifetime is at most900 seconds and never exceeds the ID token.
There is no implicit refresh. Existing SQL user state and permissions remain
current authority; a short internal native token is minted only within ASGI.
Explicit Bearer requests use the independent external access-token verifier;
ambiguous Bearer plus browser session is rejected. Native worker traffic retains
its existing in-process path.

All cookie-authenticated mutations require exact configured Origin and a
session-bound `X-Factory-CSRF` value. The frontend gets this through the private
session endpoint and keeps it only in memory. Responses are private/no-store;
auth redirects do not disclose callback parameters via Referrer. Duplicate
cookies/query parameters, insecure scheme and forged forwarded-origin headers
fail closed. The UI handles expiry, retry and old responses after identity change.

`POST /api/factory/auth/logout` and `/api/factory/logout` durably revoke the current
session and cancel the browser's pending or completed login. Completed flow
records retain the issued session hash until that session expires; the flow
cookie lasts1200 seconds while **pending state still expires at300**. This lets
logout invalidate a successful callback whose Set-Cookie response has not arrived,
even after the original five-minute flow period. Lost logout receipts are safe to
repeat. This is local application logout; it does not claim federated IdP logout.

Operator inputs still needed: registered public-client ID/exact redirect, issuer
endpoints and public key rotation policy, existing-user mapping, existing strong
native key, actual TLS ingress, log redaction/access-log policy and deployment
cleanup/rate controls. The built-in server disables access logs; a proxy must not
log callback codes or cookies. Synthetic TLS does not validate production TLS.

Standards reviewed: [OAuth security BCP](https://www.rfc-editor.org/rfc/rfc9700.html),
[PKCE](https://www.rfc-editor.org/rfc/rfc7636.html),
[OIDC ID-token validation](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation).

## Process enforcement contract

`BoundedProcessAdapter` is a standalone operator-facing Linux adapter for a
checksum-pinned executable and fixed argv. It is deliberately separate from the
workspace-only resource provider; no public command execution endpoint or default
runtime registration is added. A future approved runtime integration must connect
its custody to pool leases and current authorization. The current API takes a
fresh synchronous `before_effect` callback inside durable admission; awaitable
callbacks are rejected before any subprocess starts.

A task-private SQLite journal commits dispatch intent before a detached guardian
starts. Only the creating instance can dispatch once; reopening never redispatches
uncertain work. Owner/task/request and guardian/child Linux birth identities persist.
The child is gated until journal custody is recorded and kernel limits are set.
The guardian checks original process identity, enforces cancellation/wall deadline,
reaps the root and requires no live process-group members before reporting stop.
Lost guardian/receipt/custody remains UNKNOWN and held; it is not positive release.

Actual enforcement is explicitly limited:

| Limit | Enforced mechanism | Boundary |
|---|---|---|
| CPU | RLIMIT_CPU,1–2 seconds | Per process, not aggregate child CPU |
| Address space | RLIMIT_AS,32–128 MiB | Per process virtual memory, not aggregate RSS |
| File size | RLIMIT_FSIZE,1–64 KiB | Per file, not total disk quota |
| Wall time/cancel | Detached guardian, original process group | Cooperative programs must remain in that group |

This is **not** a hostile-code, network, filesystem, credential or multi-tenant
sandbox. Same-UID programs and task directory/journal ancestors must be trusted;
there is no protection against a hostile host replacing custody paths or a program
escaping its group. No aggregate cgroup quota, process-count quota or privilege
isolation is claimed. No host/cgroup/network/security setting was changed. Stronger
isolation requires an operator-selected supported runtime/facility and separate
acceptance; it cannot be inferred from these small synthetic process tests.

## Acceptance evidence

- Strict OIDC verifier/exchanger:9 offline tests.
- Browser boundary suite:19 tests, including concurrent callback, lost receipts,
  nonce/state/CSRF/fixation, current identity, expiry/restart, logout during exchange
  and delayed callback after five minutes plus cleanup.
- Real disposable PostgreSQL/native authorization:4 tests passed in7.659s.
- Chromium1440 desktop and390 mobile over two loopback HTTPS fixtures: login,
  PKCE exchange, abandoned-flow retry, reload session, logout, private responses,
  Secure/HttpOnly cookie and no horizontal overflow. Six stable screenshots were
  inspected. Two synthetic authorizations/two exchanges; no real IdP access.
- Bounded process suite:8 cases, including actual CPU spin, address-space allocation,
  bounded file output, descendant-group wall stop, restart/cancel, uncertain launch
  no replay and asynchronous-authority rejection. No target-host load claim.
- Frontend88 tests; final full Python/static/audit evidence and exact-head CI are
  recorded on the stage draft PR. Earlier local or prior-head results do not
  substitute for that final CI record.

Remaining product work includes selected production IdP/TLS acceptance, federated
logout where required, remote machine provisioning and runtime/lease integration,
aggregate kernel resource/fencing adapters, real scientific provider/non-toy
acceptance and sustained32-core/64GB or54-core/192GB target-machine measurements.
