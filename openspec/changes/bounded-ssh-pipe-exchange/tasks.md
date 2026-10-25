## 1. 规范与独立审查
- [x] 1.1 独立审查单一deadline、取消/cleanup、fresh guard及两个消费者接缝。
## 2. 窄模块
- [x] 2.1 实现单入口有界SSH exchange与无额外线程的Python3.12 nonblocking管道I/O。
- [x] 2.2 受控Linux子进程测试字节、背压、deadline、取消、reap及继承pipe；保留首次失败。
## 3. 集成与验证
- [x] 3.1 coordinator集成两个既有调用点/pinned argv，复审精确完整diff。
- [ ] 3.2 真实Windows runner验证nonblocking pipe；原身份/agent限制单独保留，不外推支持。

## Current evidence boundary

Module and consumer independent reviews passed after the async-guard/cleanup corrections; Linux final group 50/50 passed. Task 3.2 remains open: real Windows ran 50 with 46 passed/4 errors, including all 12 real pipe cases passing. The four fixture/collection errors have reviewed corrections and Linux 16/16 evidence, but the revised Windows head is not yet verified. Preserve the original failure. Windows credential support is independent and unimplemented; no complete Windows SSH support is claimed. See [verification](verification.md) and [review](review.md).
