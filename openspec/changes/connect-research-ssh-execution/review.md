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

## Final cumulative code-review checkpoint: fa0b736

Independent reviewer `foundation_review` reported **PASS** for exact base
`5cde50a3e252b28e9f08863251724805267de840` → head
`fa0b73663c9e173d4130060103f8dfc9defbd50f`: 72 changed files, with all 18
production-file diffs byte-identical to the earlier reviewed production change.
This supersedes the earlier review scope, without erasing the 13755c7 blocker
or earlier failed fixtures. Production is frozen at this checkpoint.

Exact [fast40231189473](https://github.com/Guanzhw/agent-factory/actions/runs/40231189473)
succeeded. Targeted evidence now includes Research `9a048ca` 1/1 (25.758s),
browser `b88499a` PASS, loopback `bb10f29` 1/1 (8.608s), and actual accepted
continuation ACK loss plus controller SIGKILL at `a6552d2`, 2/2 (33.152s).
The [native evidence](verification-native-inputs.md#accepted-ack-loss-and-actual-controller-sigkill)
records the exact fault injection; it is not merely service-instance recreation.
No final full-suite PASS is available.

Both PR136 and PR137 remain Draft/unmerged. Dependency PR136's older
[full40228654327](https://github.com/Guanzhw/agent-factory/actions/runs/40228654327)
ended FAIL: combined 2068 cases, 2057 passed, 2 failures, 4 errors, 5 skips,
2091.848s. Four lifecycle errors were corrected at 5cde50a; the two failures
remain under investigation. GPU allocation/binding is still unimplemented and
rejected, while external-network faults and actual target model/GPU/hardware
acceptance remain unverified. Code-review PASS does not close those gates.
