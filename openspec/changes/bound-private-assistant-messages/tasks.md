# Tasks

## 1. Contract review

- [ ] 1.1 coordinator和独立reviewer核对完整规范、最小core签名及锁序，确认后才实施。

## 2. Implementation ownership

- [x] 2.1 assistant_messages实现endpoint可选automaticBudget及owner检查、消息原allocation准备/恢复、只读message_for_task；仅assistant_endpoints.py/assistant_messages.py和专属测试。
- [x] 2.2 coordinator集成Store fresh reserve hook、main构造，以及P3 prepare传原allocation/订阅匹配窄接点；无新增HTTP allocation字段/队列/表。

## 3. Verification

- [ ] 3.1 便携验证字段、legacy endpoint兼容、双方可见、精确输入关联、缺失映射拒绝。
- [ ] 3.2 串行真实PG验证同键并发、rollback、prepare崩溃/原request恢复、reserved UNKNOWN零submit、撤权barrier/普通instances旁路、P3单allocation及预算一致。
- [ ] 3.3 独立完整base/head精简审查、必要整改及集成检查；QA零GPU与C03真实价值继续由应用验收，不外推本change通过。
## Core settlement follow-up

- [x] Declare absent budget service explicitly in non-budget lifecycle fixtures; preserve completion-versus-cancellation assertions under the new budget-only fallback.

- [x] Verify ordinary budgeted roots use the existing atomic completion path even without an application callback.
- [x] Verify HELD rollback and subsequent original-root observation release the same allocation exactly once, without receipt mutations or re-dispatch.


证据见verification.md。3.1/3.2保留未勾选：已有便携31项、PG首轮5/6及修正单例通过，后续19项最终组合已通过；全部列举边界（独立成员撤权/到期及缺映射故障）仍须由review核对覆盖，不能据计数补勾。3.3待独立精确head审查/集成CI。
