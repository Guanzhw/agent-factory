# 新应用开发指南

本指南是新应用从代码、素材到受治理任务的入口。底座使用 Agno 3.1.0、
PostgreSQL 和已安装的可信适配器。应用定义是不可变的配置与素材引用，不能安装代码、
扩大权限或保存凭据。普通应用复用注册执行器；需要多步骤、分支或人工审查时，注册
Agno 原生 `Workflow`，由 Agno 保存进度、暂停要求和续跑状态。

真实 ConvertD 的业务代码、后端和材料由用户在本地实现。本指南和仓库中的合成示例
证明的是接线方式，不能替代真实业务、模型、GPU 或目标机器验收。

## 公共契约与兼容边界

应用依赖已版本化的声明、精确引用和受治理请求，不依赖内部存储布局。
当前兼容证据覆盖下列边界；仓库没有独立稳定 Python SDK 的 SemVer 承诺。

| 接入面 | 当前公共契约 |
| --- | --- |
| 应用声明 | 缺省版本的冻结 v1，以及显式整数 `contractVersion: 2` 的 v2；字段见 [`application_schema.py`](../platform/agent_factory/application_schema.py) |
| 素材、应用和原生组件 | 发布的 `{id, version, sha256}`、精确 `nativeComponent` pin；新发布不重写原引用 |
| 组合、计划与任务 | 本指南中的 proposals、plans、instances 请求；保留原 `requestId` 与 payload，同 ID 改意图会冲突 |
| 可信能力注册 | 已审 `AdapterRegistration`、`NativeWorkflowRegistration` 和精确 revision/config pin；声明不能安装代码或扩大权限 |
| 外部异步操作 | [`WorkflowAdapter`](../platform/agent_factory/workflow_contracts.py) 的 `start/lookup/inspect/cancel`、原 operation ID 和停止证据 |
| 原生工作流投影 | `/api/factory/workflows/{task_id}` 的 schema 2；`decide/reconcile` 核对当前 snapshot `version` 摘要，不能将它当可排序版本号；`cancel` 仅提交 `commandId/action`，不携带 `version` |

可信工厂使用的 `BindingContext` 是本进程的接线上下文，其 `store`、内部 service、
数据库表、下划线方法和测试 helper 没有独立公开 SDK 的兼容保证。
下文示例展示当前仓库版本的接线；升级时应重新验证这些内部依赖。

| 应用声明 | v1 保留格式 | 新 v2 格式 |
| --- | --- | --- |
| 版本标记 | 不含 `contractVersion` | 显式整数 `2` |
| mode 选择 | 原 v1 默认规则 | 必须显式 `defaultMode` |
| 时间预算 | `budget.experimentSeconds` | `budget.operationSeconds` |
| mode 配置 | 原 `LegacyTaskConfig` | 有界 `configSchema` 与经校验的 `config` |
| plan 配置 | 原 `askScope/experimentDurationSeconds` | `sample/toolOrder/applicationConfig` |

既有 v1 定义、保存的计划和摘要保持原值。不要给 v1 添加 `contractVersion: 1`，
也不要原地改成 v2 或混合两套预算字段；字符串、布尔和未知版本被拒绝。
v2 不回退到 v1 的时间上限。执行仍会重检权限、素材状态和连接；格式兼容不保留已撤销的授权。
冻结 v1、严格版本和预算检查见
[`test_application_contract_v2.py`](../platform/tests/test_application_contract_v2.py)。

改变输入解释、预算、能力或 runtime 行为时，使用新的契约或实现 revision，发布新引用，
重新组合计划并完成所需审批；不要重算旧计划摘要或用旧审批静默扩大权限。
兼容的声明更新发布新应用/素材版本；破坏既有字段或请求语义的升级需先实现明确的新契约
并保留旧解析路径，不能仅给请求添加未支持的版本号。当前仅支持缺省 v1 和显式整数 `2`。
新增字段也需核对已有 strict schema，不能假设旧解析器会接受它。
应用契约、发布版本、adapter/component revision 与 Agno 依赖版本是不同的版本维度。
当前底座目标为 Agno 3.1.0；素材中的 compatibility 声明不代表已验证跨 Agno 版本、
任意 provider 或目标机器兼容。

