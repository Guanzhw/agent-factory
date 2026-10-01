# Full-function acceptance matrix

Checkpoints describe intended complete functionality, not a claim that deferred features are delivered. M1 initializes the environment. M2–M4 require implementation and acceptance evidence after the reuse-first platform decision.

| ID | Capability and evidence required | Phase | Status |
|---|---|---|---|
| ENV-1 | Install from lockfile; lint/typecheck/tests/build; API startup/stop and browser smoke | M1 | Implemented, verification recorded separately |
| ENV-2 | GitHub authenticated identity, new public MIT repo, milestones/issues, exact remote commit and CI | M1 | Pending publication verification |
| LIB-1 | Material create/edit/version/archive/import with origin/license/digest | M2 | Planned |
| LIB-2 | Skills/tools/prompts/knowledge/models/environment materials with schemas, dependencies and permission metadata | M2 | Planned |
| ASM-1 | Callable catalog/discovery → plan/preflight → instantiate → inspect/reclaim; idempotency and permission recheck; immutable revisions; manager UI | M2 | Planned |
| ASM-2 | Second synthetic profile assembled without core rewrite | M2 | Planned |
| IAM-1 | Authenticated users, manager/user enforcement, cross-user job/artifact/connection denial | M2 | Planned |
| BIND-1 | Per-user/task data and trusted credential references; secrets excluded from model input/artifacts | M2 | Planned |
| JOB-1 | Durable queue/concurrency/lifecycle/event replay, input questions and scoped approvals | M2 | Planned |
| JOB-2 | Delayed/recurring schedules, attempt history/retry and restart reconciliation | M2 | Planned |
| JOB-3 | Cancel queued/running/waiting jobs and all outstanding experiments, terminal-state races | M2/M3 | Planned |
| AUD-1 | Persistent action/approval audit and artifact metadata/digests/download authorization | M2 | Planned |
| RES-1 | Actual pinned selected runtime integration, permissions, event stream, errors and cancellation | M3 | Planned; OpenCode is a candidate |
| RES-2 | Pinned ORX adapter command/API contracts and matching binary provenance | M3 | Planned; installed ORX differs |
| LIT-1 | Literature query/retrieve/read/source ledger, evidence-linked report and uncertainty | M3 | Planned |
| EXP-1 | Hypothesis/run config/approval/launch/supervision/lineage/metrics/evaluator/report | M3 | Planned |
| UI-1 | Manager catalog/assembly/users/policy UI and user tasks/questions/approvals/events/results UI | M2/M3 | Planned |
| SEC-1 | Isolated workspace/home/config/credentials/process; controlled egress; tool and prompt-injection boundaries | M4 | Planned |
| REC-1 | Disconnect/reconnect, process failure, restart, repeated submission/idempotency, cancellation recovery | M4 | Planned |
| E2E-1 | Browser tests for submission/questions/approval/cancel/repeat/error/recovery on actual workflows | M4 | Planned |
| OPS-1 | Deployment, backups/restore, monitoring, limits, upgrades and known-risk documentation | M4 | Planned |
| LIVE-1 | User-approved real model calls; usage/cost evidence and independent research evaluation | M3/M4 | Awaiting explicit provider/budget authorization |

## Decisions awaiting direction

1. Adopt/extend a complete existing platform first, then implement verified gaps after full design traceability and comparative evaluation.
2. Runtime choice and hosting strategy; if OpenCode is selected, its current embedded SDK and network client differ from legacy `/v2` exports.
3. Include natural-language automatic agent assembly in first complete release, or start with callable/UI assembly.
4. Real model provider and an explicit cost/time/resource budget for live acceptance.
5. Department deployment identity source and isolation platform. Proposed default: local development first, dedicated production worker isolation before shared use.

These decisions do not block safe environment initialization. They do block treating the full platform/live research as delivered.
