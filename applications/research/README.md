# 可选研究应用

本文描述集成源码 `3088c44` 的当前能力，不表示这些改动全部已合入 main 或完成最终验收。研究工作台已提供项目、约定、执行配置、显式启动/续接、运行记录及助手 QA 界面；固定 native Workflow 已接入实验 child、结果判断、自动后继轮次和终态精选记录。不是仅有首轮 HTTP 后端，也不再等待首版 UI 设计确认。

应用复用 core 认证、资源连接、发布治理、原任务执行、预算 scope、消息和内容权限。项目及其执行配置只供 owner 读取；精选研究记录按 core 内容授权团队可读，不因此公开整个项目、私有聊天、凭据或原始 artifact。

## 安装与配置

部署 composition root 显式构造 `ApplicationAssembly(name='research', install=research.public.install)`，注册研究和 QA 的固定 native Workflow，并把 `applications` 加入 Python import roots。应用不 import 部署模块；未安装时 core 不创建 research 表或路由。安装不启动研究或模型调用、不创建独立后台执行器、不取得数据库所有权，运行与关闭仍归 core。

安装本仓库发行包后，用 `agent-factory-research` 启动研究组合；默认 `agent-factory` 仍只启动底座。源码开发使用 `PYTHONPATH=applications:platform:deployment`。`npm run build:research` 构建研究入口，`npm run build` 构建无应用入口；构建不公开服务。

工作台可以选择个人模型连接、已部署环境和已发布实验工具，预览后明确发布执行 definition，再保存并确认项目约定。共享 definition 不保存个人 connectionRefs；运行使用成员自己的显式连接。空库不自动种入模型、工具或目标机，缺少实际环境注册/资源连接时必须先配置，不能用 fixture 冒充可用资源。

以下 HTTP 前缀均为 `/api/factory/research`。mutation 的 requestId 为 8–80 字符；同一命令重投恢复原收据，同键异内容冲突。接口使用当前认证 owner，不接受任意 owner 字段。

### 执行配置 HTTP

- GET `/setup`：读取当前候选模型、连接、环境和实验材料；读取不隐式创建个人绑定。
- POST `/setup/drafts`：`{requestId,name,modelConnectionRef,environment,experimentMaterialRefs,connectionRefs,budget}`。environment 为 `{adapterId,revision,connectionRef?}`，experimentMaterialRefs 为精确材料 pin。只创建私有意图和 preview，不发布。
- GET `/setup/requests/{requestId}`、GET `/setup/{id}`：恢复原配置命令或读取预览。
- POST `/setup/{id}/publish`：`{requestId}`，明确发布并返回 applicationRef、mode 和个人 connectionRefs。重新验证当前资源与预览中的准确 Workflow pin；pin 改变返回 `RESEARCH_SETUP_PREVIEW_CHANGED`，要求重新预览，不静默换版本。
- POST `/setup/qa/drafts`：`{requestId,name,modelConnectionRef,budget}`，使用同一预览/发布路径产生单一 `qa` mode，不需要实验或 GPU 环境。

## 项目与约定 HTTP

- GET `/projects?after=&limit=20`：`{items,nextCursor}`，摘要不含 goals，上限 100。
- POST `/projects`：`{requestId,title,assistantId?,researchAssistantId?}`，title 最多 120 字符。assistantId 是自己的历史 core endpoint 引用，researchAssistantId 是自己的稳定研究助手身份，二者不能互换。
- GET `/projects/{id}`：详情。
- POST `/projects/{id}/goals`：`{requestId,expectedVersion,agreement}`，追加目标版本并回到 draft。
- POST `/projects/{id}/confirm`：`{requestId,expectedVersion}`，确认当前约定并标 ready，不执行研究。
- POST `/projects/{id}/end`：`{requestId,expectedVersion,outcome,reason}`，outcome 为 not_met 或 cancelled；取消已有项目 scope，阻止新入口，不声称在途操作已停止，`resourceCleanup=not_observed`。ended 项目不能再修订，继续研究需新项目。

