# Factory v0.3 scope reconciliation — 2026-10-04

The delivery target is the complete material-driven Factory, with AutoResearch as
its first Chinese-language application, approximately twenty departmental users,
and single-host targets of 32 cores/64 GB or 54 cores/192 GB. Agno 3.1.0 and
PostgreSQL remain the execution platform. Completing a diagnostic, provider or UI
stage does not complete this product target.

This reconciles checked-in scope, implementation and acceptance evidence. The
private original design documents are not reproduced here, and this is not a
claim to have revalidated every clause in those documents. See the
[current acceptance matrix](ACCEPTANCE.md#current-matrix),
[assembly contract](MATERIAL_ASSEMBLY.md), [backend contracts](BACKEND_CONTRACTS.md)
and [production inputs](PRODUCTION_DECISIONS.md).

## Delivered mechanisms and remaining work

| Area | Implemented evidence | Implementable code gap / next acceptance |
|---|---|---|
| Materials, governance and FR16 assembly | Six material kinds, immutable versions and dependency closure; separate publication review; bounded proposal/revision/acceptance and application modes. [Governance](../platform/agent_factory/material_governance.py), [composition](../platform/agent_factory/composition.py), [applications](../platform/agent_factory/applications.py). | Exercise the full manager-to-user workflow with the selected real research materials. Deterministic approved-material discovery is not unrestricted autonomous tool installation or publication. |
| Native execution and lifecycle | Persisted plans/bindings, owner connection pins, one native queue, HITL, delegation, shared root limits, cancellation and durable original-key recovery. [Bindings](../platform/agent_factory/execution_bindings.py), [bridge](../platform/agent_factory/native_bridge.py), [control receipts](../platform/agent_factory/control_commands.py), [delegation](../platform/agent_factory/delegation.py). | Extend mutation-recovery coverage where specific user commands lack it; a general durable browser command journal is still distinct from existing server receipts. Retain current authorization checks and UNKNOWN holds. |
| Plan approval | Configurable production default, exact-plan review, separate native tool confirmation and delegated scope checks. [Policy](../platform/agent_factory/plan_policy.py), [policy contract](PLAN_POLICY.md). | Choose the final production temporary-plan policy and validate real owner/reviewer responsibilities. No replacement approval mechanism is required for already authorized development work. |
| Go coding integration | Exact DeepSeek Chat and Luna Responses; native Factory/Agno coding tool, receipt, artifact and Postgres usage workflow passed for both. [Integration evidence](GO_PROJECT_INTEGRATION.md), [adapter](../platform/agent_factory/opencode_go.py), [project policy](../platform/agent_factory/go_project_campaign.py). | Continue useful coding workflows beyond the checksum acceptance case. Subscription authorization is ongoing; actual provider invoice remains unverified. Go coding authorization does not select a production scientific provider. |
| Token and accounting controls | Immutable tariff/commitment identities, per-attempt reservation and settlement, shared budgets and remote grants; nominal Go amounts explicitly distinguished from invoice cost. [Ledger](../platform/agent_factory/usage_ledger.py), [Go contract](../platform/agent_factory/go_usage.py). | Implement and test the selected scientific provider's exact input/output, usage, streaming, retry and price contract. This is substantive adapter work, not just supplying a key. |
| Literature application and Chinese evidence UI | Installed query/tool contracts, source/hash/locator and missing-text provenance, report/package artifacts, owner-scoped persisted projection, explicit empty/failed/controlled-source presentation. [Tools](../platform/agent_factory/orx_literature_tools.py), [projection](../platform/agent_factory/literature_evidence.py), [evidence contract](LITERATURE_EVIDENCE.md). | Add a governed contract for a new real question, successful permitted retrieval and model synthesis with verifiable citations. Existing live PubMed evidence has zero sources after connectivity failure; the new UI does not change that fact. |
| Experiments / AT10 | Pinned Linux ORX toy, actual processes, positive stop evidence and original-identity local/receiver recovery. [AT10 acceptance](AT10_TREE_ACCEPTANCE.md), [ORX tools](../platform/agent_factory/orx_experiment_tools.py). | Non-toy dataset/workspace/evaluator contracts, candidate-change review and evidence-based comparison still need implementation. Toy recovery is not arbitrary-code containment or scientific validity. |
| Remote runtime and resources | Runtime attachment, immutable receiver mappings, receiver-owned execution trees and controlled multi-process receipt/restart/cancellation evidence. [Resources](../platform/agent_factory/resources.py), [remote execution](../platform/agent_factory/remote_execution.py), [remote contract](REMOTE_RESOURCES.md). | A real compute allocator and environment provisioning remain code work. Add provider-backed allocation/release reconciliation and resource fencing, then validate external TLS, owner identity and positive stop evidence on the selected hosts. Attachment alone does not allocate compute. |
| Production identity | Managed SQL roles, bearer checks, current revocation and owner isolation; a demo browser bridge. [Auth](../platform/agent_factory/auth.py). | Implement the selected OIDC/gateway browser entry, session/logout and subject-to-owner mapping; verify issuer/audience and revocation. Existing demo identities are not production onboarding. |
| Operations and target capacity | Quarantine/restore/reclaim, bounded twenty-user pressure, official online PostgreSQL snapshot and independent restore. [Storage](../platform/agent_factory/storage_governance.py), [operations evidence](STORAGE_OPERATIONS.md). | Production monitoring, recovery objectives/PITR, sustained mixed-workload fairness and target-host capacity still require implementation/configuration and measurement. Recorded host is 4 CPU/16 GiB, not either target profile. |
| Scheduling | Immutable occurrence admission and guarded restart, with one active native poller. [Scheduler](../platform/agent_factory/scheduling.py). | Resolve and verify the upstream atomic lease-release boundary before supporting concurrent scheduler replicas. No cluster or multi-replica claim follows from current tests. |

## Current bounded implementation slice

Public coding research is **in development**, not accepted at this document's
creation. It selects two public MIT source files at exact commit
`914de54a18ee3ccda772f578a217f7df6594c805`:

- `platform/agent_factory/go_http.py` — fixed destination and verified transport policy.
- `platform/tests/test_go_http.py` — corresponding transport boundary tests.

The new [bounded fetcher](../platform/agent_factory/public_code_fetch.py),
[pinned knowledge adapter](../platform/agent_factory/public_code_knowledge.py) and
[governed composition helper](../platform/agent_factory/public_coding_research.py)
are being integrated. Acceptance must connect actual public retrieval and exact
whole-file hashes to the immutable knowledge binding, native Factory execution,
source-grounded coding output, scoped downloadable artifact and durable usage.
Controlled fixture tests prove contracts only. Fetch success alone does not prove
model grounding; a valid citation alone does not prove its claim. No live result
for this slice is asserted here. It remains coding research, not PubMed or
non-toy scientific acceptance.

Independent code work can continue without inventing another provider-call
approval gate: finish this slice, close concrete workflow/recovery gaps and test
with public or synthetic inputs. Selecting production identity, scientific
provider/question and compute deployment remains a separate product decision.

## Evidence boundaries and counts

[Draft PR21](https://github.com/Guanzhw/agent-factory/pull/21), exact
`38b4014692713060a2e1bd269d6dbfb1287bbf05`, completed the ongoing Go development
integration stage. Both live smokes and both native coding workflows passed.
Its recorded cumulative baseline is DeepSeek seven requests and Luna three:
four UNKNOWN and six SETTLED. The original three UNKNOWN attempts and subsequent
repeated-usage failure remain unknown; later success does not diagnose, release,
replay or settle them. Later requests must append to the same history. Nominal
accounting amounts are not an invoice, even when token counts are authoritative.

[Draft PR22](https://github.com/Guanzhw/agent-factory/pull/22), exact
`914de54a18ee3ccda772f578a217f7df6594c805`, completed literature evidence visibility
and mobile provenance display. Its CI checks are stage evidence, not a new
retrieval or scientific result. Counts include skips:

| PR22 check | Total | Passed | Skipped |
|---|---:|---:|---:|
| Each PostgreSQL CI suite | 805 | 742 | 63 |
| Local full Python suite | 805 | 506 | 299 |

Thus “805 tests with 63 skipped” does not mean 805 passes plus 63 skips.
Superseded cancelled CI runs are not green runs. Exact-head checks and historical
opt-in skips must retain their own provenance; PR21/PR22 completion cannot certify
the currently developing source-grounded slice or the complete v0.3 product.

## External inputs for production acceptance

Collect non-secret choices while independent implementation continues:

1. Identity entry: existing IdP/gateway, public issuer/audience/callback contract,
   stable subject mapping, pilot owners and separate material reviewers.
2. First scientific workflow: concrete question, allowed sources/full-text
   licences, desired comparison/citations and a domain acceptance reviewer; for
   experiments, pinned dataset/repository, baseline, metric and change scope.
3. Scientific provider: selected model/SDK, governed owner binding, authoritative
   usage and price contract, approved execution limits. Do not substitute Go
   coding subscription access for this selection.
4. Deployment/compute: chosen host/runtime and allocator, resource/network and
   isolation contract, production monitoring/recovery objectives and measured
   target workload. No merge, deployment, new payment or account change is
   implied by this reconciliation.
