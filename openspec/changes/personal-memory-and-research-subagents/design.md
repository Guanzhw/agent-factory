# Design

## Context

基线与目标见 proposal.md。当前原生 PG 已有个人记忆表/API，但 Research 仅接会话摘要；平台已有持久子任务，Research 尚无派发工具。固定 Agno **3.1.0**，先记忆、后子助手，各自一个可验收交付边界。两片技术上不互为前置。

| 现有实现 | 可复用与已确认缺口 |
| --- | --- |
| `platform/agent_factory/main.py:82`、`auth.py`、`applications/research/assistants.py` | 共用 `PostgresDb`、原生用户隔离、稳定 owner；不用每轮 task ID 存私人记忆。 |
| `applications/research/session_tools.py`、`sessions.py` | 已有授权/停止检查、call/effect、工具事件和逻辑会话；新增工具沿这些边界接入。 |
| Agno `UserMemory` / PG CRUD | 原生存储可直接用。`MemoryTools.update_memory/delete_memory` 缺 owner 范围；`MemoryManager` 辅助模型调用不满足现有 `DelegatingModel` 的 RunOutput 契约，不直接启用。 |
| `delegation.py`、`composition.py`、`delegated_operations.py` | 已有 parent/root/child、原票据、资源继承、预算、停止、原结果；`create` 缺 Research v2 `input_values` 传递，Research `_execution` 只识别主轮次。 |
| `ssh_operation_waits.py`、原生 external execution | 已示范原 requirement + ControlCommand 回填。现有 SSH 选择器不可直接给 Research 用；需窄应用接线，不新增队列。 |

## Goals / Non-Goals

**Goals:** 主助手自主使用既有 owner 模型和工具；记忆只补原生 CRUD 的应用边界，子助手只补研究身份/上下文/原等待接线。保持现有用户、凭据、运行事实、效应核对和组件职责。

**Non-Goals:** 不新增记忆模型、自动全历史抽取、向量库、后台记忆服务、通用 Team/消息总线、工作区 fork 框架、角色系统或默认账户。不把配置、fallback、容量上限当功能交付。首片子助手分工不证明任意同文件并发写、跨成员记忆共享、真实 GPU 或 30 活跃会话容量。

## Decisions

### 1. 个人记忆由当前主模型调用少量原生 CRUD

在 Research 注册查找、记住、修改、忘记单条工具；可信执行上下文决定 owner，模型没有 owner 参数。直接调用共用 native DB，原生 `UserMemory` 保存条目。查找仅按 owner/内容查询，复用现有工具输出边界并如实标明分页/截断，不添加 embeddings。模型按需要查找，不向每次请求无界注入全部记忆。

新增 ID 在写入前由原 run/call 派生或绑定于已有 effect 请求；重复调用核对原 ID/载荷。修改先按 owner 取原条目，再 upsert；删除带 owner。原生 upsert 以 memory_id 冲突，不能把底层 DB 当权限层。delete 实际无 bool 返回，按 owner 读前/读后确认，不能依据返回值伪报成功。DB 错误必须传为真实失败/未确认。

首轮真实 Go 验收发现，模型用多个空格分隔关键词检索回答偏好，得到空结果后误认为未保存。固定 3.1.0 的 `search_content` 实际是连续文本的 ILIKE 查询，不是语义检索。工具说明须明确使用短连续片段、无 query 可分页列举本人记忆，过滤无结果不等于没有记忆；不添加搜索框架或自动二次模型。该轮还发现测试夹具假定的 pytest 未安装，后续使用现有标准库 unittest 保留真实失败→修改→通过的判据；不得改保存文本迎合关键词或省略回答偏好采用断言。

实施核查：`af_effects` 保存请求 fingerprint 而非原载荷，单凭它无法重建修改/忘记的目标条目。把核对所需的原 call、工具、条目 ID、目标值及 effect 关联放入现有研究 turn body；不新增表或第二状态机。此记录在原生记忆写入前保存，用于原操作只读核对，不能成为绕过现有停止和未知命令守卫的通行条件。

