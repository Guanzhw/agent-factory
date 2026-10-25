# 新应用开发指南

本指南是新应用从代码、素材到受治理任务的入口。底座使用 Agno 3.1.0、
PostgreSQL 和已安装的可信适配器。应用定义是不可变的配置与素材引用，不能安装代码、
扩大权限或保存凭据。普通应用复用注册执行器；需要多步骤、分支或人工审查时，注册
Agno 原生 `Workflow`，由 Agno 保存进度、暂停要求和续跑状态。

真实 ConvertD 的业务代码、后端和材料由用户在本地实现。本指南和仓库中的合成示例
证明的是接线方式，不能替代真实业务、模型、GPU 或目标机器验收。

## 源码归属与静态装配

默认发行包只安装底座与部署入口，应用注册列表为空。旧 Research 源码、页面和种子已移除。
需要组合现有能力的应用可由成员显式发布材料和声明；新增可信代码则由部署方显式注册，
不向底座增加应用业务分支，也不通过 HTTP 安装代码。

| 目录或入口 | 职责 |
| --- | --- |
| `platform/agent_factory/` | 公共身份、凭据、资源、素材/应用契约、任务准入、原生执行、事件与产物 |
| `deployment/agent_factory_server/main.py` | 底座启动与显式应用注册；默认无应用 |
| `web/composition.tsx` | 公共壳与显式页面装配；默认应用目录为空 |
| `platform/tests/core_native_fixture.py` | 测试显式安装的合成应用与适配器，不是启动种子 |

`agent_factory.main.create_app` 与 `agent_factory_server.main.create_app` 均不安装旧研究应用。
应用函数与客户端优先使用下文 Application Interface；部署工厂内部接线上下文不是稳定公共 SDK。
新空库可使用登录、资源和成员发布入口。移除源码不删除旧记录、凭据、vault key、产物或备份；
旧应用任务需要原代码才能继续，永久删除旧数据仍需准确清单与单独确认。

根 `pyproject.toml` 生成底座加部署入口的 wheel，保留 `agent-factory` 命令；
`platform/pyproject.toml` 生成仅包含 `agent_factory` 的独立底座：

```bash
uv build platform --out-dir /tmp/agent-factory-core-dist
uv build --out-dir /tmp/agent-factory-deployment-dist
```

两种 distribution 不应叠装到同一环境。仓库根运行 `uv sync --frozen` 后，
可用 `uv run python -m agent_factory_server` 启动；数据库与鉴权配置要求不变。
未安装项目而直接运行源码时：

```bash
# POSIX shells; PowerShell/Windows uses ';' between these paths.
export PYTHONPATH="$PWD/platform:$PWD/deployment"
python -m agent_factory_server
```

## 部门成员的默认流程

普通启动入口的 `Settings.from_env()` 默认使用
`temporary_policy=member-self-service`、`policy_revision=department-member-v1`，以及
`material_review_mode=member-self-service`、`material_policy_revision=material-department-v1`。
成员自行创建、配置和发布材料/应用的新版本，并直接提交新任务；普通任务不经过 plan 审批。
作者直接修订、撤回和归档自己的公开版本；其他成员复制后获得自己拥有的新资源 ID。
账号管理员只管理账号，不能覆盖其他作者的资源或私人历史。

危险工具操作、精确项目创建意图和原生 Workflow 的确认/输入仍走各自原生契约。
成员发布内容引用已安装能力或自己接入的 CLI/MCP 工具声明。Python 工厂和原生 Workflow
由部署入口注册；成员工具配置通过底座资源接口持久化，并进入同一个执行绑定注册表。

历史计划和 review 按原归属可读，旧 review 写接口返回 410。缺少显式运行绑定的旧计划
执行时返回 `BINDING_MANIFEST_REQUIRED`，需重新组合新计划；原计划与请求身份保留。
未知应答继续查询原请求/操作，不能靠重建请求绕过原操作恢复。

