# 可选研究应用

研究工作台提供项目约定、个人执行配置、显式启动/续接、运行记录、助手 QA、主动关联和成果包。固定 native Workflow 使用原实验 child、实际结果、受预算限制的后继轮次和精选终态记录；成员可查阅授权的团队经验，并按明确选择的证据生成可下载交付包。

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

精选内容包含研究目标、假设/条件、原操作身份及有限结果投影，不自动共享原始 artifact、聊天或连接。任务/进程状态与 agent 判断的证据等级分开；创建记录、202、native completed 都不是科学结论已验证的证明。主动关联使用下述显式启用的接收范围，轮次后继事件不等于团队广播。

## 私有研究 QA

研究部署显式安装 `ResearchQAWorkflow`：三个顶层步骤读取原消息上下文、调用所选 owner 模型、在本地验证 JSON 文本答案后写回原 core message。不使用 provider structured-output 选项、应用答案表、反向消息或 GPU/CLI/MCP 工具。

- POST `/assistants`：`{requestId}` 创建 owner 唯一稳定身份；GET `/assistants/me` 读自己的身份/配置，GET `/assistants` 读目录。
- POST `/assistants/me/configurations`：`{requestId,expectedRevision,applicationRef,connectionRefs,budget,associations?}`。budget 包含 caps/perQuestionCaps/deadline，使用已发布 QA 应用和个人连接。配置替换保留历史 endpoint 与身份关系，以恢复原问题；旧 endpoint 不接收新问题。
- POST `/assistants/{id}/questions`：`{requestId,text}`，text 为 2–2000 字符，返回 202；GET `/assistant-questions/{messageId}`：读取原消息/答案。原 request 的恢复先于读取当前配置，不因对方改配置而重派。

QA 的 BYOK 不进入平台账务：有限 rounds/toolCalls/deadline 必填，tokenLimit/amountMicros/currency 必须为 null，配置明确显示“操作额度受限，token/费用未计量”。不支持的 token/费用硬限额请求会被拒绝。

上下文最多扫描 50 个候选、提供 8 条当前共享研究记录（16 KiB），不包含私有聊天或 raw artifact。core reply 的 contentIds 绑定模型看到的全部证据输入，不只是所选引用；缺来源时返回证据不足，撤回任意输入会使整份派生答案在 core 读取路径不可用。

## 团队经验与主动关联

在助手配置中显式设置 `associations: {enabled: true, maxRecipients: 2}` 可启用主动关联；maxRecipients 为 1–20，默认 2。省略或关闭不会自动启用。它复用 QA 端点、原操作额度与期限；收到关联事件不会因此获得训练或 GPU 权限。

研究进展按固定词项规则从当前有权读取的团队研究记录中选择相关成员，按配置限制接收人数；重复事件保留原候选，不广播兜底。模型可产生 related、conditions_differ 或 not_related，分析标为 agent_analysis，不修改他人记录。GET `/associations?after=&limit=50` 返回目录（上限 50），GET `/associations/{id}` 查看当前有权读取的分析和来源。

研究轮次也直接检索原团队记录，不必先有一条关联才能复用。下游判断、实验和精选结果保留完整来源权限依赖，展示窗口不截断授权依赖。撤回任意必要来源后，派生分析、研究投影和成果访问会重新检查权限；不能把摘要或附件复制成可绕过撤回的副本。原已授权操作仍按其身份观察、取消和收尾，不因撤回重新派发。

## 精选证据与成果包

约定的可选 `evidence` 字段为 `{toolMaterial:{id,version,sha256},fields:{metrics:"metrics",source:"source",run_recipe:"recipe"}}`。成员通过工作台选择准确 CLI 材料和原输出字段；fields 可选择 1–3 个角色，角色仅为 metrics/source/run_recipe。模型不能扩大分享范围。修改其他约定字段时保留原 evidence；当前目录不可用时界面保留原精确材料引用，不静默替换。

采集使用原 CLI 工具结果和 task/run/material 身份，保存明确选择的字段为 JSON 证据附件。未选择的原始文件、凭据和工具输出不会整份打包。配方和指标仍标为 producer_declared，需要实际复现核对；缺字段、缺原输出或无有效配方如实显示缺项。

- POST `/projects/{id}/deliveries`：`{requestId,expectedVersion}`，201 返回不可变 manifest；同请求恢复原包，不重新执行实验。
- GET `/deliveries?after=&limit=20`：授权目录，上限 100。
- GET `/deliveries/{id}`：manifest、已选记录和 missingEvidence；未终态轮次、未发布记录或证据不足不伪装完整成果。remainingQuestions 为 not_provided 时不能理解为没有剩余疑问。
- GET `/deliveries/{id}/download`：授权后返回 `application/zip`，包含 manifest 和所选证据。仅作为权限依赖的来源不因此自动导出附件；损坏、超限或失去来源权限时拒绝整包。

没有来源的包仅作者可读。有来源的包对每个访问者检查全部原来源，作者也不能绕过撤回。下载不会执行包内命令；另一成员应在自己的环境、资源和新任务预算下复现或继续，不能复用旧 UNKNOWN 操作来启动新工作。

## 验证与运行边界

实际 native/PG、受控 CLI、demo/本地合成 OIDC 的浏览器和跨成员复现证据见[集成验证](../../openspec/changes/restore-team-research-application/integration-verification.md)，首次失败和修复均保留。后端组合完整 CI 与最终 UI/新增接缝检查的准确范围分别记录；真实模型自主研究与团队价值、实际 GPU、外部身份服务和目标机容量尚未验收，按[最终验收契约](../../docs/plans/research-platform-acceptance-contract.md)分别判定。移除应用仍可运行底座，但遗留应用任务需要原组件才能继续；缺组件时保留原任务及未确认资源，不伪造完成或重新派发，移除应用也不删除现有数据。

完全移除应用及其运行时声明后，底座仍可在确认原操作全部停止后将执行记为失败并结算。它不会代替缺失应用补写研究终态或后继事件；重新安装也不会自动补写这些业务记录。需要继续原应用收尾责任的装配撤回，应保留原运行时声明。
