# Offline baseline/candidate comparison contract

This is a data-validation contract, not a workload executor or a completed comparison product. `comparison_contract.py` uses only standard-library JSON, hashes and numeric checks. It performs no file access, dynamic imports, subprocesses, network calls, credential lookup, material publication, role grants or plan approval. Tests use synthetic records only.

## Existing boundary

The existing ORX adapter in `platform/agent_factory/orx_local.py` pins its reviewed toy source files and validates the specific seven-sample result. Its `toy_local_evaluation` evidence remains distinct. This module does not adopt those results automatically or expand the existing evaluator into arbitrary code execution.

Material publication and temporary-plan approval remain separate. Material references and a plan fingerprint in this contract are immutable declarations; validation does not establish that either was approved or that authorization is still current. A future integration must use current native ownership, plan review, runtime bindings, usage limits and effect custody checks.

## API and reviewed inputs

- `validate_contract(value)` returns a defensive copy of a strict schema-1 record. `fingerprint(value)` computes its canonical JSON hash; the digest is not a signature or verification of external bytes.
- `validate_candidate(contract, candidate)` permits replacements of existing files named in `allowedChanges`. Adds, deletes, evaluator/data changes and authority changes are rejected. Candidate and baseline file maps have the same keys.
- `compare_observations(contract, candidate, baseline_result, candidate_result)` evaluates supplied records only. It returns descriptive `improved`, `regressed`, `unchanged` or `inconclusive`, always with `executionVerified: false` and `scientificConclusionVerified: false`.

The contract contains exact dataset byte hashes, evaluator byte hashes and protocol revision; complete baseline file hashes; allowed changed paths; material id/version/hash references; a fixed plan fingerprint, capability set and resource limits; one primary metric with direction, unit and minimum improvement; a seed; and an ordered sample-set digest and sample count. Dataset origin must be declared `public` or `synthetic` with a license identifier. These declarations are not independent verification of licensing or public availability.

Paths are inert relative labels, not locations this module opens. No command, package install, URL, callback, model provider, secret or executable loader is accepted. The same authority hash is required for the candidate. Allowing a source-file replacement does not establish that the replacement is safe to execute.

For future producers, the ordered sample-set digest must identify the same ordered records, split and preprocessing selection for both variants. The pinned evaluator protocol must specify aggregation, missing-data handling and determinism. This module compares those hashes; it cannot recover or verify their underlying data. All completed results must cover the entire fixed sample set. Partial sampling cannot masquerade as a completed comparison.

## Result and failure semantics

Each observation pins the contract, variant file map, dataset, evaluator, ordered sample set, seed, metric ID, unit and result-artifact hash. A completed observation requires a finite bounded numeric value and exact sample count. Boolean numbers, NaN, infinity, mismatched units and changed pins are rejected with the fixed error `COMPARISON_CONTRACT_INVALID`.

Failed, cancelled and unknown observations require a null value and yield `inconclusive`. They are never coerced to zero or counted as improvement. Missing or malformed evidence is rejected, not ranked. A valid positive delta means improvement in the declared direction only when it strictly exceeds the threshold; a negative delta beyond the opposite threshold means regression. Values inside the threshold band are `unchanged`, not proof of statistical equivalence. One metric and one paired observation do not establish significance, uncertainty, generalization or scientific validity.

## Original offline-stage boundary

No core API or execution path is connected in this stage. Required future work includes separate material and plan approvals, verified actual dataset/evaluator/result bytes, an explicit bounded execution backend, original task/run and effect receipts, current authority before each effect, immutable baseline/candidate provenance, partial/UNKNOWN custody, real workload acceptance and user-facing review. Neither the pure contract tests nor existing toy ORX acceptance prove those steps complete.

## Controlled workflow continuation

The subsequent [controlled comparison workflow](CONTROLLED_COMPARISON_WORKFLOW.md)
connects this unchanged pure contract to separately reviewed fixed synthetic
inputs, immutable native plans, one bounded paired process and verified original
artifacts. The pure assessment still does not assert execution verification; a
separate native evidence envelope carries custody and byte verification. This
finite development workflow does not complete real scientific acceptance. See
the draft PR for actual process/PostgreSQL/browser and exact-head CI evidence,
and the [closure map](IMPLEMENTATION_CLOSURE_MAP.md) for remaining work.