v2 已有本机原生合成执行证据；当前通用 `remote_handoff` 对不支持的中立 v2 manifest
返回 `REMOTE_CONTRACT_UNSUPPORTED`。ORX 原生会话需按其自身协议验收，不能推断所有
远端 runtime 已支持 v2。真实研究、模型请求、外部后端及停止证据仍需分别验收。

## 选择最小路径

| 需求 | 开发内容 | 部署管理员接线 |
| --- | --- | --- |
| 已有能力的新组合 | 应用 mode、素材选择、输入声明与预算 | 审查并发布素材和应用，核对现有适配器及用户连接 |
| 一个新工具或模型 | 可信工厂函数、参数/结果契约、受控测试 | `Settings.runtime_adapters`、工具 policy 或模型 pricing、连接绑定 |
| 多步骤、分支、人工审查 | 原生 `Workflow` / `Step` / `Router`，稳定注册身份 | `Settings.native_workflows`，应用 mode 的精确 `nativeComponent` pin |
| 异步外部操作 | 原操作的 start/lookup/inspect/cancel 与明确停止证据 | `Settings.workflow_runtimes`，原生外部 wait 的工具及权限 |

不要为了增加一个应用修改全局队列、复制调度器或编写独立 DAG/resume 引擎。
`Loop`、嵌套 Workflow 和 Team 尚未开放到这一注册边界。

## 普通开发者：实现与交付

### 1. 声明输入和业务边界

为每个 mode 定义有界 `inputSchema`。它与执行器 `TaskConfig` 分开；用户提交
`inputValues`，组合过程固定原值及 schema，不注入默认值。支持闭合对象、有限长度
数组/字符串、有限数值、整数、布尔、null 和标量 enum；不支持 `$ref`、代码或网络加载。

以下是可直接导入的原生最小组件；函数只返回合成文本，没有外部副作用：

```python
from typing import Any, cast

from agno.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnError, StepInput, StepOutput
from agent_factory.input_schema import input_model
from agent_factory.native_workflows import NativeWorkflowRegistration

INPUT_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['topic'],
    'properties': {'topic': {'type': 'string', 'maxLength': 200}},
}
ApplicationInput = input_model(INPUT_SCHEMA)

async def summarize(step_input: StepInput) -> StepOutput:
    return StepOutput(content='Synthetic wiring example; no backend called.')

def registration(reviewed_implementation_sha256: str):
    component = Workflow(
        id='department-summary-v1', name='Department summary',
        input_schema=ApplicationInput,
        steps=[Step(
            name='summarize', step_id='summarize',
            executor=cast(Any, summarize), max_retries=0,
            skip_on_failure=False,
            human_review=HumanReview(on_error=OnError.fail),
        )], telemetry=False,
    )
    return NativeWorkflowRegistration(
        component, '1', ('summarize',), reviewed_implementation_sha256,
    )
```

`input_model` 生成实际 Pydantic 模型，负责严格类型与嵌套限制。若业务代码需要序列化
已验证模型，使用 `model_dump(by_alias=True, exclude_unset=True)`，保留字段别名并区分
省略和显式 null；不要用默认 dump 给不可变输入补值。应用声明必须与原生组件的输入
模型匹配。测试还应覆盖 `false` 不能当数字、额外字段、边界长度、输入篡改和跨应用复用。

上例只定义组件，不会启动服务。`implementation_sha256` 必须是管理员针对已审代码和
配置清单生成并保留的真实 64 位小写十六进制摘要，不能复制测试中的占位摘要。
Agno `to_dict()` 的函数名不是源码 pin。注册后不要替换 executor、selector、evaluator、
Agent 或 model；进程内身份检查不等同于代码沙箱。

### 2. 实现工具、模型和外部 runtime

可信工厂接受 [`BindingContext`](../platform/agent_factory/execution_bindings.py)，其中包含
当前 settings、store、plan、native run context、绑定 spec 和经检查的 connection。
它不能从用户输入任意选择凭据、主机或安装程序。

