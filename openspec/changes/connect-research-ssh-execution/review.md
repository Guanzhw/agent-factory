# Independent SSH integration review

Reviewer: `foundation_review`, independent of the implementation authors.

- Base: `d6c8f620322eb4fe246c300000da93b53a2d4163`
- Reviewed head: `8eee759626057e061532164c23c24d9c4a135759`
- Conclusion: **code review PASS** after the output-budget correction. This is not final full-suite or D01 acceptance.

The earlier review at `13755c7` was blocked, not passed. It found that a Research process profile could allow 16 MiB output while the helper transfers at most 256 KiB and the default local artifact limit is 64 KiB. A stopped original operation could then remain held indefinitely because complete archival could never succeed. That finding remains part of the review history.

Specification `e1e25c1` preceded correction `8eee759`. New dispatch requires a local artifact allowance of at least 64 KiB and an output cap no larger than the minimum of the helper and local artifact bounds. Rejection occurs before target registration, preflight or custody intent. Original persisted/UNKNOWN operations do not acquire this new admission restriction on replay; their original identity and archival/release responsibility remain intact. No truncation or relaxed release proof replaces complete archival.

The author recorded 40 portable cases passed, zero skips, targeted Pyright zero errors/warnings, strict OpenSpec and whitespace checks. The first portable fixture errors remain in [verification](verification.md#reject-unsupported-ssh-output-budgets-before-dispatch). These results support the correction; they are not real GPU or final integrated execution evidence.

## Native and Research evidence at this checkpoint

- `83e020f` records the updated native SSH group: 3/3 passed, zero skips, 95.656s. It covers original native wait/restart, uncertain continuation recovery and distinct retained inputs/actual archived output. The fixture substitutes SSH transport; it does not establish remote GPU execution or the complete Research consumer.
- The Research integration's first case failed in 35.567s because the controlled model fixture's signature had drifted. `9661db2` corrects that fixture and retains the original failure. The corrected case has **not yet been rerun** at this checkpoint; no Research end-to-end PASS is claimed.
- GPU allocation/execution remains **unimplemented in this CPU helper/provider**, which rejects GPU bindings. Target execution method, possible scheduler and hardware/resource parameters also remain to be frozen. D01 is not merely waiting for credentials or hardware access.

Final integrated checks and exact-head publication remain separate gates. Earlier successful loopback and portable runs retain their documented scope; this review does not upgrade them to a combined final result.
