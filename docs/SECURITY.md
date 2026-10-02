# Security and deployment assumptions

This milestone runs an explicitly synthetic, loopback-only demo. It grants no external access and changes no account credentials. Use a separate production database; the store refuses demo/production mode reuse. Demo identity and the fixture database's loopback trust authentication must never be exposed to a department network.

## Trust boundaries

Native Agno JWT verification, managed SQL roles, fail-closed directory and user isolation establish identity. JWT role/scope claims cannot enlarge managed rights. Current authorization is read again at protected tool boundaries; user disablement/revocation does not rely on cached admission claims. The factory masks cross-user task/plan/artifact access with 404. Demo manager identity is an administrator, but default material publication requires a distinct current administrator. Production authors can have narrower native components:write rights; no production identity or grant is provisioned. Inert imports enforce bounds, licenses/provenance and exact dependencies; archive/withdrawal affects current execution without erasing history.

The public executor routes are blocked by an ingress guard. Only the trusted in-process bridge context can call those routes, and native JWT/owner/policy checks still apply. Clients cannot supply a subject, permission set, arbitrary tool, model, executable or server URL to the factory. Goals, retrieved content and tool outputs are untrusted data. Catalog permissions undergo dependency-closure checks and application/task bounds. Snapshots cannot grant authority after current policy is withdrawn.

User credentials resolve through trusted connection references. Provider credentials, bearer tokens, raw keys and personal configuration are absent from prompts/materials/artifacts. Production requires operator-configured identity/key/connection provisioning; no setup endpoint creates production users or grants. Signing keys are process configuration; no plaintext key is logged or returned.

Missing local/remote acknowledgements and side-effect receipts are UNKNOWN. They retain capacity and refuse automatic replay or reclaim. Cancellation intent is durable; a request acknowledgement, disconnect or lease expiry does not prove compute stopped. Artifacts have owner-scoped download authorization, a content hash and explicit synthetic provenance.

## Local experiment containment

Only a fixed reviewed fixture program runs. It receives an allowlisted minimal environment and no user source/code. Windows uses a kill-on-close Job Object with CPU-rate, memory and process bounds, plus bounded output/time and verified process cleanup. POSIX uses an owned process group and fixed-program resource limits with final group termination. This does not make arbitrary shell, native dependencies or hostile code safe for departmental tenancy.

Separate directory roots, HOME/config/cache and ORX_DATA_DIR are useful hygiene but are not tenant security. Production requires approved OS/container/process isolation, separate credentials, controlled egress, workspace ownership, process/resource accounting, artifact scanning and remote identity verification before untrusted execution. The adapter cannot infer these guarantees from an endpoint's existence or advertised version.

## Operational gaps

Production OS, remote endpoints/providers, identity source and model budget are not selected. Plan/material review policies have conservative configurable defaults. Actual native admission tests cover twenty synthetic users; clean-stop PostgreSQL restore is verified. Secret lifecycle, retention/PITR/RPO/RTO, monitoring and sustained throughput/fairness remain open. Native queue streams are replica-local here; the intended deployment is one application process. Configure verified coordination before any multi-process/replica design; no cluster is assumed. Binding a service beyond loopback, deploying, adding access or invoking paid resources requires explicit authorization.

Commit only original safe code, public docs and synthetic samples. Ignore `.env`, `.local`, virtual environments, caches, database/workspaces, browser profiles, logs and generated research. Never copy private source packages, company workflows, credentials or personal files into this public repository.

Signed owner-bound Factory event cursors are application metadata, not native Agno stream claims. Large events fail explicitly; late lower-ID commits require replay. Historical protected failures are queried independently of the bounded display window. Active fixed compute rechecks current authority and cleans up on loss; cancellation intent still requires positive native/effect/group stop evidence before release.

Trusted lifecycle cleanup uses exact persisted native owner/session/run/executor/envelope/idempotency bindings and public native cancellation APIs. It creates no work, JWT or grant after authority loss. Missing tickets, unknown effects and stale running-ticket evidence retain capacity. Default in-memory native signals are limited to the single application process.


## Governed execution registration

Approved definitions and inert material `runtimeBinding` descriptors do not
install code. Operators register trusted same-process factories; a fresh Model
is selected per native response context, with current exact user/task/run and
connection pins checked before and after provider responses. Scoped tools recheck
authority even when a callable is retained. Concurrent owners never mutate one
shared Model or receive another owner's knowledge/handle.

The public connection API lists redacted registrations and binds/revokes only
the caller's narrowed references. It cannot set a secret, URL, subject, adapter or
grant. Current expiry, role loss, registration removal, revision or handle identity
change invalidate old references. Rotation requires new explicit binding and plan
pins; revoked history stays inspectable. Registrations are operator memory/config
objects, not a production secrets manager or credential-rotation service.

Connection-bearing remote manifests currently fail closed until an explicit
receiver-side mapping is implemented; no private handle is serialized or sent.
The ORX registered discovery tool enforces time/output bounds and cancellation
observation but supplies no hard CPU/memory/PID tenant containment. Do not infer
that isolation from a selected environment descriptor or isolated directories.
