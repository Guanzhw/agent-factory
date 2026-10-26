# Windows SSH integration checkpoint

当前状态以 [精确提交验收](verification-installed.md#current-result--2026-10-26) 为准：`445a2ce` 的 Windows 三组与 fast 均成功，cleanup 修复已通过独立审查与实际安装检查。下表是历史工作树检查点；最终 full 待运行，跨机器 Linux 验收仍 BLOCKED。

These are coordinator observations of the evolving integration worktree, not a final exact-head acceptance result. Earlier probe failures and review blockers remain in their original records.

| Check | Actual result / boundary |
|---|---|
| Linux loopback and onboarding after scoped-process integration | 4 passed, zero skipped, 10.702s; `/tmp/af-windows-scope-linux-loopback.log`. Scope integration `beba` and packaging `b039` were stable during this working-tree run; no claim that the entire tested worktree equals one commit. |
| Web `npm run check` | 490 tests / 53 files, 22.75s; lint/typecheck/build passed. `/tmp/af-windows-ssh-web-check.log`. Production and all-dependency npm audits: zero findings. |
| First local Pyright | 46 errors, 8 warnings during the unfrozen implementation stage. Retained as a failed/incomplete check; final static verification remains required. |
| Native PostgreSQL group | Coordinator session22598 exited 0: 4 passed, zero skips, 100.623s; `/tmp/af-windows-scope-native-pg.log`. Original native wait/restart, uncertain continuation, accepted continuation ACK loss and distinct inputs through the real helper passed. Transport is a synthetic local fixture, not Windows execution or SSH-network ACK-loss proof. Heavy test slot released. |
| Installed-wheel tests/workflow | Added but awaiting independent review and actual run. Source imports or packaging edits alone are not installed-wheel acceptance. |
| Credential manager review | Cleanup review BLOCKED; correction in progress. No complete product credential acceptance. |

## Separate platform evidence

PR137 exact `860e460` [full40241711220](https://github.com/Guanzhw/agent-factory/actions/runs/40241711220)
has Windows 1317 passed / 871 skipped / zero errors (233.556s); PG remains pending.
This run concerns the Linux SSH stack, not all current Windows credential edits.

Stage B probe exact `8848b53` passed three actual Windows scenarios in
[40242397177](https://github.com/Guanzhw/agent-factory/actions/runs/40242397177),
[artifact12617236560](https://github.com/Guanzhw/agent-factory/actions/runs/40242397177/artifacts/12617236560).
The two earlier failures remain recorded. Probe success does not establish the
product manager/consumer path.

The later low-level Windows group passed 58 of 59, with one strict assertion
failure (`251 != 244`). Its cause is not yet established; diagnostic change
`0aba479` has CI pending. The expected result has not been relaxed, and the group
is not PASS. See [owned-process evidence](verification-owned-process.md).

## Ownership and remaining gates

Root: integration and CI coordination; assistant_endpoints: credential manager;
research_frontend: low-level Windows diagnosis; assistant_messages: installed-wheel
tests; foundation_review: independent review; pr104_independent_review: CI work.

Actual Windows→Linux target execution is NOT RUN. GPU allocation/binding remains
UNIMPLEMENTED; C/D target model, hardware and execution inputs remain missing.
Local Linux, synthetic Windows probes and frontend checks do not close those
boundaries. No paid model/GPU call, deployment or new real credential access was
performed for this checkpoint.
