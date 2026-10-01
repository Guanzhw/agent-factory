# Security and deployment assumptions

This milestone runs an explicitly synthetic, loopback-only demo. It grants no external access and changes no account credentials. Use a separate production database; the store refuses demo/production mode reuse. Demo identity and the fixture database's loopback trust authentication must never be exposed to a department network.

## Trust boundaries

Native Agno JWT verification, managed SQL roles, fail-closed directory and user isolation establish identity. JWT role/scope claims cannot enlarge managed rights. Current authorization is read again at protected tool boundaries; user disablement/revocation does not rely on cached admission claims. The factory masks cross-user task/plan/artifact access with 404. Manager fixture identity is an administrator for synthetic publication; narrower production manager/admin roles and publication review separation remain acceptance work.

The public executor routes are blocked by an ingress guard. Only the trusted in-process bridge context can call those routes, and native JWT/owner/policy checks still apply. Clients cannot supply a subject, permission set, arbitrary tool, model, executable or server URL to the factory. Goals, retrieved content and tool outputs are untrusted data. Catalog permissions undergo dependency-closure checks and application/task bounds. Snapshots cannot grant authority after current policy is withdrawn.

User credentials resolve through trusted connection references. Provider credentials, bearer tokens, raw keys and personal configuration are absent from prompts/materials/artifacts. Production requires operator-configured identity/key/connection provisioning; no setup endpoint creates production users or grants. Signing keys are process configuration; no plaintext key is logged or returned.

Missing local/remote acknowledgements and side-effect receipts are UNKNOWN. They retain capacity and refuse automatic replay or reclaim. Cancellation intent is durable; a request acknowledgement, disconnect or lease expiry does not prove compute stopped. Artifacts have owner-scoped download authorization, a content hash and explicit synthetic provenance.

## Local experiment containment

Only a fixed reviewed fixture program runs. It receives an allowlisted minimal environment and no user source/code. Windows uses a kill-on-close Job Object with CPU-rate, memory and process bounds, plus bounded output/time and verified process cleanup. POSIX uses an owned process group and fixed-program resource limits with final group termination. This does not make arbitrary shell, native dependencies or hostile code safe for departmental tenancy.

Separate directory roots, HOME/config/cache and ORX_DATA_DIR are useful hygiene but are not tenant security. Production requires approved OS/container/process isolation, separate credentials, controlled egress, workspace ownership, process/resource accounting, artifact scanning and remote identity verification before untrusted execution. The adapter cannot infer these guarantees from an endpoint's existence or advertised version.

## Operational gaps

Production OS, remote endpoints/providers, identity source, model budget and temporary-plan policy are not selected. Scheduling/delegation governance, secret lifecycle, backup/restore/retention, monitoring, fair admission and capacity tests remain open. Native queue streams are replica-local here; the intended deployment is one application process. Configure verified coordination before any multi-process/replica design; no cluster is assumed. Binding a service beyond loopback, deploying, adding access or invoking paid resources requires explicit authorization.

Commit only original safe code, public docs and synthetic samples. Ignore `.env`, `.local`, virtual environments, caches, database/workspaces, browser profiles, logs and generated research. Never copy private source packages, company workflows, credentials or personal files into this public repository.