`member-self-service` 是唯一支持的新运行模式；`bounded-synthetic`、`admin-review`、
`separate-admin` 等旧计划或发布模式作为当前配置会明确报错，demo 也不恢复旧审批路径。
数据库中的旧审批模式、记录、摘要和版本保留，启动使用当前传入配置。
流程及迁移边界见 [成员发布](MEMBER_PUBLICATION.md) 与
[部门协作说明](department-minimal-integration.md)。

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

应用层的小型公共接口、职责边界和兼容政策见 [Application interface v1](APPLICATION_INTERFACE.md)。
原生函数可声明 `application_context`，通过输入、资源引用、事件和产物接口编写应用；
生命周期客户端隐藏内部 plan，复用现有准入与回执，不建立新的执行或恢复引擎。

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
v2 不回退到 v1 的时间上限。执行仍会检查当前成员、素材状态和连接；格式兼容保留原内容身份。
冻结 v1、严格版本和预算检查见
[`test_application_contract_v2.py`](../platform/tests/test_application_contract_v2.py)。

改变输入解释、预算、能力或 runtime 行为时，使用新的契约或实现 revision，发布新引用，
重新组合计划并重新检查当前成员、资源状态与所需原生确认；保留旧计划的摘要和历史审批。
兼容的声明更新发布新应用/素材版本；破坏既有字段或请求语义的升级需先实现明确的新契约
并保留旧解析路径，不能仅给请求添加未支持的版本号。当前仅支持缺省 v1 和显式整数 `2`。
新增字段也需核对已有 strict schema，不能假设旧解析器会接受它。
应用契约、发布版本、adapter/component revision 与 Agno 依赖版本是不同的版本维度。
当前底座目标为 Agno 3.1.0；素材中的 compatibility 声明不代表已验证跨 Agno 版本、
任意 provider 或目标机器兼容。

v2 支持显式启用的根 native agent 远程 handoff。`HandoffTarget` 和接收端 `TrustedOrigin`
均须设置 `supported_application_contracts=(1, 2)`；接收端另外配置完整 `v2_budget`
（toolCalls、maxDepth、maxChildren、operationSeconds、outputBytes）。默认仅 v1，不自动降级。
目标列表的 supportedApplicationContracts 是静态声明，connectivityVerified 不由声明推断。
接收端须已有与原 applicationRef 精确匹配的已发布应用版本及实际运行绑定。

v2 wire 为 `{wireVersion: 2, plan, applicationDefinition, sha256}`；sha256 仍是 plan 摘要，
完整应用定义由 plan.applicationRef 的版本摘要间接绑定。输入/schema/config/材料与绑定逐项核对，
operationSeconds 不改名为 experimentSeconds。旧 v1 manifest、默认配置指纹及响应字段保留。
workflow、scientific、delegation 与嵌套 remote placement 未启用，明确拒绝。
本地双进程/独立PG的确定性 checksum 已验证准确配置、预算、产物和丢回执重启/取消原身份；
这不是任意远端 runtime 或真实供应商兼容证明。ORX、真实科研与外部后端仍需分别验收。

## 选择最小路径

| 需求 | 开发内容 | 注册或发布路径 |
| --- | --- | --- |
| 已有能力的新组合 | 应用 mode、素材选择、输入声明与预算 | 成员直接发布素材和应用，核对现有适配器及用户连接 |
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

上例只定义组件，不会启动服务。`implementation_sha256` 必须是部署方针对已审代码和
配置清单生成并保留的真实 64 位小写十六进制摘要，不能复制测试中的占位摘要。
Agno `to_dict()` 的函数名不是源码 pin。注册后不要替换 executor、selector、evaluator、
Agent 或 model；进程内身份检查不等同于代码沙箱。

### 2. 实现工具、模型和外部 runtime

可信工厂接受 [`BindingContext`](../platform/agent_factory/execution_bindings.py)，其中包含
当前 settings、store、plan、native run context、绑定 spec 和经检查的 connection。
它不能从用户输入任意选择凭据、主机或安装程序。

