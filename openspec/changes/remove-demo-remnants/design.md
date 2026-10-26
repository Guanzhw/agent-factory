# Design

## Context

基线与动机见 [proposal.md](proposal.md)。反例直接保留在基线：`TaskWorkspace.tsx:116–117` 两处分支、`opencode_go.py:37–90` 两个类，以及下列指南；无需另建截图或原始报告。API 本地及远端投影均固定 `runtime: live`，四个 loopback 消费文件全在 tests，response stream 无其他消费者。

## Goals / Non-Goals

**Goals:** 补齐现行说明、正式前端和 wheel 的无 demo 边界，继续使用原测试 wire 契约。

**Non-Goals:** 不按关键词删除历史；不缩窄历史读取类型或修改 shared runtime 字段；不改正式 Go Model/通用注入、身份权限、默认部署、数据库或付费调用策略。

## Decisions

1. 将两个类整体移入 `platform/tests/go_http_fixture.py`，由该文件导入产品 `BASE_URL/USER_AGENT`；同步 `fixture_go_development.py`、`test_go_development_profile.py`、`test_opencode_go.py`，不加 product re-export、兼容开关或新 abstraction。保留端点、header 白名单、不重试及 response/transport cleanup；peer 增加“收到 Authorization”布尔观测，在定向 loopback 用例断言 false，不记录值。
2. UI 只删两个 demo 三元分支；`source` 优先级、`evidenceKind`、`validationStatus`、指标名和数据不变。使用既有 task-history 渲染检查与完整 npm check，不加实现镜像测试。
3. 精确指南范围：TEAM_MEMBERSHIP 去默认演示身份；DEPLOYMENT_VALIDATION 区分正式配置与测试 OIDC；APPLICATION_DEVELOPMENT 说明无默认 demo、默认无应用及 Research 显式入口；SECURITY 同段对齐账号管理员/成员自服务；MATERIAL_GOVERNANCE 旧 seed 标历史；MATERIAL_ASSEMBLY 对齐固定 live/production 与未验字段；EVENT_REPLAY 说明显式签名密钥；TOKEN_LEDGER 说明默认 pricing 为空、合成零价测试显式注册。SOURCE_SYNTHESIS_JOURNEY 仅增加退役提示，历史 audit/spec/review/evidence 不改。

## Risks / Trade-offs

- 迁移可能遗漏测试 imports 或改变流关闭 → 运行现有 Go contract/profile/HTTP 测试，并用既有 peer 定向验证 chat/responses 本机 socket、无 Authorization 与正常/异常清理；不跑无关全套 PG。
- 源码移除仍可能打包错误 → 执行独立 wheel 内容/隔离 import 两项既有测试并检查 wheel 内无两个 fixture 类；保持真实 adapter 可导入。此检查不声称完整 PG 生命周期验收。
- 文案可能误升格真实验收 → 逐条对照现有配置/API；历史结果不重分类，真实 IdP/模型/GPU 未验仍明确。

## Migration Plan

本方案先经非作者审查，再实施与目标验证；保留精确 base/head 和首失败事实，交完整 diff 简洁性复审。无数据迁移；按现有 CI 实际规则发布独立 Draft PR，由协调者核验并推进。
