# Documentation map

This map separates current entry documents, component references, verification procedures, and dated evidence. The default product is the autonomous Research composition. The [2026-11-06 decision](plans/agent-autonomy-20261106.md) replaces the fixed research controller and two-entry product design.

Classification follows each document's purpose and the implementation it describes. Mentioning an old result or retired behavior does not retire a current interface. Mixed references remain under current components; their older examples and acceptance sections apply only to the stated revision. Plans record decisions and proposals, not proof that every item is implemented.

List the Markdown files for an inventory check:

```sh
rg --files docs -g "*.md"
```

## Current entry documents

- [Architecture](ARCHITECTURE.md) — `ARCHITECTURE.md`
- [Validate a change](DEVELOPMENT_CHECKS.md) — `DEVELOPMENT_CHECKS.md`
- [OpenCode model presets](OPENCODE_GO.md) — `OPENCODE_GO.md`
- [使用研究助手完成一个目标](PERSONAL_RESEARCH_SESSIONS.md) — `PERSONAL_RESEARCH_SESSIONS.md`
- [文档目录](README.md) — `README.md`
- [Runtime design](RUNTIME_DESIGN.md) — `RUNTIME_DESIGN.md`
- [Security and deployment assumptions](SECURITY.md) — `SECURITY.md`
- [Server shutdown](SHUTDOWN.md) — `SHUTDOWN.md`
- [在 Windows 启动本地服务](WINDOWS_LOCAL_START.md) — `WINDOWS_LOCAL_START.md`

## Component references

- [Scoped application content](APPLICATION_CONTENT.md) — `APPLICATION_CONTENT.md`
- [新应用开发指南](APPLICATION_DEVELOPMENT.md) — `APPLICATION_DEVELOPMENT.md`
- [Bounded assistant events](ASSISTANT_EVENTS.md) — `ASSISTANT_EVENTS.md`
- [成员助手端点与消息](ASSISTANT_MESSAGING.md) — `ASSISTANT_MESSAGING.md`
- [Durable task control commands](CONTROL_COMMANDS.md) — `CONTROL_COMMANDS.md`
- [Bounded native delegation](DELEGATION.md) — `DELEGATION.md`
- [Deployment declaration validation](DEPLOYMENT_VALIDATION.md) — `DEPLOYMENT_VALIDATION.md`
- [Removed development login](DEVELOPMENT_LOGIN.md) — `DEVELOPMENT_LOGIN.md`
- [Durable Factory event replay](EVENT_REPLAY.md) — `EVENT_REPLAY.md`
- [Trusted lifecycle cleanup observation](LIFECYCLE.md) — `LIFECYCLE.md`
- [Material assembly and execution bindings](MATERIAL_ASSEMBLY.md) — `MATERIAL_ASSEMBLY.md`
- [Versioned material governance](MATERIAL_GOVERNANCE.md) — `MATERIAL_GOVERNANCE.md`
- [成员发布与团队复用](MEMBER_PUBLICATION.md) — `MEMBER_PUBLICATION.md`
- [Member resource endpoints](MEMBER_RESOURCE_ENDPOINTS.md) — `MEMBER_RESOURCE_ENDPOINTS.md`
- [Member CLI and MCP tools](MEMBER_TOOLS.md) — `MEMBER_TOOLS.md`
- [个人凭据与连接](PERSONAL_CREDENTIALS.md) — `PERSONAL_CREDENTIALS.md`
- [Personal remote connection boundary](PERSONAL_REMOTE_CONNECTIONS.md) — `PERSONAL_REMOTE_CONNECTIONS.md`
- [Personal CLI and MCP connection lifecycle](PERSONAL_TOOL_CONNECTION_LIFECYCLE.md) — `PERSONAL_TOOL_CONNECTION_LIFECYCLE.md`
- [Personal CLI and MCP implementation contract](PERSONAL_TOOL_IMPLEMENTATION_CONTRACT.md) — `PERSONAL_TOOL_IMPLEMENTATION_CONTRACT.md`
- [Personal and team resources](RESOURCE_SHARING.md) — `RESOURCE_SHARING.md`
- [Schedule clock and preview contract](SCHEDULE_CLOCK_CONTRACT.md) — `SCHEDULE_CLOCK_CONTRACT.md`
- [Schedule rejection diagnostics](SCHEDULE_DIAGNOSTICS.md) — `SCHEDULE_DIAGNOSTICS.md`
- [Guarded native scheduling](SCHEDULING.md) — `SCHEDULING.md`
- [Team membership and account migration](TEAM_MEMBERSHIP.md) — `TEAM_MEMBERSHIP.md`
- [Durable token and amount ledger](TOKEN_LEDGER.md) — `TOKEN_LEDGER.md`
- [Explicit scoped trusted model-proxy deployment mode](TRUSTED_MODEL_PROXY_DESIGN.md) — `TRUSTED_MODEL_PROXY_DESIGN.md`

