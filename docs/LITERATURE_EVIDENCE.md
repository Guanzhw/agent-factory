# Public literature evidence, contract revision 2

This opt-in workflow produces a bibliography and short located excerpts, a
readable Markdown report and an owner-scoped downloadable ZIP. It uses the
ordinary material/application publication, exact-plan approval, native Agno queue,
current connection guards, effect journal and artifact API. It calls no model
provider and makes no scientific synthesis claim.

## Current measured boundary

The actual Linux binary passed exact SHA-256 and version preflight inside the
bounded task container. The integrated reviewed application then attempted one
public PubMed query (`retrieval augmented generation`, limit 1). The endpoint
could not be reached. The original attempt was not silently retried or routed
through host networking. The native workflow produced a failure report and ZIP,
with zero sources and positive process-stop evidence. This is actual containment,
queue and failure-artifact evidence, **not successful live literature retrieval**.
See [the measured receipt](evidence/literature-public-2026-10-02.json).

Separate controlled-transport native tests cover successful invented metadata,
paper excerpt/locator/hash, explicit missing full text, bundle hashes, independent
publication/plan approval and cross-owner download rejection. Their artifacts are
labeled `controlled_literature_fixture`, including the resulting report/ZIP.
Neither these tests nor an older standalone metadata retrieval certify a live
end-to-end source package on this Linux host.

## Approved execution and evidence contract

- Legacy discovery revision 1 retains its Windows binary pin and transport
  contract. Discovery revision 2 selects the approved platform pin; Linux uses
  `a847d07e8c4c3f2efc47c3549fd27f52c9999b46a21451d4c07ec12de292b8cd`.
  Unknown platforms fail closed. The source remains ORX 0.2.13 at
  `f336b121525d99364e2dee4fe90b2784894a54e6`.
- Revision 2 requires `TaskLinuxRetrievalProvider`, not the old unrestricted
  host subprocess provider. The selected environment bounds aggregate memory,
  CPU rate, aggregate CPU time and cgroup task/thread count; commands also have
  wall-time and combined stdout/stderr bounds. The pinned image/guardian and
  exact task container identity are inspected. Retrieval scopes use the existing managed storage inventory with evidence protection; their receipts are not reclaimable scratch. Exit of the Docker client alone
  is insufficient: namespace/process stop must be positively confirmed.
- Only this explicitly installed retrieval profile uses the daemon's existing
  `bridge`. It publishes no ports and does not change networks, DNS, host security
  or firewall rules. There is no host-network/proxy fallback. This fixed CLI
  containment is not an egress allowlist or a hostile-code tenant sandbox.
- `orx_discover` uses an immutable installed query ID, corpus and limit (1–3).
  The initial public application installs only `public-rag-v1`; the material
  validator still rejects arbitrary paths, URLs and code. Task goals and private
  user data are not sent as search text. Editing approved research workloads is
  a future explicit contract, not an unrestricted string escape.
- `orx_paper` and `orx_text` accept canonical IDs only from this task's persisted
  discovery evidence. No arbitrary URLs/files/commands are accepted. They reuse
  `OpenResearchAdapter.paper`. For supported arXiv IDs they request extracted
  full text explicitly; alphaXiv's generated overview is never presented as
  primary-source text. Other sources remain abstract-only or explicitly
  `full_text_unsupported`; fetch failures are distinct from confirmed absence.
- Each record contains source ID, canonical URL, SHA-256, hash scope, a bounded
  contiguous excerpt and exact character/line locator in that rendition. The
  hash is of decoded CLI text or the metadata abstract, **not a PDF hash**.
  Full paper text is not exported. Empty and failed retrievals never acquire a
  fabricated quote, full-text flag or scientific conclusion.
- `orx_sources_report` writes Markdown plus ZIP (`report.md`, `sources.json`,
  `manifest.json`) through existing owner-scoped artifacts/downloads. The inner
  manifest hashes the two content files; the artifact receipt hashes the ZIP.
  Persisted uncertain effects refuse automatic replay. No access or launch grant
  is recovered merely from a local file or a native COMPLETED status.

All four tools are explicitly registered at revision `2`. The operator must use
`orx-evidence-v2` and distinct plan/material policy revisions; old contract hashes
and whitelists remain intact. The deterministic `LiteratureEvidenceModel` has an
explicit zero-provider price contract, separate from any future provider model.
Its final status is `blocked-no-sources` when the evidence set is empty, even if
the native queue successfully delivered the failure report.

## Reproduce

Use the official locked dependencies and the already approved exact Linux ORX
binary/image described in [LINUX_ORX.md](LINUX_ORX.md). No credential provisioning
or security/network changes are part of this setup. Supply only an isolated
loopback PostgreSQL fixture and trusted absolute binary path.

```sh
# Offline controlled-source contracts and actual native PostgreSQL workflow:
PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest \
  test_literature_evidence test_literature_postgres -v

# Explicitly permit one small public query; an unreachable endpoint is reported:
FACTORY_LITERATURE_PUBLIC_ACCEPTANCE=1 \
FACTORY_LITERATURE_EVIDENCE_DIR=/workspace/scratch/literature-evidence \
PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest \
  test_literature_postgres.ActualLiteraturePostgresTests -v
```

The actual test exports a sanitized result receipt, report and ZIP. It separately
records `liveSourceSuccess`; passing failure-handling assertions must not be
reported as successful public retrieval. It creates/removes only its own
randomly named database, workspace and exactly attributed disposable containers.
`local_literature_profile.literature_settings` and
`publish_literature_application` are trusted installation helpers. They do not
install handles or publish definitions from an HTTP request, create real users,
or enable a public service by default.

## Least-capability experiment mappings

The five experiment adapters retain revision 1 unchanged and additionally
register revision 2. Inspect/wait/logs require only `research:read`; run/cancel
require only `compute:local`. New profile materials and the application have
separate immutable IDs and separate `localExperimentRead` / `localExperimentRun`
connection requirements. Every current tool resolves its own exact connection.

Experiment identity is anchored to the immutable admitted launch pin and actual
native provenance so switching from inspect to run does not create a different
experiment/effect. Receiver anchors are read from the historical admitted proof;
this grants no handle or execution authority. Reclaim uses the original admitted
receiver-local launch pin and environment, even after current rights end. The
receiver guard is unchanged: its entire tool connection capability set must fit
both the source material permissions and source connection ceiling.

Revision 2 launch operations use the selected environment's total deadline for
the multi-command/current-authority operation; each CLI command remains capped.
Revision 1 retains its old behavior. The actual receiver acceptance uses two
native apps and independent databases with explicitly controlled ASGI transport;
it passed in 117.686 seconds, including distinct publication/plan approvals, one real run (baseline 16 / candidate 0), positive process stop and original receiver-pin reclaim. It does not certify production TLS, deployed hosts or real provider compute.

## Remaining implementation decisions

Real model SDK integration must enforce each native provider attempt (including
streaming and retries) against the ledger, then reconcile actual usage. An API
key alone does not implement or certify this. Production browser login/session
entry and identity-provider integration remain code work beyond native managed
roles. Mutable reviewed research workspaces require a selected workload,
version/approval rules and evaluator/source boundaries beyond the fixed toy and
installed public query profile.

AT10 remains an explicit integration risk: a native model failure must not
implicitly cancel independently approved deterministic external work. The future
provider integration needs a reviewed failure/ownership boundary and a regression
that fails the model while observing the original external work and receipt.
This stage does not claim that boundary has been solved. Real provider, identity,
workload and target-host acceptance require separate decisions and evidence.
