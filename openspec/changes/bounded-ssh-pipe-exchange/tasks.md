## 1. 规范与独立审查
- [ ] 1.1 独立审查单一deadline、取消/cleanup、fresh guard及两个消费者接缝。
## 2. 窄模块
- [ ] 2.1 实现单入口有界SSH exchange与无额外线程的asyncio管道I/O。
- [ ] 2.2 受控Linux子进程测试字节、背压、deadline、取消、reap及继承pipe；保留首次失败。
## 3. 集成与验证
- [ ] 3.1 coordinator集成两个既有调用点/pinned argv，复审精确完整diff。
- [ ] 3.2 真实Windows runner验证Proactor；原身份/agent限制单独保留，不外推支持。
