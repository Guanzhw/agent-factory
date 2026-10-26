# R4 新研究准入独立审查

Reviewer: `audit_quality`，非方案/实施作者；仅审查，不修改产品代码。

## 方案审查 — 2026-10-26

精确范围：`62614177c23c4d2cd0caf6b7c91418e74fde8ad4` → `57ddd10f88289efdaa6b0f3185c57c5035f99b30`；包括首稿 `e91886eeb773dd20cf2aa3a9801412e18a456bda` 及其两个规范文件修订。工作区 `/workspace/agent-factory-fix-research-admission`，change `restrict-new-research-admission`；产品代码未改变。

**方案 PASS。实施仍须等待 R1 已审实现整合后的精确新 base，由作者与 reviewer 确认依赖差异；本结论不放行当前基线上的产品实施，不代表实现或运行验收通过。**

- 已阅读 AGENTS、ARCHITECTURE、开发检查、OpenSpec config 及本 change 全部 diff，并追读实际 rounds/runs/public/setup、GovernedStorage command 表与原 ExecutionEditor/测试。命令主键 `(actor_id, request_id)` 和原 fingerprint 校验足以区分原意图，无需新兼容注册表或路由开关。
- 仅三类持久 action 进入原意图核对：`research.start` 使用原 `start` 指纹，`research.round.start/resume` 使用原 `round.start` 指纹，完整保留 project/expectedVersion 及 owner 校验；其他 action 和同键异内容冲突。新请求才进入当前完整 `{kind,id,revision,sha256}` pin 检查，并在原事务内拒绝零新分配/执行。
- 首稿存在未装 Workflow 的恢复承诺缺口：public 仅安装 ResearchRuns，而 round 指纹不等于 legacy 指纹。修订用小范围共享原 command 核验及既有 intent→receipt 处理解决，不增加旧执行器或另一套 round 装配。`round.resume` 无 request 时只返回保存结果，不能重发后继事件；有原 task 时只读原收据；无 task 时仅交原 request/allocation 给 core 复核，404/超时不得解释成可替代派发。
- 明确保留当前成员/owner、原项目/版本、原 allocation/task/run/pin、UNKNOWN 占用与 scope 取消。没有 Workflow 时不承诺 round 列表投影或领域步骤；缺失旧 pin 执行代码的 paused 任务不能通过换 pin 或新任务“兼容恢复”。R1 finalization-only 注册不等于提供原 executor。
- UI 复用现有 `setupApi.candidates.workflowPin`，全字段比对，既有不匹配选项可见且解释原因，禁提交但不自动选替代。候选接口读取失败要呈现错误；原记录/请求恢复不依赖候选接口。无需新 API、通用策略框架或固定名称白名单。
- 测试迁移必须保留原 owner/幂等/预算/UNKNOWN/取消断言；旧首轮用显式持久 fixture，真实新准入和事务回滚验证移至唯一 rounds 路径。实施复审重点核无 Workflow 的持久 round/start/resume、跨项目/版本/动作冲突、pin 变化/结束后的原收据，以及 UI 错误 sha/原旧选项；不接受只改 fixture pin 追绿。

独立检查：精确规范范围 `git diff --check` PASS；缓存 CLI、`OPENSPEC_TELEMETRY=0` 执行 `validate restrict-new-research-admission --strict` PASS；工作树干净。没有运行 PG、浏览器、外部模型或真实旧 paused 续执行。后续需对确认的新 base→实现 head 全 diff 和 R1 依赖增量分别复核。

## R1 依赖及 stacked 基线确认 — 2026-10-26

已读 R1 `d9f92acffcfd6937c4c43ad8c3ddc205e6e1b9f6` 的实际产品差异：rounds 仅 `_publish/_finalize` 改动，public 仅增加已知 `62614177` pin 的 finalization-only owner，不提供旧 executor。R4 方案仍适用；不新增未部署 R1 中间 pin 的兼容。R1 最终文档 base `e4afcb6eb230ad079f13ac87dc5e3d581701b390` → stacked spec `00e32d01cb08758fd54138049b79a4ef64849984` 仅两个规范提交、五文件；规范 subtree `b1483d5757694c082d3d704ac8911e25edddeae1` 与已审 `57ddd10f` 相同，旧分支保留。此 gate 已 PASS 后作者开始实施。

## 完整实现与简洁性审查 — 2026-10-26

