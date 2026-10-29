# Design

## Context

基线 `e52dd2774cd5ba9b2687d11bf811875e64ba1ccc`。固定 Agno 3.1.0 普通队列重领走 `arun`；`acontinue_run` 只用于 PAUSED，正常非流式 Workflow 最后才持久结果。已有 native 终态协调覆盖不了 reply 已提交、Workflow 尚未完成的窗口。当前仅有本轮隔离测试部署证据，没有接入真实用户部署；pin 约束不等于已有必须兼容的真实在途任务。

## Goals / Non-Goals

**Goals:** 先通过“原回复 commit → 实际退出 → 同 task/run 重领 → 零新增模型 → 原生正常完成”正链，再核紧邻的身份、撤权与未知操作边界。

**Non-Goals:** 双版本组件、配置/迁移 UI、通用恢复框架、缓存或第二 worker；不修复模型已调用但 reply 未保存、关联分析 answer 尾窗，不伪造旧 pin 或 task 终态。

## Decisions

1. 仅在 `qa.py` 增加窄的已存回复读取/核对方法，在 `qa_workflow.py` 现有首步调用。复用 `_write`、`_original`、`_match`、原消息读接口和来源核权；先分流原事件 delivery，关联分析仍按原路径。无 reply 返回空判据后继续原三步，不创建占位回复。
2. 有 reply 时必须有原 `research_qa_inputs`，校验 owner/run/message/配置与完整来源集合；双方当前成员和原依赖均可读，含未引用来源。在既有来源/admission 锁内，复用 `reply_for_task(owner, task, savedText, originalDependencies)` 的既存分支精确核对 raw reply task/正文/依赖，不写新答案；缺输入、来源不可用或身份不符则拒绝、零新模型。
3. 有效原回复由首步返回 `StepOutput(content=原回复投影, stop=True)`，Agno 原生保存并结束同一 run；不再 answer/record、不改消息身份或时间、不手写任务终态。原生取消和平台 effect/custody/预算结算仍是独立事实，reply 不清除 unknown。
4. 两个文件修改使既有 implementation hash 自然变化，组件 ID 保持 `research-qa`；不保留假 hash、不注入双实例、不改 setup/assistant/UI。原消息和历史数据保留受权读取，不保证旧草稿在新 pin 下发布或旧任务在新代码下续跑。实际部署前按下述检查处理，而不是新增兼容代码。

## Risks / Trade-offs

- [退出发生在 reply 保存前] → 保留未修边界，不把模型内存结果当持久答案。
- [来源撤回、异 run 或未结束操作] → 拒绝非法复用；即使有回复也不提前结算，沿已有 guard，不新增策略框架。
- [目标存在旧 pin 在途任务] → 当前目标未接入，不能称无在途；部署时核实原版本/任务，先让原运行版本完成再切，不盲重放、改绑或覆盖代码。

## Migration Plan

无数据迁移。上线前核已授权目标的旧 pin queued/running/paused/结果未确认任务；未核实或仍在途时不切该部署，保留原运行版本和原记录。旧草稿/配置不偷偷改 pin，确需后续使用时沿原操作显式重建，不保证透明升级。回滚同样先核新 pin 在途，不将新任务送回旧实现。

验收先做真实 PostgreSQL/原生 worker 的服务 OS 退出正链，记录同 task/run、attempt、原回复与模型计数、真实完成及结算；必要身份/撤权/unknown 反例及关联回归随后。脚本模型计数不等于真实研究质量；不为本片增加配置或抽象。非作者需明确给出过度实现结论。
