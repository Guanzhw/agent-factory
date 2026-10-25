# Tasks

## 1. Contract review

- [ ] 1.1 coordinator和独立reviewer核对完整规范、最小core签名及锁序，确认后才实施。

## 2. Implementation ownership

- [ ] 2.1 assistant_messages实现endpoint可选automaticBudget及owner检查、消息原allocation准备/恢复、只读message_for_task；仅assistant_endpoints.py/assistant_messages.py和专属测试。
- [ ] 2.2 coordinator集成Store fresh reserve hook、main构造，以及P3 prepare传原allocation/订阅匹配窄接点；无新增HTTP allocation字段/队列/表。

## 3. Verification

- [ ] 3.1 便携验证字段、legacy endpoint兼容、双方可见、精确输入关联、缺失映射拒绝。
- [ ] 3.2 串行真实PG验证同键并发、rollback、prepare崩溃/原request恢复、reserved UNKNOWN零submit、撤权barrier/普通instances旁路、P3单allocation及预算一致。
- [ ] 3.3 独立完整base/head精简审查、必要整改及集成检查；QA零GPU与C03真实价值继续由应用验收，不外推本change通过。
## Core settlement follow-up

- [ ] Verify ordinary budgeted roots use the existing atomic completion path even without an application callback.
- [ ] Verify HELD rollback and subsequent original-root observation release the same allocation exactly once, without receipt mutations or re-dispatch.

