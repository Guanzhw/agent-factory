# Design

## Context

参见proposal动机与最终验收A01/A02/A03/A05。现有GovernedStorage提供事务/幂等命令，ApplicationRuns把requestId映射至原plan/task，native queue拥有执行。P1先行草稿176行在新增spec-first要求到达前写入，已暂停、未测试/提交；必须按本规范重新核对后才能恢复，不将历史倒写为spec先行。

## Goals / Non-Goals

**Goals:** 通过普通成员API创建可定位端点并向离线成员提交有收据的消息，复用原执行链。

**Non-Goals:** 不新增通用PersonalAgent、第二worker或恢复器，不在本change加入订阅轮询/研究schema；QA零GPU必须由后续受控研究问答组件落实并验收，本通用消息接口不虚称已做到。

## Decisions

- AssistantEndpoints保存生成ID、owner、name、固定app pin/mode、材料/连接引用、enabled。配置不可变；用新端点表达新配置，启停是独立幂等命令。团队列表只投影摘要，不暴露资源refs。复用GovernedStorage与command_table，避免新增锁/重试框架。
- 文本入口只支持无inputSchema，或声明string goal且没有其他必填字段的mode；消息同时作为goal和该schema的inputValues.goal，不引入任意字段映射DSL。配置拒绝不兼容入口，发送沿原输入校验。
- 消息保存sender、recipient endpoint、文本、发送请求键和唯一application request ID；采用已有DB事务幂等表，消息引用接收者不可变默认配置。客户端不能传owner/app/material/connection覆盖。
- 首次持久化消息的提交者调用已有ApplicationRuns.start；相同消息只能关联同一request ID，重复POST仅查原收据，不再次start。首次提交者在保存消息后/准入前崩溃则明确未确认，不猜测可重试；后续P3恢复协议另写spec。原执行幂等仍由既有task admission保证；消息层不维护另一份native终态。receipt读取ApplicationRuns.request原身份并只返回限定状态，不暴露plan handoff/资源或作者全job。
- 消息只能通过当前认证sender创建；内部接收者owner来自已启用端点且重新检查成员/app权限。HTTP与trusted native调用共享服务，不添加代理身份token。
- 无常驻收件worker：发送请求将有界工作交现有durable queue。订阅触发和崩溃前尚未准入的自动唤醒放P3，不声称当前覆盖提交前消息积压恢复。P2读取必须明确queued/prepared/unknown，不伪报已执行。

## Risks / Trade-offs

- 持久端点引用可能过期 → 准入按精确发布与当前成员检查；拒绝新操作而不改变原任务。
- 消息引起接收者费用 → 仅使用接收者显式配置的端点与既有预算；P3加入跨消息自动额度；本地验证无真实模型。
- 应用组件为trusted代码 → 当前端口不是沙箱，后续QA入口应绑定无训练权限/工具路径并实际计数验证。
- 停用与发送竞争 → 准入点重查状态；已准入操作保留原身份，停用不假冒已取消。

## Migration Plan

只增加core表和路由，默认无端点；旧配置与任务不改写。停用新入口即可撤回新增功能，保留收据，不删除数据库。按P1和P2分开提交/审查，之后P3通用事件预算、P6受限证据共享、P4–P8研究应用各自先写spec；P9综合验收沿用17项，不机械按文件建立change。