## Component references with historical examples

These documents contain current interfaces or operating instructions alongside earlier implementation notes. Read the contract separately from the dated results.

- [Explicit delegated aggregate process backend](AGGREGATE_PROCESS_CONTRACTS.md) — `AGGREGATE_PROCESS_CONTRACTS.md`
- [Public application interface v1](APPLICATION_INTERFACE.md) — `APPLICATION_INTERFACE.md`
- [Governed native workflow agents](GOVERNED_WORKFLOW_AGENTS.md) — `GOVERNED_WORKFLOW_AGENTS.md`
- [Integration boundaries](INTEGRATIONS.md) — `INTEGRATIONS.md`
- [Member execution and resource maintenance](MEMBER_EXECUTION.md) — `MEMBER_EXECUTION.md`
- [Owner model boundaries and compatibility](MODEL_PROTOCOLS.md) — `MODEL_PROTOCOLS.md`
- [Operations and restoration evidence](OPERATIONS.md) — `OPERATIONS.md`
- [Member plan execution](PLAN_POLICY.md) — `PLAN_POLICY.md`
- [Native bounded-process / shared-lease integration](PROCESS_LEASE_RUNTIME.md) — `PROCESS_LEASE_RUNTIME.md`
- [Governed remote execution and receiver-local bindings](REMOTE_BINDINGS.md) — `REMOTE_BINDINGS.md`
- [Trusted Factory execution placement](REMOTE_HANDOFF.md) — `REMOTE_HANDOFF.md`
- [Existing remote runtime / process lease integration](REMOTE_PROCESS_ISOLATION.md) — `REMOTE_PROCESS_ISOLATION.md`
- [Remote resources](REMOTE_RESOURCES.md) — `REMOTE_RESOURCES.md`
- [Remove demo modes: deployment update](REMOVE_DEMO_UPGRADE.md) — `REMOVE_DEMO_UPGRADE.md`
- [Single-host disk governance and recoverable retention](STORAGE_OPERATIONS.md) — `STORAGE_OPERATIONS.md`
- [Trusted-team integration](department-minimal-integration.md) — `department-minimal-integration.md`
- [Owner BYOK and disabled Factory billing](owner-byok-api.md) — `owner-byok-api.md`

## Verification procedures

These procedures exercise current test entrypoints. A procedure describes how to run a check; its existence is not a passing result.

- [Controlled schedule diagnostics browser acceptance](SCHEDULE_DIAGNOSTICS_ACCEPTANCE.md) — `SCHEDULE_DIAGNOSTICS_ACCEPTANCE.md`

## Design decisions and plans

