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
| Go coding integration | Exact DeepSeek Chat and Luna Responses; native tool/receipt/artifact/usage workflows and the pinned public-source coding example passed. Luna uses a separately governed revision 2 with a fixed 512-output-token cap; revision 1 remains 256. [Integration evidence](GO_PROJECT_INTEGRATION.md), [adapter](../platform/agent_factory/opencode_go.py), [project policy](../platform/agent_factory/go_project_campaign.py). | Integrate further useful coding workflows and the full browser product flow. Subscription authorization is ongoing; actual invoice remains unverified. Go coding authorization does not select a production scientific provider. |
| Token and accounting controls | Immutable tariff/commitment identities, per-attempt reservation and settlement, shared budgets and remote grants; nominal Go amounts explicitly distinguished from invoice cost. [Ledger](../platform/agent_factory/usage_ledger.py), [Go contract](../platform/agent_factory/go_usage.py). | Implement and test the selected scientific provider's exact input/output, usage, streaming, retry and price contract. This is substantive adapter work, not just supplying a key. |
| Literature application and Chinese evidence UI | Source/hash/locator and missing-text provenance, report/package artifacts and owner-scoped Chinese evidence projection. New host PubMed retrieval completed through native Factory with two real abstract-only sources. [PubMed adapter](../platform/agent_factory/pubmed_retrieval.py), [governed profile](../platform/agent_factory/pubmed_profile.py), [projection](../platform/agent_factory/literature_evidence.py). | Validate the selected production question/source and permitted text coverage. The older zero-source failure remains unchanged; host-path success does not establish the old ORX container path or its failure cause. |
| Source-bound synthesis | Governed immutable source snapshot, native knowledge injection, separate scientific capability, bounded claims/source IDs and exact-quote checks, explicit limitations, saved JSON/Markdown artifacts. Native controlled-model synthesis completed using the new real PubMed sources. [Contract](../platform/agent_factory/literature_synthesis.py), [fixture profile](../platform/agent_factory/literature_synthesis_profile.py). | Integrate a selected real scientific model/provider and its trusted accounting contract, then verify semantic/scientific quality with a domain reviewer. Current model execution is controlled-fixture; structural citation integrity is not a verified scientific conclusion. |
| Experiments / AT10 | Pinned Linux ORX toy, actual processes, positive stop evidence and original-identity local/receiver recovery. [AT10 acceptance](AT10_TREE_ACCEPTANCE.md), [ORX tools](../platform/agent_factory/orx_experiment_tools.py). | Non-toy dataset/workspace/evaluator contracts, candidate-change review and evidence-based comparison still need implementation. Toy recovery is not arbitrary-code containment or scientific validity. |
| Remote runtime and resources | Runtime attachment, immutable receiver mappings, receiver-owned execution trees and controlled multi-process receipt/restart/cancellation evidence. [Resources](../platform/agent_factory/resources.py), [remote execution](../platform/agent_factory/remote_execution.py), [remote contract](REMOTE_RESOURCES.md). | Shared weighted pool admission, a real task-owned workspace allocator and stop-only maintenance now exist; see [resource/identity milestone](RESOURCE_IDENTITY_INTEGRATION.md). A standalone trusted-cooperative process adapter now enforces per-process CPU/address-space/file-size and group wall limits; see [browser/process milestone](BROWSER_AUTH_PROCESS_ENFORCEMENT.md). Remote machine provisioning, runtime attachment to allocated environments and aggregate kernel fencing remain code work. External TLS/owner/stop proof and target-host acceptance remain open. |
| Production identity | Managed SQL roles, bearer checks, current revocation and owner isolation; a demo browser bridge. [Auth](../platform/agent_factory/auth.py). | An opt-in RFC9068 RS256 bearer bridge now maps pinned issuer/subject identities to existing SQL owners, with offline and native-queue PG acceptance. Browser authorization-code/PKCE/state/nonce, revocable sessions, CSRF/logout and Chinese UI now pass synthetic HTTPS desktop/mobile and native SQL tests; see [browser/process milestone](BROWSER_AUTH_PROCESS_ENFORCEMENT.md). Real IdP/TLS integration, any required confidential-client/federated-logout adapter and production onboarding remain open; no identities were provisioned outside synthetic tests. |
| Operations and target capacity | Quarantine/restore/reclaim, bounded twenty-user pressure, official online PostgreSQL snapshot and independent restore. [Storage](../platform/agent_factory/storage_governance.py), [operations evidence](STORAGE_OPERATIONS.md). | Production monitoring, recovery objectives/PITR, sustained mixed-workload fairness and target-host capacity still require implementation/configuration and measurement. Recorded host is 4 CPU/16 GiB, not either target profile. |
| Scheduling | Immutable occurrence admission and guarded restart, with one active native poller. [Scheduler](../platform/agent_factory/scheduling.py). | Resolve and verify the upstream atomic lease-release boundary before supporting concurrent scheduler replicas. No cluster or multi-replica claim follows from current tests. |