| 注册 kind | 工厂产物 | 开发者必须交付 |
| --- | --- | --- |
| `tool` | Agno 工具 | 固定工具名、最小能力、参数验证、当前权限与副作用契约 |
| `model` | Agno `Model` | 实际 provider/model 身份、请求/重试/流式 usage 契约和 pricing 接线 |
| `knowledge` | `KnowledgeContext` | 受控内容及 provenance，不能伪称真实来源 |
| `environment` | `EnvironmentLimits` | 底层实现实际执行的时间、输出、内存、PID、CPU 限额 |

素材中的 `runtimeBinding` 仅是 `{adapterId, revision, config}`。工具代码通过
`AdapterRegistration('tool', ..., tool_name=..., permissions=(... ,))` 安装，模型通过
`AdapterRegistration('model', ..., factory)` 安装。不要把导入路径或可执行代码放入素材。
环境限额声明也不会自动为任意业务程序提供容器隔离。

外部异步操作采用 `OperationCustody`，不要在函数重试中再次提交。实现与调用形状见
[`DurableOperations`、`build_workflow` 和 `settings`](../platform/tests/test_native_workflow_factory_postgres.py)：

- runtime 提供 `start(context, operation_id, inputs)`、`lookup(context, operation_id)`、
  `inspect(context, handle)`、`cancel(context, handle)` 四个 async 方法。
- 步骤调用 `await store.workflow.start(run_context, step_id, effect_slot, adapter_pin, inputs)`；
  adapter pin 是精确的 `adapterId/revision/configFingerprint`。
- 首次提交前保存原 intent；未知应答通过 `WorkflowAcknowledgementUnknown` 表达，
  保留原 operation ID，后续只查原操作。禁止把找不到应答解释为可以再次 start。
- `allStopped` 必须有该原操作的实际证据。原生运行 completed/cancelled、超时或进程消失
  都不能独立证明外部操作停止。未证实的 custody、资源及磁盘占用继续保留。

### 3. 使用原生分支与 HITL

每个注册 Step 使用唯一语义 ASCII `step_id` 与唯一名称；函数步骤 `max_retries=0`。
**每个 Step** 都配置 `HumanReview(on_error=OnError.fail)` 和 `skip_on_failure=False`，
避免 Agno 默认错误处理将失败当作后续可执行状态。需要人工确认时，可增加
`requires_confirmation=True` 和 `on_reject=OnReject.cancel`。

注册语义 ID 用来审查组件并绑定工具。执行时 Agno 可能生成并保存原生 Step UUID；
恢复时使用保存的原生身份，不能把 runtime UUID 改写为语义 ID或自行构造替代步骤。

模型决定分支时，使用固定身份、静态指令、无工具的 Agent 输出有界 enum，再由可信
原生 Router selector 验证并选择预注册分支。不要解释模型生成的代码、步骤或权限。
Agent hooks、fallback model、额外 parser/model 等执行路径不被此边界隐式允许。

外部并行操作用原生 `Parallel` 提交，随后在 parallel **外部**放置只带
`factory_wait_operations` 工具的 wait Agent。Parallel join 只表示提交函数结束。
原生 external execution 暂停原 run；控制层通过 `RunRequirement.set_external_execution_result`
填入已验证的原操作结果，再继续同一个原生 run。不要直接修改 requirements JSON，
也不要自己实现“从下一 stage 重新运行”。

前端从 `/api/factory/workflows/{task_id}` 读取 schema 2 原生投影；命令为 `decide`、
`reconcile`、`cancel`，不是独立 `resume`。确认/输入针对原 requirement，reconcile 针对原
operation。命令 ID 和原 payload 持久保留；未知应答先读取原 receipt。原生命令完成与
外部实际停止分开展示。详见 [工作流治理说明](GOVERNED_WORKFLOW_AGENTS.md)。

### 4. 给管理员提供可审查包

交付已审代码/config 清单及摘要、输入 schema、六类素材草案、工具能力和最小预算、
外部操作停止/恢复契约、合成测试及尚未验证的真实依赖。应用不要依赖 demo persona、
固定 fixture 密码或管理员身份；凭据不属于交付素材。