- [Agno 3.1 and immutable task envelopes](decisions/0001-native-plan-envelope.md) — `decisions/0001-native-plan-envelope.md`
- [通用通信与长期研究助手的责任边界](decisions/0002-core-communication-research-assistant-boundary.md) — `decisions/0002-core-communication-research-assistant-boundary.md`
- [自主 Agent 与统一工作入口](plans/agent-autonomy-20261106.md) — `plans/agent-autonomy-20261106.md`
- [规划：应用服务组合与明确的生命周期归属](plans/application-composition.md) — `plans/application-composition.md`
- [规划：通用 v2 应用的远程执行契约](plans/remote-application-v2.md) — `plans/remote-application-v2.md`
- [研究平台验收进度 — 2026-10-25](plans/research-acceptance-progress-20261025.md) — `plans/research-acceptance-progress-20261025.md`
- [实现：可追踪的多轮科研与共享总预算](plans/research-iterations.md) — `plans/research-iterations.md`
- [最终验收契约与每 PR 精简审查](plans/research-platform-acceptance-contract.md) — `plans/research-platform-acceptance-contract.md`
- [新研究应用：底座能力与缺口](plans/research-platform-core-gap-analysis.md) — `plans/research-platform-core-gap-analysis.md`
- [团队研究应用分层交付规划](plans/research-platform-delivery-plan.md) — `plans/research-platform-delivery-plan.md`
- [Research release register — 2026-10-25](plans/research-release-register-20261025.md) — `plans/research-release-register-20261025.md`
- [规划：科研服务关闭结果与未完成资源收尾](plans/research-shutdown.md) — `plans/research-shutdown.md`
- [Reusable CLI/MCP identity bindings](plans/reusable-tool-identity-bindings.md) — `plans/reusable-tool-identity-bindings.md`
- [规划：任务历史分页与读取、执行收尾分离](plans/task-history-reads.md) — `plans/task-history-reads.md`
- [测试清理与 CI 成本收敛](plans/test-ci-cleanup.md) — `plans/test-ci-cleanup.md`
- [权限、运行限制与自主研究重构](reviews/agent-autonomy-20261106.md) — `reviews/agent-autonomy-20261106.md`
- [按设计重审与统一整理](reviews/design-aligned-cleanup-20261105.md) — `reviews/design-aligned-cleanup-20261105.md`

## Historical acceptance and handoffs