沿现有 effect 与原操作观察边界核对记忆写入；写入后回执丢失只查询原 ID，不能重新调用 upsert 或换 ID。结果已被后续变更覆盖时保留待核，不重放旧值。核对不调用模型、不解除任意研究副作用守卫；若要解除原阻断，只能在原记忆操作已确认且原运行安全结束后沿现有会话规则显式继续。实现时先用 DB 成功/回执前退出这一窗口验证所需窄接线，不另建恢复框架。

当前 `task_held` 把研究 `blockReason` 本身计为 custody，因此不能等待 task 终态后才清该标记，否则互相等待。记忆观察仅在原 native 身份/结束状态已核、原记忆回执已确认且无其他未知 effect 时释放对应应用标记；不自行标 task 成功/终态。随后仍由既有执行观察器检查 native/process/workflow custody，`_safe` 确认任务真正结束后才开放显式下一轮。无原记忆核对依据的一般重试不采用此路径。

实施反例还确认：记忆 effect 正常 DONE 后、原生最终回复前退出，仍会因一般重试守卫阻断；不能只处理 UNKNOWN 回执窗口。对这类仅记忆原操作同样核原请求 fingerprint、条目证明与原生终态后允许显式下一轮；混合命令继续服从原守卫。另已复现同 call ID 改成 forget 时错配别的 UNKNOWN effect，观察必须核对原请求 fingerprint，不能仅按 effect key/条目不存在结算。

原生 MemoryTools 不原样注册，原因是上述实际 owner 缺口及无关 think/analyze 工具；不为修它们创建 DB 代理。也不启动 MemoryManager 二次推理来重复主模型决策。用户明确要求记忆时可直接执行，不添加每条人工确认；首片不自主摘录项目资料或共享材料。现有工具记录承担结果展示，自然语言承担修改/忘记入口。

### 2. 子助手复用 DelegationService，保持 child 自己的身份

主助手得到一个明确派发入口和原结果等待能力。派发沿已有 parent/root link、精确 application/材料/连接引用、task/run、预算及取消；Research 解析持久可信 parent link 得到根逻辑 session/turn/workspace，给 child 明确子目标和必要上下文，不整包复制主聊天。child 的模型/工具检查使用自己的 task/run，结果不能写入主轮次回复或摘要。普通用户输入不能伪造 parent 关联。

给现有通用创建接口传递当前 schema 所需 inputs；权限和资源仍从 parent 继承，不增加第二套凭据链。修改限于现有调用契约，core 不认识 Research 字段。Agno Team 有原生委派能力，但不会自动生成平台原票据/操作关联；当前改用 Team 比复用现有路径改动更广，本片不采用。

### 3. 原生等待先做可证伪的小验证

先以测试 child 验证 native external-execution 暂停和原 ControlCommand/requirement 回填。当前 `_model_boundary` 对 `attempt > 1 and effects` 阻断，必须仅允许已核对原等待身份的合法 continuation；一般重试和未知命令仍拒绝。不允许 child 冒充 parent、不用清空 effects 通过验收。

完整代码审查又复现：若父助手第一个工具就是派发，持久 delegation link 已建立，但父任务没有 af_effects；普通队列 attempt=2 不能仅因 effects 为空而重新进入模型。恢复守卫同时识别已有委派原操作，合法原 ControlCommand 续入仍沿原证明放行；复用现有 link，不另造 effect 或状态框架。

首样本一个 child + 主助手：保留 `maxChildren=1`、每用户两个活动任务、两个 worker。并行两用户各有 parent+child，证明等待真正释放 worker且原结果可返回；暂停不意味活动任务不计数。若已有原生协议不能满足该反例，停止子助手扩展并报告具体失败，先完成不依赖它的记忆片，不能先抬并发或写新调度器。

验证通过后串起真实任务：child 调查一处、主助手调查另一处→原会话收集→修改测试；再让 child 在明确文件分工下实际编辑/运行。第一样本只读是任务选择，不是全局工具禁令。现有锁是 run 级，不能宣称同文件并发编辑安全；先明确分工与单写者，发现真实冲突再补最小修复，不预造隔离工作树。

### 4. 将已验证探针接入实际个人助手

