# Design

## Context

基线与动机见 [proposal.md](proposal.md)。反例直接保留在基线：`TaskWorkspace.tsx:116–117` 两处分支、`opencode_go.py:37–90` 两个类，以及下列指南；无需另建截图或原始报告。API 本地及远端投影均固定 `runtime: live`，四个 loopback 消费文件全在 tests，response stream 无其他消费者。

## Goals / Non-Goals

**Goals:** 补齐现行说明、正式前端和 wheel 的无 demo 边界，继续使用原测试 wire 契约。

**Non-Goals:** 不按关键词删除历史；不缩窄历史读取类型或修改 shared runtime 字段；不改正式 Go Model/通用注入、身份权限、默认部署、数据库或付费调用策略。

## Decisions

1. 将两个类整体移入 `platform/tests/go_http_fixture.py`，由该文件导入产品 `BASE_URL/USER_AGENT`；同步 `fixture_go_development.py`、`test_go_development_profile.py`、`test_opencode_go.py`，不加 product re-export、兼容开关或新 abstraction。保留端点、header 白名单、不重试及 response/transport cleanup；peer 增加“收到 Authorization”布尔观测，在定向 loopback 用例断言 false，不记录值。
2. UI 只删两个 demo 三元分支；`source` 优先级、`evidenceKind`、`validationStatus`、指标名和数据不变。使用既有 task-history 渲染检查与完整 npm check，不加实现镜像测试。
3. 精确指南范围：TEAM_MEMBERSHIP 去默认演示身份；DEPLOYMENT_VALIDATION 区分正式配置与测试 OIDC；APPLICATION_DEVELOPMENT 说明无默认 demo、默认无应用及 Research 显式入口；SECURITY 的身份及默认策略说明对齐账号管理员/成员自服务与现有 runtime bounds；MATERIAL_GOVERNANCE 旧 seed 标历史；MATERIAL_ASSEMBLY 对齐固定 live/production 与未验字段；EVENT_REPLAY 说明显式签名密钥；TOKEN_LEDGER 说明默认 pricing 为空、合成零价测试显式注册。SOURCE_SYNTHESIS_JOURNEY 仅增加退役提示，历史 audit/spec/review/evidence 不改。

## Risks / Trade-offs

- 迁移可能遗漏测试 imports 或改变流关闭 → 运行现有 Go contract/profile/HTTP 测试，并用既有 peer 定向验证 chat/responses 本机 socket、无 Authorization 与正常/异常清理；不跑无关全套 PG。
- 源码移除仍可能打包错误 → 执行独立 wheel 内容/隔离 import 两项既有测试并检查 wheel 内无两个 fixture 类；保持真实 adapter 可导入。此检查不声称完整 PG 生命周期验收。
- 文案可能误升格真实验收 → 逐条对照现有配置/API；历史结果不重分类，真实 IdP/模型/GPU 未验仍明确。

## Migration Plan

本方案先经非作者审查，再实施与目标验证；保留精确 base/head 和首失败事实，交完整 diff 简洁性复审。无数据迁移；按现有 CI 实际规则发布独立 Draft PR，由协调者核验并推进。

## Follow-up current documentation

补充基线 `f3f931b06f11b7ea910a9efe3d5b8a8ba89442ff`；统一只读复扫 150 份相关 Markdown 后冻结以下 12 文件。先审本清单，再一次修正文档，对照源码/链接、完整 diff 及适用 CI，不新增产品、测试、框架或验收记录包。

- 当前纠错：`docs/INTEGRATIONS.md:7,9,19–25`，纠正默认 demo/provider 注册，旧 Auto-Research/ORX fixture 和已移除测试入口明确为历史。
- 当前纠错：`docs/ACCEPTANCE.md:30,40`，仅 current matrix 对齐 member-self-service、历史 review 只读、默认无应用/模型及测试合成材料。
- 当前纠错：`docs/department-minimal-integration.md:15`，去掉现行合同中的 demo profiles 例外，明确产品 demo profiles 已退役。
- 当前纠错：`docs/plans/research-platform-acceptance-contract.md:41` 的 B01，分开隔离合成 OIDC 与实际身份验证，不使用退役 demo 登录；保留双用户、退出及真实 IdP BLOCKED 标准。
- 当前纠错：`docs/MEMBER_EXECUTION.md:15`，以显式成员发布/提交替代已移除 Research 脚本入口，保留原任务/run/requirement 连续性及取消限制。
- 历史限定：`docs/GO_DEVELOPMENT_PROFILE.md:3–14,23–28,52–59`，全文开头明确旧 product profile/loopback 启动入口退役，链接当前显式配置；不宣布 Go 模型协议退役。
- 历史限定：`docs/OPENCODE_GO.md:3–8`，导语不再把旧 development-profile 当当前 setup；保留原孤立适配器/契约证据。
- 历史限定：`docs/DESKTOP_WORKSPACE.md:3–28`，标明旧 OpenResearch 导航/准备入口及 demo 验收不构成当前操作指南。
- 历史限定：`docs/task-first-ux.md:3–10,39–41`，标明旧 seeded Auto-Research/实验 runner 入口退役，不宣布一般 UI 原则退役。
- 历史限定：`docs/CONTROLLED_COMPARISON_WORKFLOW.md:3–16,81–85`，限定旧应用/workspace/复现入口，保留结果与失败证据及通用 comparison 合同。
- 历史限定：`docs/LITERATURE_EVIDENCE.md:3–7,74–107`，限定旧模型/profile/helper/复现命令，保留受控与真实失败证据。
- 历史限定：`docs/INFERENCE_RECOVERY.md:5–9,109–131`，仅旧 ORX 应用扩展/复现块标历史；通用 core 原操作恢复、UNKNOWN 与取消契约保持有效。

空 `Settings.runtime_adapters` / `default_bindings` 不表示整个启动 registry 为空：保留 core 内置个人模型/工具适配器的事实，只否定默认 demo、应用/模型绑定及自动凭据配置。七份历史限定文件不重写原验收正文；其余历史里程碑、产品/测试/CI/资源策略不动。实际默认启动另有独立验证，不在本次纯文档变更重跑服务或创建账号。
