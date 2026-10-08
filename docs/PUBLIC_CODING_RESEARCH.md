# Public-source coding research development acceptance

This is an explicit coding-development example, not a production scientific
question. It reviews how Agent Factory's Go HTTP client retains managed proxy/CA
support while restricting destinations, redirects and retries.

Two MIT public files at exact commit `914de54a18ee3ccda772f578a217f7df6594c805`
were fetched through the existing managed HTTP environment on 2026-10-04.
Full-file and selected-excerpt hashes match immutable Git objects. The fetcher
allows only these two URLs, verifies TLS, disables redirects and retries, strips
origin authentication/cookies and bounds time and bytes. No host security setting
was changed. Fixture transport always produces `controlled-fixture` evidence.

The existing checksum application receives separately reviewed knowledge and
prompt materials, pinned into its immutable plan. Native Agno injects source data;
the model performs one checksum call and writes its answer into the native run.
The operator runner checks receipt, artifact hash, native attempt count, settled
usage and citation presence. Semantic review is a separate human/agent check,
not inferred from `[S1]` / `[S2]` strings. No arbitrary execution or new tool is granted.

## Actual results

[Sanitized evidence](evidence/public-coding-research-2026-10-04.json) retains the
sources, answer, exact usage states and finite diagnostic timeline.

- DeepSeek: completed, one native attempt, two SETTLED requests (2250 + 2528 =
  4778 tokens), zero held tokens, verified checksum artifact and both citations.
  Its review correctly describes the pinned destination guard, environment
  behavior, redirect/retry settings and the proxy-failure fixture. This establishes
  this development example, not production safety or invoice verification.
- Luna: first request SETTLED (2085 tokens), second response HTTP200 then
  `RESPONSES_INCOMPLETE`; usage UNKNOWN and 33280 held tokens remain. The campaign
  automatically stopped. No retry or release of the UNKNOWN hold occurred. The
  evidence does not establish the provider's reason for an incomplete response.
- Campaign now has 14 historical requests: 9 SETTLED and 5 UNKNOWN. The four prior
  UNKNOWN records are preserved; this stage added three settlements and one UNKNOWN.
  **Dual-model live acceptance remains incomplete.**

The successful answer is persisted native run content; its JSON export is not
misrepresented as a generated native report artifact. The checksum is a separately
verified native tool artifact. There is no claim that this operator-only runner
adds a complete browser research product flow.

## Retrieval diagnostics

Future ORX failure artifacts now include finite stage/code/failure-class/optional
exit-code facts. They never inspect or copy CLI text, URLs or exception chains,
and retain `transportCause: UNKNOWN`. Historical failure records are unchanged.
One separate current host PubMed GET returned HTTP200 and one source ID. It does
not establish that the old Linux container retrieval transport works or explain
the historical zero-source failure. Proxy credentials must not be forwarded via
container `--env` arguments; no such change was made.

## Verification and operation

Local default Python: 828 collected, 528 passed, 300 skipped, zero failures/errors,
47.622 seconds. Frontend: 78 passed. Ruff/Pyright passed; npm audit found zero
vulnerabilities. Serial focused PostgreSQL: one dual-protocol native research test
passed (10.409s), and one failed-retrieval diagnostic test passed (10.323s).
Mock protocol success is separate from the actual Luna failure above.

After an operator obtains and validates a real snapshot, the bounded loader in
`scripts/run_public_coding_research.py` accepts its JSON path together with the
existing campaign, exact model, disposable database URL and new evidence directory.
It neither creates billing authority nor clears campaign stops or runs a smoke.
Current campaign is stopped, so further live work must first resolve the recorded
protocol stop under existing policy; this document does not authorize bypassing it.

See [scope reconciliation](V03_SCOPE_RECONCILIATION.md) for remaining implementable
product work and external production inputs. Exact-head CI is recorded on the
stage's draft PR after commit; local results alone do not establish CI success.