- [Acceptance ledger](ACCEPTANCE.md) — `ACCEPTANCE.md`
- [Application recovery and aggregate contracts — 2026-10-04](APP_RECOVERY_AGGREGATE_ACCEPTANCE.md) — `APP_RECOVERY_AGGREGATE_ACCEPTANCE.md`
- [Linux AT10 tree and receiver acceptance](AT10_TREE_ACCEPTANCE.md) — `AT10_TREE_ACCEPTANCE.md`
- [karpathy/autoresearch integration milestone](AUTORESEARCH_INTEGRATION.md) — `AUTORESEARCH_INTEGRATION.md`
- [Remote AutoResearch operator handoff](AUTORESEARCH_REMOTE_OPERATOR.md) — `AUTORESEARCH_REMOTE_OPERATOR.md`
- [Goal-driven AutoResearch session integration](AUTORESEARCH_SESSION.md) — `AUTORESEARCH_SESSION.md`
- [Actual backend contract acceptance](BACKEND_CONTRACTS.md) — `BACKEND_CONTRACTS.md`
- [Offline baseline/candidate comparison contract](BASELINE_CANDIDATE_CONTRACT.md) — `BASELINE_CANDIDATE_CONTRACT.md`
- [Bounded original-model research recovery](BOUNDED_RESEARCH_RECOVERY.md) — `BOUNDED_RESEARCH_RECOVERY.md`
- [Browser authentication and bounded process enforcement](BROWSER_AUTH_PROCESS_ENFORCEMENT.md) — `BROWSER_AUTH_PROCESS_ENFORCEMENT.md`
- [Cloud Codex handoff checkpoint — WIP](CLOUD_HANDOFF.md) — `CLOUD_HANDOFF.md`
- [Active: Windows SSH final verification — 2026-10-26](CLOUD_TASK_BOARD.md) — `CLOUD_TASK_BOARD.md`
- [Semantic continuation correction — 2026-10-08](CLOUD_WIP_HANDOFF.md) — `CLOUD_WIP_HANDOFF.md`
- [Complete inventory and prelaunch evidence](COMPLETE_INVENTORY_PRELAUNCH.md) — `COMPLETE_INVENTORY_PRELAUNCH.md`
- [Controlled baseline/candidate workflow](CONTROLLED_COMPARISON_WORKFLOW.md) — `CONTROLLED_COMPARISON_WORKFLOW.md`
- [Current delivery and review index](DELIVERY_INDEX.md) — `DELIVERY_INDEX.md`
- [Desktop workspace entry points](DESKTOP_WORKSPACE.md) — `DESKTOP_WORKSPACE.md`
- [Runnable development implementation checkpoint](DEVELOPMENT_IMPLEMENTATION_CHECKPOINT.md) — `DEVELOPMENT_IMPLEMENTATION_CHECKPOINT.md`
- [Explicit environment continuation](ENVIRONMENT_CONTINUATION.md) — `ENVIRONMENT_CONTINUATION.md`
- [Factory, OpenResearch, and research workloads](FACTORY_OPENRESEARCH_CONTRACT.md) — `FACTORY_OPENRESEARCH_CONTRACT.md`
- [Go development product profile](GO_DEVELOPMENT_PROFILE.md) — `GO_DEVELOPMENT_PROFILE.md`
- [Exact DeepSeek continuation](GO_EXACT_SINGLE_SMOKE.md) — `GO_EXACT_SINGLE_SMOKE.md`
- [Final authorized DeepSeek path validation](GO_FINAL_SINGLE_SMOKE.md) — `GO_FINAL_SINGLE_SMOKE.md`
- [Bounded Go validation — 2026-10-03](GO_LIVE_VALIDATION.md) — `GO_LIVE_VALIDATION.md`
- [Go managed egress compatibility](GO_MANAGED_EGRESS.md) — `GO_MANAGED_EGRESS.md`
- [Owner Chat Completions and OpenCode Go](GO_OWNER_CHAT_COMPATIBILITY.md) — `GO_OWNER_CHAT_COMPATIBILITY.md`
- [Ongoing Go project integration — 2026-10-04](GO_PROJECT_INTEGRATION.md) — `GO_PROJECT_INTEGRATION.md`
- [Safe Go rejection diagnostics](GO_REJECTION_DIAGNOSTICS.md) — `GO_REJECTION_DIAGNOSTICS.md`
- [Go diagnostics correction — offline only](GO_SAFE_DIAGNOSTICS.md) — `GO_SAFE_DIAGNOSTICS.md`
- [Implementation closure map](IMPLEMENTATION_CLOSURE_MAP.md) — `IMPLEMENTATION_CLOSURE_MAP.md`
- [AT10: bounded inference recovery for existing external work](INFERENCE_RECOVERY.md) — `INFERENCE_RECOVERY.md`
- [Pinned Linux ORX toy profile](LINUX_ORX.md) — `LINUX_ORX.md`
- [Public literature evidence, contract revision 2](LITERATURE_EVIDENCE.md) — `LITERATURE_EVIDENCE.md`
- [Local remote-process PostgreSQL admission diagnosis](LOCAL_PG_ADMISSION_DIAGNOSIS.md) — `LOCAL_PG_ADMISSION_DIAGNOSIS.md`
- [Luna compatibility and governed literature contracts — 2026-10-04](LUNA_SCIENTIFIC_CONTRACTS.md) — `LUNA_SCIENTIFIC_CONTRACTS.md`
- [Managed native attachment: bounded turn contract](MANAGED_ORX_PROVIDER.md) — `MANAGED_ORX_PROVIDER.md`
- [Approved application template to native task](MATERIAL_TEMPLATE_JOURNEY.md) — `MATERIAL_TEMPLATE_JOURNEY.md`
- [Native OpenResearch attachment boundary](NATIVE_ORX_ATTACHMENT.md) — `NATIVE_ORX_ATTACHMENT.md`
- [Native research text artifacts](NATIVE_RESEARCH_ARTIFACTS.md) — `NATIVE_RESEARCH_ARTIFACTS.md`
- [Native research command and result presentation](NATIVE_RESEARCH_RESULT_UX.md) — `NATIVE_RESEARCH_RESULT_UX.md`
- [OpenResearch tool adapter (legacy CLI boundary)](OPENRESEARCH.md) — `OPENRESEARCH.md`
- [Ordinary OpenResearch main page](OPENRESEARCH_MAIN_BODY.md) — `OPENRESEARCH_MAIN_BODY.md`
- [Backend contract for the OpenResearch workspace UI](OPENRESEARCH_UI_INTEGRATION.md) — `OPENRESEARCH_UI_INTEGRATION.md`
- [Original research custody recovery](ORIGINAL_RESEARCH_CUSTODY_RECOVERY.md) — `ORIGINAL_RESEARCH_CUSTODY_RECOVERY.md`
- [Actual task-owned ORX local experiments](ORX_LOCAL_EXPERIMENTS.md) — `ORX_LOCAL_EXPERIMENTS.md`
- [Ordinary personal commands through native Factory tasks](PERSONAL_NATIVE_COMMANDS.md) — `PERSONAL_NATIVE_COMMANDS.md`
- [Ordinary native OpenResearch sessions](PERSONAL_OPENRESEARCH.md) — `PERSONAL_OPENRESEARCH.md`
- [Ordinary OpenResearch research journey](PERSONAL_OPENRESEARCH_JOURNEY.md) — `PERSONAL_OPENRESEARCH_JOURNEY.md`
- [Ordinary native OpenResearch project creation](PERSONAL_OPENRESEARCH_PROJECT_CREATION.md) — `PERSONAL_OPENRESEARCH_PROJECT_CREATION.md`
- [PR47 installation closure handoff](PR47_INSTALL_HANDOFF.md) — `PR47_INSTALL_HANDOFF.md`
- [PR47 package-data path repair](PR47_PACKAGE_PATH_REPAIR.md) — `PR47_PACKAGE_PATH_REPAIR.md`
- [Released original custody and PR50 research continuation](PR50_RELEASED_CUSTODY_HANDOFF.md) — `PR50_RELEASED_CUSTODY_HANDOFF.md`
- [Production and research decisions still needed](PRODUCTION_DECISIONS.md) — `PRODUCTION_DECISIONS.md`
- [Public-source coding research development acceptance](PUBLIC_CODING_RESEARCH.md) — `PUBLIC_CODING_RESEARCH.md`
- [First real local baseline accepted — 2026-10-07](RESEARCH_BASELINE_ACCEPTANCE.md) — `RESEARCH_BASELINE_ACCEPTANCE.md`
- [本地受管 baseline：准备 → 训练 → 独立评价](RESEARCH_BASELINE_BOOTSTRAP.md) — `RESEARCH_BASELINE_BOOTSTRAP.md`
- [One candidate and original-invocation recovery](RESEARCH_CANDIDATE_HANDOFF.md) — `RESEARCH_CANDIDATE_HANDOFF.md`
- [One candidate and bounded target recovery: reviewable next step](RESEARCH_CANDIDATE_RECOVERY_PLAN.md) — `RESEARCH_CANDIDATE_RECOVERY_PLAN.md`
- [私有开发控制面：存储确定后的最小执行计划](RESEARCH_CONTROL_ENVIRONMENT_PLAN.md) — `RESEARCH_CONTROL_ENVIRONMENT_PLAN.md`
- [Research custody runtime integration handoff](RESEARCH_CUSTODY_RUNTIME.md) — `RESEARCH_CUSTODY_RUNTIME.md`
- [Operator-owned local research adapter](RESEARCH_LOCAL_ADAPTER.md) — `RESEARCH_LOCAL_ADAPTER.md`
- [Fixed eager-model memory preflight](RESEARCH_MODEL_PREFLIGHT.md) — `RESEARCH_MODEL_PREFLIGHT.md`
- [原适配器 optimizer / compile 有界资源诊断](RESEARCH_OPTIMIZER_PREFLIGHT.md) — `RESEARCH_OPTIMIZER_PREFLIGHT.md`
- [Original research queue closure: read-only root-only gate](RESEARCH_ORIGINAL_QUEUE_READ.md) — `RESEARCH_ORIGINAL_QUEUE_READ.md`
- [Unintegrated tokenizer preparation checkpoint](RESEARCH_PREPARATION_WIP.md) — `RESEARCH_PREPARATION_WIP.md`
- [Fixed SDPA compatibility diagnostic and baseline handoff](RESEARCH_SDPA_DIAGNOSTIC.md) — `RESEARCH_SDPA_DIAGNOSTIC.md`
- [Target admission and first-baseline boundary](RESEARCH_TARGET_ADMISSION.md) — `RESEARCH_TARGET_ADMISSION.md`
- [Canonical research compiler search path repair](RESEARCH_TOOLCHAIN_PATH_HANDOFF.md) — `RESEARCH_TOOLCHAIN_PATH_HANDOFF.md`
- [Read-only uv target diagnostics](RESEARCH_UV_LAUNCH.md) — `RESEARCH_UV_LAUNCH.md`
- [Shared compute admission and production identity integration](RESOURCE_IDENTITY_INTEGRATION.md) — `RESOURCE_IDENTITY_INTEGRATION.md`
- [Verified source to controlled synthesis](SOURCE_SYNTHESIS_JOURNEY.md) — `SOURCE_SYNTHESIS_JOURNEY.md`
- [v0.3 application workflow gap audit](V03_APP_GAP_AUDIT.md) — `V03_APP_GAP_AUDIT.md`
- [v0.3 final requirement audit](V03_FINAL_REQUIREMENT_AUDIT.md) — `V03_FINAL_REQUIREMENT_AUDIT.md`
- [Factory v0.3 scope reconciliation — 2026-10-04](V03_SCOPE_RECONCILIATION.md) — `V03_SCOPE_RECONCILIATION.md`
- [Verification record](VERIFICATION.md) — `VERIFICATION.md`
- [OpenCode Go development adapter — prior isolated stage](history/opencode-go-isolated-stage.md) — `history/opencode-go-isolated-stage.md`
- [Managed original OpenResearch attachment: connection probe](managed-openresearch-probe.md) — `managed-openresearch-probe.md`
- [Ordinary personal OpenCode sessions](personal-agent-sessions.md) — `personal-agent-sessions.md`
- [Platform OpenResearch environments (first increment)](platform-openresearch-environments.md) — `platform-openresearch-environments.md`
- [OpenResearch on an owned Linux server](ssh-openresearch-environments.md) — `ssh-openresearch-environments.md`
- [Task-first frontend contract](task-first-ux.md) — `task-first-ux.md`

## Screenshot evidence notes

- [研究代码任务截图](images/research-coding-task/README.md) — `images/research-coding-task/README.md`
- [模型输出设置：实际浏览器截图](images/research-tool-budget/README.md) — `images/research-tool-budget/README.md`

## Evidence files

`docs/evidence` contains dated JSON, CSV, and SVG records. `docs/images` contains screenshots from named scenarios. A retained image or result does not certify a later commit. The adjacent Markdown record defines its scope.

Current results belong to the corresponding PR and its exact-commit checks. The historical October acceptance ledger is not a current release checklist.