## Current coding and literature evidence

[Draft PR23](https://github.com/Guanzhw/agent-factory/pull/23), exact
`a5173379ce7f119fdcf3540239fd82cb19ff86ab`, completed the DeepSeek public-source
coding example. Both public MIT files remain pinned to commit
`914de54a18ee3ccda772f578a217f7df6594c805`:

- `platform/agent_factory/go_http.py` — fixed destination and verified transport policy.
- `platform/tests/test_go_http.py` — corresponding transport boundary tests.

The [bounded fetcher](../platform/agent_factory/public_code_fetch.py),
[pinned knowledge adapter](../platform/agent_factory/public_code_knowledge.py) and
[governed composition helper](../platform/agent_factory/public_coding_research.py)
connect actual public retrieval and verified file hashes to immutable knowledge
bindings, native execution, a cited coding answer and checksum artifact. The
PR23 record preserves the initial Luna incomplete outcome. This subsequent stage
completed a new Luna conversation with separately pinned output revision 2:
**two SETTLED requests, 4,332 tokens, zero task-held tokens**, verified receipt and
artifact, and one native attempt. Its source evidence is `live-public-fetch`;
citation presence is verified, while semantic review remains a separate check.
The answer is native run content, not a fabricated native report artifact.

Only new ordinal 16 explicitly reported `MAX_OUTPUT_TOKENS`; its diagnostic
reported 2,010 input / 256 output / 2,266 total tokens as an unsettled provider
observation. This supported a new, bounded 512-output-token revision rather than
mutating the old 256-token definition. Ordinal 14's reason remains unknown.
Neither the new diagnosis nor later success settles or releases any historical
UNKNOWN reservation. Public coding success does not select a scientific model.

A separate **actual host PubMed/native Factory** run completed with two public
sources: PMID **42828563** and **42826496**. Both records are `abstract_only`, with
`fullTextAvailable=false`; source JSON, Markdown report and evidence ZIP were
persisted with hashes. Retrieval evidence is ready, the receipt is verified and
retrieval errors are empty. No scientific model/provider was called. This is a
new host-path result, not a correction of the historical zero-source/container
failure and not full-text or scientific-synthesis acceptance.

The new governed synthesis mechanism then consumed those real sources through a
pinned source snapshot and native knowledge binding. Its separate native run
completed with a verified receipt, JSON/Markdown synthesis artifacts, citation
structure/integrity checks and zero task-held tokens. **Model execution remained
`controlled-fixture`**, with `scientificProviderCalled=false` and
`scientificEndToEndAccepted=false`. The real provenance of the inputs does not
turn deterministic fixture output into live scientific-model evidence or a
verified conclusion. Independent semantic/domain review remains required.

These current outcomes were checked against the operator's sanitized
`luna-revision2-1-result.json`, `pubmed-native-1-result.json` and
`scientific-native-1-result.json` in the `luna-scientific-20261004` evidence set.
Final exact-head CI for this subsequent stage is tracked separately; earlier
PR checks do not certify later implementation changes.

Independent implementation can continue on concrete workflow/recovery and
scientific-provider integration gaps. No artificial per-call approval gate is
introduced for authorized subscription development. Production identity,
scientific-provider/question selection and compute deployment remain distinct
product decisions and acceptance work.

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
opt-in skips must retain their own provenance. PR21/PR22/PR23 are completed stages,
not certification of subsequent changes or the complete v0.3 product. The new
Luna/retrieval/controlled-synthesis results above do not close the production
identity, real scientific-provider, compute-allocation or target-capacity gaps.

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
