## 1. 规范与独立审查
- [x] 1.1 独立审查单一deadline、取消/cleanup、fresh guard及两个消费者接缝。
## 2. 窄模块
- [x] 2.1 实现单入口有界SSH exchange与无额外线程的Python3.12 nonblocking管道I/O。
- [x] 2.2 受控Linux子进程测试字节、背压、deadline、取消、reap及继承pipe；保留首次失败。
## 3. 集成与验证
- [x] 3.1 coordinator集成两个既有调用点/pinned argv，复审精确完整diff。
- [x] 3.2 真实Windows runner验证nonblocking pipe；原身份/agent限制单独保留，不外推支持。

## Current evidence boundary

Module and consumer independent reviews passed after the async-guard/cleanup corrections; Linux final group 50/50 passed. Task 3.2 remains open: real Windows ran 50 with 46 passed/4 errors, including all 12 real pipe cases passing. The four fixture/collection errors have reviewed corrections and Linux 16/16 evidence, but the revised Windows head is not yet verified. Preserve the original failure. Windows credential support is independent and unimplemented; no complete Windows SSH support is claimed. See [verification](verification.md) and [review](review.md).

### Later exact-head Windows result

Task 3.2's bounded-pipe platform verification is now complete: dc1fead Windows portable job121308976958 passed 49/49, zero skips, 2.905s, selecting three portable classes and excluding the actual Linux helper (separate Linux 16/16 passed). Earlier 50-case errors and old d3 selector WinError10038 remain recorded. The same run's ASKPASS job failed; credentials and whole Windows SSH acceptance remain open outside this bounded-pipe task. Old d3 full PG is still running, not a final PASS.

### Final integrated result

Exact860e460 full40241711220 now passed all seven jobs, including Windows
1317 passed/871 skipped and PG2183 passed/5 skipped; the bounded-pipe tasks above
are complete within their stated scope. The old 50-case failure and later49-case
pass remain separate historical results. Documentation-only follow-up requires
review/new exact fast; PR137 is not yet merged. This does not close DraftPR138
production Windows credentials, GPU implementation or actual target acceptance.