详情包含 `id,ownerId,title,assistantId,researchAssistantId,state,currentGoalVersion,goals,ending,createdAt,execution`。state 为 draft/ready/ended，新项目 version 为 0。goals 按版本升序：`{version,agreement,createdAt,confirmedAt}`。execution.available 表示当前约定和已存在运行是否允许申请启动/续接；false 带 reason，true 的 reason 为 null，不代替实际准入时的当前授权检查。

agreement 的 objective/evaluation/stopConditions 各为 1–4000 字符；resourceRefs 为 slot 到已有资源 ref（最多 30 项），保存引用不授予权限。budget 采用 core scope 语义：rounds/toolCalls 为正整数；tokenLimit 为空时 amountMicros/currency 同时为空；否则 tokenLimit/amountMicros 非负且 currency 为 USD/EUR/CNY。声明预算字段不等于当前选择的模型支持实际费用计量，准入仍须验证。

```json
{"objective":"测试目标","evaluation":"可核对评价标准","stopConditions":"达标或预算用尽停止","resourceRefs":{},"budget":{"rounds":3,"toolCalls":12,"tokenLimit":null,"amountMicros":null,"currency":null}}
```

目标历史不可覆盖，confirmedAt 是确认元数据。修改、确认、结束均检查 expectedVersion；409 `RESEARCH_GOAL_VERSION_CONFLICT` 要求读取最新状态，不可无条件重写。其他项目错误包括 `RESEARCH_PROJECT_NOT_FOUND`、`RESEARCH_AGREEMENT_REQUIRED`、`RESEARCH_PROJECT_ENDED`；权限和幂等错误沿 core 契约。

## Native 研究轮次

agreement 可包含 execution；缺失时仍可保存约定，但不能 start。正式研究配置选择准确发布的固定研究 Workflow，而非把任意应用当成自主研究组件。

```json
{"applicationRef":{"id":"published-application","version":1,"sha256":"<真实发布版本的64位摘要>"},"mode":"research","materialChoices":{},"connectionRefs":{},"deadline":1793000000,"perRoundCaps":{"rounds":1,"toolCalls":4,"tokenLimit":null,"amountMicros":null,"currency":null}}
```

示例 deadline 仅说明 epoch 单位，必须替换为明确且未过期的期限。materialChoices 是 slot 到材料 pin，connectionRefs 是 slot 到已有个人连接 ref，不提交秘密。每轮 caps 不超过项目 budget，计费类型/币种一致；完整目标/评价/停止文本不截断，组合超过 2000 字符或不符合所选 inputSchema 时拒绝。

- POST `/projects/{id}/start`：`{requestId,expectedVersion}`。固定研究路径的 202 包含 projectId/goalVersion/roundId/scopeId/allocationId/execution；202 是准入回执，不是执行成功。确认后由工作台“按当前约定启动或续接研究”按钮调用。
- GET `/projects/{id}/experiments`：固定研究路径返回 `{items,rounds}`。items 包含实验假设/条件和 attempts 的原 operationId/operation；rounds 包含 goalVersion、scope/allocation/task/delivery 身份、decision、terminal、terminalRecordId 和 continuations。实际任务与 artifact 仍通过授权的 core 任务接口读取。

固定 Workflow 依次取得约定和原证据，由所选模型决定实验或立即停止；实验使用 core 原 child/custody 身份，等待并读取实际结果后再判断 continue/stop。完成消费者发布精选终态，并在原 scope 和 deadline 内通过 core 事件安排后继；不建立第二套执行或恢复链。模型判断标为 agent_analysis，进程成功不等于科学达标。

同 request 恢复原操作，UNKNOWN 不重新 dispatch。项目 scope 跨目标修订保持原总预算与 deadline，不重置或扩容；旧运行保留原目标版本。存在未终态运行或同目标已有原轮次时，不用另一个 start 请求复制工作；已确认新目标的续接也由原约束检查。end 取消 scope，不释放 UNKNOWN 或伪造清理完成。