精确范围：base `e4afcb6eb230ad079f13ac87dc5e3d581701b390` → 产品/测试 `93064bc6b2926ed8e4c3c67705ea2c1736a0f237`（20文件 +576/-151），并审阅其后仅新增44行 verification 的 `46c0611bfddb944cb40dc12fc7e284c0806dad2c`。全部产品、测试、fixture、浏览器脚本、规范和验证文档 diff 均已阅读；不是仅凭测试通过判断。

**实现、简洁性及验证文档 PASS，无整改阻断。仅覆盖本地已记录范围，不代表 full/Windows、真实旧 paused executor 或外部模型/GPU 验收。**

- `ResearchRuns.original_intent` 用持久三类 action 选择原指纹，复用原 `db.old` 校验 project/expectedVersion；两条调用方先检查成员和项目 owner。`recover_intent` 合并原重复代码，有 task 时直接查原 request/allocation 收据，无 request 的 resume 直接回保存结果，不重新发事件。无 task 仍将完整原请求和原 allocation 交 core，并保留项目结束/原 scope 的阻断；没有把 404 当成可创建替代请求的证明。
- 删除 legacy fresh 的 scope/allocation/experiment/start-record 创建分支，无 Workflow 公开入口也不能绕过新准入。rounds 在既有 admission/数据库事务内先核原命令，再检查新请求的完整当前 pin；availability 先识别原运行，旧 pin/当前目录不可用不阻断已有任务回执。原 owner、预算、UNKNOWN、取消职责不变；无新状态机、兼容模式、注册表或重试。
- UI 复用现有候选 endpoint，按 kind/id/revision/sha256 四字段过滤应用/mode；原不兼容选择以禁用项显示且不能提交，不静默代选。候选失败显示错误并禁提交；ProjectDetails 保留历史/结束入口。`ApplicationMode.nativeComponent` 仅补已有 API 字段类型，没有新后端接口或固定 mode 名称策略。
- 显式 `research_history_fixture` 只构造旧持久数据，不形成产品入口；原 owner、请求重放、预算冻结、UNKNOWN、完整目标与取消断言保留。删除的 fresh publication/binding 用例转为当前 rounds 的绑定后回滚，真实 PG 检查 scope/allocation/request/domain 均回滚；原 start 记录读取/共享撤销仍单独保留。无 Workflow 的 round-shaped PG fixture 明确只证明 command/receipt 协议，不冒称旧 Workflow 实现存在。
- 浏览器新增选项检查仍要求恰好空项/research，先前 exact label 失败改成实际 combobox 定位；logout 后等待登录按钮可用再导航，保留原跨 owner 404、刷新/返回/重登、结果和产物断言。没有放宽 timeout、跳过场景或改产品登录行为。
- 独立 AST 核对：R4 在 rounds 仅改 availability/_prepare/start；R1 `_publish/_finalize`、public 注册、workflow 与 peer_sources 全文保持。首失败 checkpoint `67574c82597ac5b998f538c283648287253667e9` 的产品仍等于 base，已审规范未改变。完整 diff-check 与当前 change strict 独立通过。

已读取证据目录 `/workspace/agent-factory-fix-research-admission-v2-evidence/`：后端首失败7项（2 FAIL/4 ERROR）、UI首失败4 FAIL/2 PASS、legacy适配前15项（4 FAIL/5 ERROR）均保留。修后33便携 PASS；真实PG9项/21.884s和原native5项/22.775s，零skip；npm check 53files/495tests、lint/typecheck/build通过，官方production/full audit均0漏洞；source-PYTHONPATH Pyright0errors/0warnings、Ruff及architecture512/0/0。初次缺happy-dom/旧venv类型错误没有隐藏或通过改产品追绿，验证文档明确解释来源。

真实 desktop 浏览器最终报告：业务 API 未mock，loopback TLS/合成OIDC、PG/native运行，1 round/1 experiment、原结果及artifact、跨owner读写404、pageErrors/consoleErrors均0；模型/本地工具为合成，团队读取仍标 `NOTDONE: P7 API absent`。两次前置浏览器失败及截图保留。PG清理回执仅默认三数据库、fixture sessions0、task tables及live fixture processes为空。reviewer 未重复占用PG或浏览器资源。

剩余边界：完整 release、Windows、mobile、真实模型/ORX/GPU未跑；旧 paused 缺原 executor 仍不可宣称续执行，无 Workflow 不提供 round 列表/领域步骤，R2/R3不在此增量。后续只补审查副本或主代理checkbox时核精确文档增量即可，不追加自指记录。