| 注册 kind | 工厂产物 | 开发者必须交付 |
| --- | --- | --- |
| `tool` | Agno 工具 | 精确 adapter/修订的名称与能力、参数验证、当前资源状态与副作用契约 |
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

### 4. 提供可检查的部署与发布包

交付已审代码/config 清单及摘要、输入 schema、六类素材草案、工具能力和最小预算、
外部操作停止/恢复契约、合成测试及尚未验证的真实依赖。应用不要依赖 demo persona、
固定 fixture 密码或管理员身份；凭据不属于交付素材。

完整的可运行合成接线参考是
[`test_native_workflow_factory_postgres.py`](../platform/tests/test_native_workflow_factory_postgres.py)：
`build_workflow` 定义组件，`settings` 安装工厂，`publish` 由作者直接发布素材及应用，
`serve` 安装应用并绑定其状态；测试通过实际 Factory API 创建任务，验证原 run 暂停/恢复、
未知应答 lookup 与取消 custody。Workflow 自身的确认/输入保持原生契约。
SQLite 在这个例子中只是合成外部后端，不是生产 ConvertD。

[`test_native_workflow_reuse_postgres.py`](../platform/tests/test_native_workflow_reuse_postgres.py)
补充原生 enum Agent→Router、Condition、Parallel 和持久化 HITL 的机制示例；直接的 Agno
机制测试不等于通过 Factory 注册和发布边界。新应用以完整 Factory 接线为验收入口。

## 部署接线与成员发布

### 1. 安装可信能力

部署方在 `create_app(settings)` 前安装所需的同进程注册；普通配置从 `Settings.from_env()`
读取，HTTP 不提供安装代码接口：

- `runtime_adapters`：上述模型、工具、知识和环境工厂。
- `native_workflows`：上述四参数 NativeWorkflowRegistration；函数步骤名称必须精确列入
  `tool_names`，并具有已发布的对应工具素材与精确适配器声明。
- `workflow_runtimes`：若有外部操作，以 `(adapter_id, revision, configFingerprint)` 为 key
  安装原 runtime 对象。这个配置与素材 `runtime_adapters` 的环境工厂不同。
- `trusted_connections`：只安装用户/任务范围明确的可信连接；素材及请求只引用 opaque ref。
- `usage_pricing`：模型准确的 provider/model、版本、计价与每次请求限额。受控本地模型的
  零价测试声明不能套用真实 provider。未知 usage、重试或费用边界不能降级成免费成功。

查看 [`Settings`](../platform/agent_factory/config.py)、
[适配器接线](MATERIAL_ASSEMBLY.md)、[token ledger](TOKEN_LEDGER.md) 和
[执行绑定实现](../platform/agent_factory/execution_bindings.py)。独立底座提供通用资源接入；
研究部署另外安装自己的显式 demo 工厂。成员 CLI/MCP 工具不需要额外工具许可登记或审批
policy revision；发布核对所选 adapter ID、revision、工具名和声明能力，实际调用还检查资源状态。

### 2. 发布素材与应用

按 [素材治理](MATERIAL_GOVERNANCE.md) 创建六类素材：skill、tool、prompt、knowledge、
model、environment。每项包含来源/许可证、兼容版本、依赖、权限及需要时的 runtimeBinding。
成员通过 `MaterialGovernance.create_draft → publish` 直接发布自己创建的版本；调用
`publish(actor, material_id, version, request_id)` 时保留原 request ID 和意图。
对应 HTTP 为 `POST /api/factory/material-governance/versions/{id}/{version}/publish`，
请求体为 `{requestId}`，并携带 `X-Factory-Expected-Owner` 校验头。
保留返回的 `{id, version, sha256}` 精确引用。
作者修改自己的公开定义会生成新版本，撤回和归档也由作者直接操作。其他成员复制时
省略原 ID，建立自己的版本链；原版本、任务和摘要保持不变。

新应用使用以下 v2 最小结构；既有 v1 定义按上面的保留格式继续支持。
`published_refs` 是已发布的实际六类引用，
`native_pin` 来自 `state['store'].native_workflows.pin('department-summary-v1')`：