历史首轮路径仍由 `ResearchRuns` 处理不匹配固定 Workflow 的配置：其 start 返回 experimentId/attemptId/startRecordId，experiments 返回原首轮 execution。它不能承诺自主后继，也不会自动迁移既有实验为新轮次。历史切片证据见[开始记录验证](../../openspec/changes/restore-team-research-application/start-records-verification.md)；当前轮次见[native Workflow 验证](../../openspec/changes/restore-team-research-application/native-workflow-verification.md)。

## 精选研究记录

固定轮次创建实验时发布开始精选记录，完成消费者发布独立终态记录；历史首轮路径的 startRecordId 则是准备事务中的 pending_admission 快照。开始快照不会被覆写成实时状态，应读取原运行和后续终态。内容读取使用 `GET /api/factory/application-content/{id}`，作者可按 core sharing 接口撤回，命令回放不恢复撤回。

精选内容包含研究目标、假设/条件、原操作身份及有限结果投影，不自动共享原始 artifact、聊天或连接。任务/进程状态与 agent 判断的证据等级分开；创建记录、202、native completed 都不是科学结论已验证的证明。当前集成不包含研究相关接收者选择和主动关联消费者，不能将轮次后继事件当作团队广播或已交付团队价值。

## 私有研究 QA

研究部署显式安装 `ResearchQAWorkflow`：三个顶层步骤读取原消息上下文、调用所选 owner 模型、在本地验证 JSON 文本答案后写回原 core message。不使用 provider structured-output 选项、应用答案表、反向消息或 GPU/CLI/MCP 工具。

- POST `/assistants`：`{requestId}` 创建 owner 唯一稳定身份；GET `/assistants/me` 读自己的身份/配置，GET `/assistants` 读目录。
- POST `/assistants/me/configurations`：`{requestId,expectedRevision,applicationRef,connectionRefs,budget}`。budget 包含 caps/perQuestionCaps/deadline，使用已发布 QA 应用和个人连接。配置替换保留历史 endpoint 与身份关系，以恢复原问题；旧 endpoint 不接收新问题。
- POST `/assistants/{id}/questions`：`{requestId,text}`，text 为 2–2000 字符，返回 202；GET `/assistant-questions/{messageId}`：读取原消息/答案。原 request 的恢复先于读取当前配置，不因对方改配置而重派。

QA 的 BYOK 不进入平台账务：有限 rounds/toolCalls/deadline 必填，tokenLimit/amountMicros/currency 必须为 null，配置明确显示“操作额度受限，token/费用未计量”。不支持的 token/费用硬限额请求会被拒绝。

上下文最多扫描 50 个候选、提供 8 条当前共享研究记录（16 KiB），不包含私有聊天或 raw artifact。core reply 的 contentIds 绑定模型看到的全部证据输入，不只是所选引用；缺来源时返回证据不足，撤回任意输入会使整份派生答案在 core 读取路径不可用。

## 验证与剩余边界

[工作台验证](../../openspec/changes/integrate-live-research-workbench/verification.md)记录实际 HTTP/PG/浏览器、合成模型及 demo/本地合成 OIDC 的区别；[QA 验证](../../openspec/changes/add-research-assistant-qa/verification.md)保留分阶段目标结果。它们不是生产身份、真实模型研究价值或实际 GPU 的验收。早期记录中“UI/Workflow 尚未接入”描述的是当时切片，不是本 README 的当前实现状态。

`3088c44` 是未完成交付的集成快照，相关 Draft PR 尚未全部合入。此前精确 `551f1bf` 的 [full40206239436](https://github.com/Guanzhw/agent-factory/actions/runs/40206239436) 失败；夹具和 remote 取消观察顺序已有后续修复，但当前集成未有新的完整绿色验收。恶意 QA 已确认同 task/run 的队列 attempt 1→2 导致两次 HTTP，不能沿用早期 wire=1 目标结果声称重试边界已通过。

当前集成之外的主动关联、可复现交付包仍需各自整合与验收；完整运行中改目标旅程、真实模型自主研究/团队经验配对、另一成员复现、实际远端 GPU 和目标机容量也未完成。独立开发中的 UI 或机制目标通过不自动覆盖本快照，不把它们写成已合入能力。正式验收以[验收契约](../../docs/plans/research-platform-acceptance-contract.md)逐项证据为准。
