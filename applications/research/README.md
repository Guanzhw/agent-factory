# 可选研究应用：项目约定接口

P4项目约定现已接入P5首轮后端：明确确认执行配置后，HTTP start可准入一个真实native root。自主后继轮次尚未接入；execution.available如实表示当前确认状态和配置是否允许申请首轮准入，false带具体reason，true的reason为null。资源当前授权仍需准入预检。现有UI没有start按钮，本轮不改前端，研究UI继续等待独立设计确认。应用使用core认证，项目只供owner读取；后续团队记录通过限定共享内容接口发布，不把整个项目变为公开。

部署composition root显式构造 `ApplicationAssembly(name='research', install=research.public.install)`，并把 `applications` 加入Python import roots；应用自身不import部署模块。未安装时core不创建research表或路由。安装不创建后台任务/线程，不取得DB所有权，关闭仍归core。

## HTTP

前缀 `/api/factory/research`。mutation包含8–80字符requestId，重投返回原命令收据，同键异内容冲突。所有接口使用当前认证owner，不接受owner字段。

- GET `/projects?after=&limit=20`：`{items,nextCursor}`，items为项目摘要（无goals），上限100。
- POST `/projects`：`{requestId,title,assistantId?}`，title最多120字符，assistantId只能关联自己的core端点；返回详情。
- GET `/projects/{id}`：详情。
- POST `/projects/{id}/goals`：`{requestId,expectedVersion,agreement}`，追加目标版本并回到draft。
- POST `/projects/{id}/confirm`：`{requestId,expectedVersion}`，确认当前约定并标ready；没有执行含义。
- POST `/projects/{id}/end`：`{requestId,expectedVersion,outcome,reason}`，outcome为not_met或cancelled；记录领域结束并取消已建立的项目scope以阻断新入口；不声称在途操作已停止，`resourceCleanup=not_observed`。ended不能再修订，继续研究建新项目。

详情字段：`id,ownerId,title,assistantId,state,currentGoalVersion,goals,ending,createdAt,execution`。state为draft/ready/ended。新项目version0。goals按版本升序：`{version,agreement,createdAt,confirmedAt}`。agreement字段 `objective,evaluation,stopConditions` 为1–4000字符；`resourceRefs`为slot到已有资源ref，最多30项，仅保存引用、不验证或授予执行权限；`budget`为下例。执行准入将由P5按当前资源权限再次检查，P4不创建预算scope或预留资源。

```json
{"objective":"测试目标","evaluation":"可核对评价标准","stopConditions":"达标或预算用尽停止","resourceRefs":{},"budget":{"rounds":3,"toolCalls":12,"tokenLimit":null,"amountMicros":null,"currency":null}}
```

budget沿core scope语义：rounds/toolCalls为正整数；tokenLimit为空时amountMicros/currency同时为空（不可宣称金额硬上限）；否则tokenLimit/amountMicros非负且currency为USD/EUR/CNY。目标历史agreement不可覆盖，confirmedAt是单次确认元数据。修改、确认、结束都检查expectedVersion；409 `RESEARCH_GOAL_VERSION_CONFLICT`要求读取最新状态，不能无条件重试写入。

错误使用现有HTTP异常封装，code为`RESEARCH_PROJECT_NOT_FOUND`、`RESEARCH_AGREEMENT_REQUIRED`、`RESEARCH_GOAL_VERSION_CONFLICT`或`RESEARCH_PROJECT_ENDED`。权限/幂等异常沿core契约。

## 显式运行

安装本仓库发行包后，用`agent-factory-research`启动包含研究应用的组合；默认`agent-factory`仍只启动底座。源码开发需`PYTHONPATH=applications:platform:deployment`。前端`npm run build:research`构建研究入口，`npm run build`构建无应用入口；运行时只绑定配置的地址，不由构建命令公开服务。

## P5 首轮后端契约

agreement新增可选execution；缺失时可保存约定，但start返回409。

```json
{"applicationRef":{"id":"published-application","version":1,"sha256":"<真实发布版本的64位摘要>"},"mode":"selected-mode","materialChoices":{},"connectionRefs":{},"deadline":1793000000,"perRoundCaps":{"rounds":1,"toolCalls":4,"tokenLimit":null,"amountMicros":null,"currency":null}}
```

示例时间仅说明epoch单位；实际截止时间必须用户明确配置且正式start时未过期。materialChoices是slot到精确材料pin，connectionRefs是slot到已有连接ref；不提交秘密。首root接收完整「研究目标/评价标准/停止条件」文本，组合不超过2000字符，不截断；有inputSchema的模式须接受字符串goal且没有其他必填字段，完整文本同时写inputValues.goal并按schema验证。不兼容模式拒绝。每轮caps不得超过项目budget，计费类型/币种必须一致。model/provider/tool权限仍由core实际计划与原任务guard校验。

- POST `/projects/{id}/start`：`{requestId,expectedVersion}`。202含projectId/goalVersion/experimentId/attemptId/scopeId/allocationId与execution原准入回执；202不是执行成功。准备事务按admission→应用namespace→usage锁顺序冻结scope、allocation、原factory request绑定和领域意图，提交后才进入core准入。即使从公开core启动接口重投原request且不带allocation，core仍强制原预算；已有task回执必须与allocation.taskId一致。
- GET `/projects/{id}/experiments`：返回items，每项含id/projectId/goalVersion/hypothesis/conditions/createdAt，以及attempt的id/allocationId/requestId/execution。execution来自ApplicationRuns.request，表达准入事实，不是科研结论或最终task状态；尚无core回执为null。实际task状态与产物按原task查询底座。

本切片一个项目只允许首个实验/运行意图。相同request恢复原回执，UNKNOWN不重新dispatch；不同request不能另开后继。项目scope跨目标修订保持原总预算与deadline，不重置或扩容。旧实验保持原goal版本。end取消scope但不释放UNKNOWN或伪造清理完成。模型自主实验循环、临时child、自动后继、共享开始/终态记录和真实科研/GPU验收仍未在此切片完成。

额外409包括RESEARCH_CONFIRMED_GOAL_REQUIRED、RESEARCH_EXECUTION_CONFIGURATION_REQUIRED、RESEARCH_ORIGINAL_ATTEMPT_REQUIRED、RESEARCH_COMMITMENT_FROZEN。安装仍不自动执行任何模型；只有明确HTTP start进入准入。