完整的可运行合成接线参考是
[`test_native_workflow_factory_postgres.py`](../platform/tests/test_native_workflow_factory_postgres.py)：
`build_workflow` 定义组件，`settings` 安装工厂和 policy，`publish` 发布素材及应用，
`serve` 安装应用并绑定其状态；测试通过实际 Factory API 创建任务，验证原 run 暂停/恢复、
未知应答 lookup 与取消 custody。SQLite 在这个例子中只是合成外部后端，不是生产 ConvertD。

[`test_native_workflow_reuse_postgres.py`](../platform/tests/test_native_workflow_reuse_postgres.py)
补充原生 enum Agent→Router、Condition、Parallel 和持久化 HITL 的机制示例；直接的 Agno
机制测试不等于通过 Factory 注册和发布边界。新应用以完整 Factory 接线为验收入口。

## 部署管理员：注册、发布和准入

### 1. 安装可信能力

在 `create_app(Settings(...))` 前安装所需的同进程注册，HTTP 不提供安装代码接口：

- `runtime_adapters`：上述模型、工具、知识和环境工厂。
- `tool_policies`：每个新增工具对应四字段
  `ToolPolicyRegistration(adapter_id, adapter_revision, revision, read_only)`。
  工具名和唯一 capability 从精确 AdapterRegistration 推导，不重复手写第二份身份。
  `read_only` 要匹配实际行为；不能靠声明消除外部副作用。
- `native_workflows`：上述四参数 NativeWorkflowRegistration；函数步骤名称必须精确列入
  `tool_names`，并具有被批准的对应工具素材/policy。
- `workflow_runtimes`：若有外部操作，以 `(adapter_id, revision, configFingerprint)` 为 key
  安装原 runtime 对象。这个配置与素材 `runtime_adapters` 的环境工厂不同。
- `trusted_connections`：只安装用户/任务范围明确的可信连接；素材及请求只引用 opaque ref。
- `usage_pricing`：模型准确的 provider/model、版本、计价与每次请求限额。受控本地模型的
  零价测试声明不能套用真实 provider。未知 usage、重试或费用边界不能降级成免费成功。

查看 [`Settings`](../platform/agent_factory/config.py)、
[适配器接线](MATERIAL_ASSEMBLY.md)、[token ledger](TOKEN_LEDGER.md) 和
[工具 policy 实现](../platform/agent_factory/tool_policy_registry.py)。默认 CLI 只配置显式 demo
能力；新应用不能假设实际服务已经安装。启用新的工具治理契约时使用新的 plan/material
policy revision，不要沿用旧审批哈希静默扩大能力。

### 2. 发布素材与应用

按 [素材治理](MATERIAL_GOVERNANCE.md) 创建六类素材：skill、tool、prompt、knowledge、
model、environment。每项包含来源/许可证、兼容版本、依赖、权限及需要时的 runtimeBinding。
通过 `MaterialGovernance.create_draft → request_publication → decide_publication`，
由不同的当前管理员审查。保留返回的 `{id, version, sha256}` 精确引用。

新应用使用以下 v2 最小结构；既有 v1 定义按上面的保留格式继续支持。
`approved_refs` 是完成审查后的实际六类引用，
`native_pin` 来自 `state['store'].native_workflows.pin('department-summary-v1')`：

```python
def application_definition(approved_refs, native_pin, input_schema):
    return {
        'contractVersion': 2,
        'id': 'department-summary', 'name': 'Department summary',
        'description': 'Reviewed bounded application', 'defaultMode': 'summary',
        'modes': {'summary': {
            'materialRefs': approved_refs,
            'nativeComponent': native_pin,
            'inputSchema': input_schema,
            'toolOrder': ['summarize'],
            'capabilities': ['summary:execute'],
            'configSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
            'config': {}, 'connectionRequirements': [],
            'budget': {'toolCalls': 4, 'maxDepth': 1, 'maxChildren': 1,
                       'operationSeconds': 8, 'outputBytes': 65536},
        }},
    }
```

这里的 `summary:execute` 必须与工具注册、素材权限及当前用户权限一致，不能仅填写字符串
就获得授权。toolOrder 和素材需要包括该 mode 实际使用的工具；如果加入 wait Agent，也
要加入 `factory_wait_operations` 的素材和 policy。普通注册执行器应用省略 nativeComponent；
不是所有应用都需要 Workflow。