独立探针 `124e53ee` 已通过 5 项真实 PG 用例和完整累计非作者审查：原父 run 暂停/续入、两成员/两个 worker、同数据库服务生命周期重建、原任务树停止及一般未知结果守卫。停止曾被新 child 授权顺序误归为权限错误；已在原身份/绑定核对后先识别明确停止，再执行活跃授权，未改 CLI 通用错误分类。当前还没有 OS 进程崩溃、真实模型分工或产品 UI 通过证据。

下一实现片以记忆候选 `e023453` 为依赖基线，保留记忆冻结分支；将测试工具注册移入现有 Research 工具注册，复用原委派请求、预算和 external execution 等待。主模型得到简短分工/采用结果说明；现有事件显示子目标、原 child/run 与真实状态，不新增消息总线或执行引擎。新能力只用于新配置，旧 Plan 不静默换绑。

整合先复现一个具体边界：parent/child 共用逻辑 turn、各自 run，却可能使用相同 call ID；记忆原意图与观察须按原 run/call 区分，核对 child 自己的原 effect，不能覆盖主回复/摘要或把 child 当 parent。复用已有记忆与 delegation 记录，不建另一套状态表，也不通过禁止 child 使用全部记忆工具绕开问题。

验收先在现有解释器预检小仓库和测试，再让真实 Go 自主分头调查、采用结果并完成修复；另一个明确文件分工任务由 child 实际编辑/运行。独立 OS 探针验证原 parent 已持久 PAUSED、child 结果持久后退出真实服务 PID，同 PG 新 PID 续原 parent/run，重复观察无替代 child；child 操作 UNKNOWN 时不得重放。该项不阻塞源码实施，但阻塞完整验收与发布。桌面手机验证派发/等待/失败/停止及原任务入口，协议与实模、浏览器证据分别报告。

浏览器停止验收发现：正常执行中的命令在收到回执前也持有 UNKNOWN effect，新子助手卡片把这个 custody 标记当成显示状态，误标原生 running 为未知。复用既有生命周期事实的 displayStatus 区分运行/停止中与未确认结果；不改变 allStopped、unknown、原等待或副作用恢复门禁。

## Risks / Trade-offs

- 原生 API 名称不代表正确接线 → 实测 owner、原 ID、DB 失败、写后退出；不把文本审查当通过。
- 研究身份/重试守卫可能阻断合法 child/continuation → 先验证原身份、暂停、回填和重复观察；保留未知副作用负向用例。
- 模型可能不采用记忆或子结果 → 脚本用例只验协议，真实 Go 另验自主工具选择和最后任务结果。
- 私人记忆不等于全部持久知识 → 现有项目记录、证据出处、共享撤权与任务事实仍各自为准；忘记不擦除旧聊天。

## Migration Plan

不升级 Agno，不迁移或重写旧会话/模型绑定/历史任务，不新增旧版兼容引擎。每片只给新部署注册新工具；原 Plan 仍按原工具绑定运行，不偷改在途任务。旧会话采用新增能力的入口需明确显示其现有绑定限制，不能默默换配置。回退保留原生记忆数据和原任务记录，不永久删除真实数据。

原会话显式选择更新后的模型配置、正常网络获取依赖仍是独立待办；全站易用性和可部署版本继续原 roadmap，不在本片中悄悄扩大。

## References

- [Agno v3.1.0 PG memory CRUD](https://github.com/agno-agi/agno/blob/v3.1.0/libs/agno/agno/db/postgres/postgres.py#L2133)、[MemoryTools](https://github.com/agno-agi/agno/blob/v3.1.0/libs/agno/agno/tools/memory.py#L184)、[MemoryManager](https://github.com/agno-agi/agno/blob/v3.1.0/libs/agno/agno/memory/manager.py#L220)。安装源码已与固定 tag 核对，不用最新版宣传推断。
- [现有 research 守卫](https://github.com/Guanzhw/agent-factory/blob/dff7b96c7cb83bdaca4f85f5069cac6f04322306/applications/research/sessions.py#L372)、[原生等待接线示例](https://github.com/Guanzhw/agent-factory/blob/dff7b96c7cb83bdaca4f85f5069cac6f04322306/platform/agent_factory/ssh_operation_waits.py#L45)、[Agno 队列](https://github.com/agno-agi/agno/blob/v3.1.0/libs/agno/agno/os/job_queue.py)。目前仅源码证据，尚无本片运行通过结论。
