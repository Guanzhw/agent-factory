# Proposal

## Why

固定研究Workflow需要从当前原任务取得可信事件来源，而不是相信模型输入中的contentId。现有事件订阅深度硬上限20也会静默阻断用户已确认的较长有界研究。应用需区分明确技术拒绝与科学停止，目前错误只保存异常类型，不足以说明原拒绝原因。

基线f25c899；这是已有P3消费者的三个窄接入口，不增加执行链或公开通用Store接口。

## What Changes

- 新增只读delivery_for_task(owner, task_id)，从原任务和既有request/delivery/allocation关联得到不透明内容与lineage引用。
- 去除maxDepth的硬编码20上限，保留非负深度、原根/深度继承、TTL、候选20和既有scope总预算。
- 在已有error字符串字段保存有限安全大写HTTP code；其他异常仅保存类型，不保存任意消息内容。

## Capabilities

### New Capabilities

- `original-assistant-inputs`: 原任务绑定的事件输入引用和安全技术拒绝说明。

### Modified Capabilities

无主spec修改；增量约束既有bounded-assistant-events实现。

## Impact

仅assistant_events、专属测试和此规范。无main/schema/UI改动，不新增API、预算scope、消息或任务。真实模型/GPU验证不在本单元。