v2 `config` 是应用声明数据，用户本轮值由 `inputSchema/inputValues` 传入。
`configSchema` 不能声明 permissions、credentials、budget、executionBindings 等授权字段。
可用 `application_schema.definition_model(body).model_validate(body)` 校验声明格式；这不替代素材发布、
组件身份、权限、连接和生产准入检查，也不会执行该应用。

再通过 `ApplicationService.create_draft → request_publication → decide_publication` 发布应用。
完整具体 payload 和不同审查者接线见上述 fixture 的 `publish`，不要把测试账户用于生产。
素材/应用发布审批与某个用户任务的 plan 审批是独立步骤。

### 3. 让用户组合并运行

用户在组合界面选择应用和 mode、填写输入、绑定允许的连接。API 对应
`POST /api/factory/compositions/proposals`，字段包含 `goal/application/mode/inputValues/requestId`，
以及可选的精确 applicationRef、允许的 materialChoices 和 connectionRefs。查看并修订 proposal，
接受后获得不可变 plan；缺少适配器、连接、审批或权限时处理具体 preflight 阻碍。

需要直接固定应用时，`POST /api/factory/plans` 使用 `topic/application/mode/inputValues/requestId`；
随后 `POST /api/factory/instances` 使用 `planId/requestId`。不要把 proposal 的 `goal` 字段照搬
到 plans 请求。生产准入仍受配置的 plan 审批策略约束；同一 requestId 改变意图会冲突。

权限、素材发布状态、精确连接 pin 与原生身份在执行时重新检查。工具和模型调用使用
共享预算，子任务不能另开预算；外部 wait 完成也按原 native tool call ID 计账。扩大预算或
更换材料需新计划和必要审批，不能修改进行中的不可变 plan。

部署生产实例需独立数据库、受管身份与角色、私密服务配置及实际 runtime 资源边界。
默认 demo 登录仅适合 loopback。远端执行还需单独的受信映射和当前源授权，不能把应用
输入中的地址当受信执行目标。参见 [部署决策](PRODUCTION_DECISIONS.md)、
[计划审批](PLAN_POLICY.md) 和 [远端绑定](REMOTE_BINDINGS.md)。

## 可执行检查与验收记录

在仓库根目录准备已锁定依赖后，先运行不需要数据库的定向检查：

```bash
uv sync --frozen
npm ci --ignore-scripts
uv run python -m unittest discover -s platform/tests -p 'test_application_inputs.py' -v
uv run python -m unittest discover -s platform/tests -p 'test_application_contract_v2.py' -v
uv run python -m unittest discover -s platform/tests -p 'test_tool_policy_registry.py' -v
uv run python -m unittest discover -s platform/tests -p 'test_native_workflows.py' -v
uv run ruff check platform scripts
uv run pyright
npm run check
npm audit
```

真实队列/恢复测试使用管理员提供的**可销毁测试服务器**，设置
`FACTORY_TEST_DATABASE_URL`，身份需有 CREATEDB；fixture 创建并清理自己随机命名的数据库。
不要使用生产 URL。未设置该变量时 PG 测试跳过，skip 不算验收。

```bash
uv run python -m unittest discover -s platform/tests -p 'test_native_workflow_factory_postgres.py' -v
uv run python -m unittest discover -s platform/tests -p 'test_native_workflow_reuse_postgres.py' -v
```

这些重型测试串行运行。完整仓库检查见 [README](../README.md#checks)，结果必须记录精确
commit、执行环境、运行数、失败和 skip。应覆盖输入拒绝、权限撤销、原 run 新进程恢复、
重复命令、未知提交不重放、取消未知保留 custody、停止证据后释放，以及原生运行状态与
业务结果的区分。浏览器 mock、合成模型和合成后端分别标注，不冒充真实 provider 或业务验收。

真实 ConvertD 验收还需要用户本地的已审后端、材料、结果评价方式和停止证据；应用开发
与发布流程已接线，不代表这些尚未提供的业务依赖已经验证。
