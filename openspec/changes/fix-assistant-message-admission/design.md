# Design

## Context

基线见 proposal。`Store.reserve_task` 在原 task 命中后才进入消息 fresh gate，并与端点启停、sender 成员变更共享 `af_admission` 栅栏。事件的 pending 扫描已具公平轮转，存在 reserved/UNKNOWN task 时 recover 只读取原收据。

## Goals / Non-Goals

**Goals:** 修复 C2/C3，沿现有服务恢复同一原请求，并使预算与无预算消息共享准入语义。

**Non-Goals:** 不新增控制器、重试调度或策略框架；不扩大任务上限；不更改终局无 task 的 hold 释放，不把 404/时间经过当未执行证明；不迁移历史 rejected 记录。

## Decisions

1. Store 的真实活跃任务上限改用稳定 `ACTIVE_TASK_CAPACITY_EXHAUSTED` 错误码，HTTP 429 不变。AssistantEvents 将此码纳入安全投影，只对此精确 429 和既有 stopping 条件保留 pending；其余终局判断仍在 admission 栅栏内核对无 task。不能笼统把所有 429 变成可重试。
2. AssistantMessages 将 recipient、sender、endpoint resolve 和完整 expected/prepared 指纹核对放在预算条件之前；预算条件只包裹 require_budget 与 allocation 匹配。移除为早 return 服务的 owned 读取；resolve 已有相同原端点读取能力。Store 原 task 早返回保持不变。
3. 验证先新增失败回归并保存输出，再实现。真实 PostgreSQL 测试从实际 Store 容量拒绝到容量释放，断言原身份、held allocation 和 native submit 计数；复用原恢复 fixture 验证无预算准备窗口撤权、原指纹冲突和原 UNKNOWN 不重派。便携单元覆盖精确错误分类与非容量拒绝保留 fence。

## Risks / Trade-offs

- [错误码改变外部 detail] → 保持 HTTP 429，将稳定码加入错误投影测试；不依赖可变英文文案。
- [真正终局无 task 仍持有分配] → 明确保留现有边界；安全释放需要额外 fence/计费证据，本次不声称解决。
- [历史已 rejected 容量事件不自动恢复] → 无迁移或批量重派；此次修复针对新失败分类。
- [合成数据库模型不能证明 live provider] → 分开记录静态、便携及 PostgreSQL 验证，外部模型/GPU/Windows/浏览器未验。