```python
def application_definition(published_refs, native_pin, input_schema):
    return {
        'contractVersion': 2,
        'id': 'department-summary', 'name': 'Department summary',
        'description': 'Published bounded application', 'defaultMode': 'summary',
        'modes': {'summary': {
            'materialRefs': published_refs,
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

这里的 `summary:execute` 必须与所选工具的实际能力声明、素材权限及 mode 范围一致。
`toolOrder` 和素材需要包括该 mode 实际使用的工具；如果加入 wait Agent，也要加入
`factory_wait_operations` 的素材与运行绑定。普通注册执行器应用省略 nativeComponent；
不是所有应用都需要 Workflow。

v2 `config` 是应用声明数据，用户本轮值由 `inputSchema/inputValues` 传入。
`configSchema` 不能声明 permissions、credentials、budget、executionBindings 等授权字段。
可用 `application_schema.definition_model(body).model_validate(body)` 校验声明格式；这不替代素材发布、
组件身份、资源归属、连接和生产准入检查，也不会执行该应用。

再通过 `ApplicationService.create_draft → publish` 发布应用，调用
`publish(actor, application_id, version, request_id)`；对应 HTTP 为
`POST /api/factory/applications/{id}/versions/{version}/publish`，请求体同样为 `{requestId}`，
并携带 `X-Factory-Expected-Owner` 校验头。成员自助发布示例见
[`test_department_publication.py`](../platform/tests/test_department_publication.py)。
`request_publication/decide_publication` 已退役并返回 410；原生 Workflow fixture 也使用
作者直接发布。历史 review 只按原作者范围读取，测试账号不用于生产。

### 3. 让用户组合并运行

用户在组合界面选择应用和 mode、填写输入、绑定允许的连接。API 对应
`POST /api/factory/compositions/proposals`，字段包含 `goal/application/mode/inputValues/requestId`，
以及可选的精确 applicationRef、允许的 materialChoices 和 connectionRefs。查看并修订 proposal，
接受后获得不可变 plan；适配器或连接缺失、资源不可用时处理具体 preflight 阻碍。

需要直接固定应用时，`POST /api/factory/plans` 使用 `topic/application/mode/inputValues/requestId`；
随后 `POST /api/factory/instances` 使用 `planId/requestId`。不要把 proposal 的 `goal` 字段照搬
到 plans 请求。普通成员新计划使用 `member-self-service` 直接准入，不需要另建审批请求；
执行前仍检查当前成员身份、资源可用性、精确绑定及预算。同一 requestId 改变意图会冲突。

当前成员、素材发布状态、共享与资源状态、精确连接 pin 及原生身份在实际调用时重新检查。工具和模型调用使用
共享预算，子任务不能另开预算；外部 wait 完成也按原 native tool call ID 计账。扩大预算或
更换材料需显式创建新计划，并完成该操作要求的原生确认，不能修改进行中的不可变 plan。

部署生产实例需独立数据库、受管成员身份、账号管理员标记、私密服务配置及实际 runtime 资源边界。
默认 demo 登录仅适合 loopback。远端执行还需单独的受信映射和当前源授权，不能把应用
输入中的地址当受信执行目标。参见 [部署决策](PRODUCTION_DECISIONS.md)、
[部门协作与历史计划迁移](department-minimal-integration.md) 和 [远端绑定](REMOTE_BINDINGS.md)。

## 可执行检查与验收记录

### 使用本人的 CLI / MCP 工具连接

成员可以在工具连接页面接入 CLI 命令或 MCP 服务，保存命令/参数/工作目录或 MCP 地址、
当前工具名称与输入 schema。协议无需认证时可以省略凭据；需要认证时，凭据由资源所有者
托管到 vault。配置持久化后进入原生绑定注册表，服务重启或其他工作进程可按精确 ID 加载。
部署提供的 `Settings.personal_tool_adapters` 仍可复用，同样不需要第二套工具许可登记。
工具描述固定输入 schema、capabilities、单一 permission 和实际读写语义；应用只引用声明。

例如，已安装的 `department.lookup` 适配器提供 `lookup_record`，需要
`records:read` 能力及权限，则工具材料的关键字段为：

```json
{
  "kind": "tool",
  "content": "lookup_record",
  "permissions": ["records:read"],
  "runtimeBinding": {
    "adapterId": "department.lookup",
    "revision": "1",
    "config": {"connectionName": "records"}
  }
}
```

这是材料内容片段；创建草稿时补齐名称、来源和许可证，版本与摘要由服务端生成。应用 mode
使用该材料引用，并声明：

```json
{
  "connectionRequirements": [
    {"name": "records", "kind": "tool", "requiredCapabilities": ["records:read"], "required": true}
  ]
}
```

成员在工具连接页面配置并绑定个人或团队工具，在材料编辑器选择“已接入工具”加载当前
声明；页面填写精确运行绑定并允许指定应用中的连接名称。装配应用时选择该名称对应的
个人或团队连接，调用者和凭据所有者分别检查。命令、MCP 地址与秘密由资源连接保存，
应用和材料只固定 adapter/connection 引用。配置成功与外部实际调用的验收分别记录。
详见[成员工具](MEMBER_TOOLS.md)、[成员发布](MEMBER_PUBLICATION.md)及
[个人工具生命周期](PERSONAL_TOOL_CONNECTION_LIFECYCLE.md)。

在仓库根目录准备已锁定依赖后，先运行不需要数据库的定向检查：

```bash
uv sync --frozen
npm ci --ignore-scripts
# Explicit synthetic fixtures remain in the platform test tree.
export PYTHONPATH="$PWD/platform:$PWD/deployment:$PWD/platform/tests"
uv run python -m unittest discover -s platform/tests -p 'test_application_inputs.py' -v
uv run python -m unittest discover -s platform/tests -p 'test_application_contract_v2.py' -v
uv run python -m unittest discover -s platform/tests -p 'test_tool_policy_registry.py' -v
uv run python -m unittest discover -s platform/tests -p 'test_native_workflows.py' -v
uv run ruff check platform deployment scripts
uv run pyright
npm run check
npm audit
```

完整 Python 回归发现 `platform/tests`，通用执行测试显式安装合成应用。
独立 wheel 生命周期与 import 边界仍需单独检查；测试收集成功不等于执行通过。

```bash
uv run python scripts/check_python.py
# 使用可销毁 PostgreSQL 后执行独立底座生命周期：
uv run python scripts/check_core_install.py
```

`npm run check:python` 执行 Python lint/type 检查及完整 discovery；
`npm run check` 检查公共前端并构建静态装配页面。浏览器 fixtures 位于
`platform/tests/browser/`，合成浏览器、真实数据库及外部身份/模型验收分别记录。
当前 core-only revision 的通过情况以其实际检查结果为准，旧研究验收不能替代。

真实队列/恢复测试使用管理员提供的**可销毁测试服务器**，设置
`FACTORY_TEST_DATABASE_URL`，身份需有 CREATEDB；fixture 创建并清理自己随机命名的数据库。
不要使用生产 URL。未设置该变量时 PG 测试跳过，skip 不算验收。

```bash
uv run python -m unittest discover -s platform/tests -p 'test_native_workflow_factory_postgres.py' -v
uv run python -m unittest discover -s platform/tests -p 'test_native_workflow_reuse_postgres.py' -v
```

这些重型测试串行运行。完整仓库检查见 [README](../README.md#checks)，结果必须记录精确
commit、执行环境、运行数、失败和 skip。应覆盖输入拒绝、账号禁用与资源撤回、原 run 新进程恢复、
重复命令、未知提交不重放、取消未知保留 custody、停止证据后释放，以及原生运行状态与
业务结果的区分。浏览器 mock、合成模型和合成后端分别标注，不冒充真实 provider 或业务验收。

真实 ConvertD 验收还需要用户本地的已审后端、材料、结果评价方式和停止证据；应用开发
与发布流程已接线，不代表这些尚未提供的业务依赖已经验证。
