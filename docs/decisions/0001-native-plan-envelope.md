# Agno 3.1 and immutable task envelopes

Accepted for implementation, 2026-10-01. New factory code is MIT; upstream Agno is Apache-2.0. The frontend is original React code, with no commercial Control Plane assets.

The selected engine is Agno AgentOS 3.1.0, upstream revision `ab1d6007f09163c3adadbe06f998dc481b77a09a`, with PostgreSQL. The earlier OpenCode scaffold is superseded as the factory engine. OpenCode remains a possible remote runtime attachment, not a second session owner inside the research agent.

Actual local regression found native static-component durable queue recovery works. Explicit published-version, database-only and factory-resolved runs returned acceptance without durable queue tickets. Native duplicate handling also reused changed input without a fingerprint conflict. We do not patch or fork the queue to repair these behaviors.

One registered `factory-executor` retains native session, worker, cancellation, model/tool and HITL lifecycle ownership. Its public callable instructions/tools, pre-hooks and tool-hooks load a persisted immutable plan using a trusted user/session/run binding. The queue persists the serializable envelope. Materials and the plan snapshot are separate from user/task bindings and native running state. Publishing a newer material cannot mutate an accepted snapshot.

Factory admission persists a semantic request fingerprint and bounded reservation before calling the native static route. Repeated identical requests reuse the original task; changed requests return 409. Missing acknowledgements retain capacity and require authoritative reconciliation. A trusted in-process context prevents public native executor calls from bypassing this admission boundary. Native JWT verification, managed SQL roles, fail-closed user directory and user isolation still apply to internal lifecycle requests.

Actual native PostgreSQL seam tests proved two plan instruction variants, hard-restart recovery with the pinned old snapshot, pause/confirmation/restart/continue, question/restart/answer, cancellation of a paused run, current authority/tool restriction checks and refusal to repeat an UNKNOWN effect. No replacement agent loop, nested agent `arun()`, upstream edit or external model call was used. Native COMPLETED is retained in the snapshot; protected tool failures and unresolved effects determine the application outcome separately.

The production temporary-plan approval matrix remains an operator decision. The explicitly selected demo policy admits only published synthetic materials and fixed local tools; experiments still require native scoped confirmation. Live provider, ORX and remote-resource configuration are disabled until configured and validated. A durable local proof is not a production load or tenant-isolation certification.

Single-server targets are 32 cores/64 GB or 54 cores/192 GB. Twenty users is not twenty workers; the initial cap is two workers and bounded per-user/aggregate task budgets. Remote compute allocation, native remote runtime attachment and A2A are separate capabilities. No arbitrary user code, environment provisioning, external access or paid execution is inferred by a plan.
