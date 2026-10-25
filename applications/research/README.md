# 可选研究应用：项目约定接口

P4当前只保存个人研究项目与约定，不启动模型、实验或训练；每个项目返回 `execution.available=false`。没有空的start路由。应用使用core认证，项目只供owner读取；后续团队记录通过限定共享内容接口发布，不把整个项目变为公开。

部署composition root显式构造 `ApplicationAssembly(name='research', install=research.public.install)`，并把 `applications` 加入Python import roots；应用自身不import部署模块。未安装时core不创建research表或路由。安装不创建后台任务/线程，不取得DB所有权，关闭仍归core。

## HTTP

前缀 `/api/factory/research`。mutation包含8–80字符requestId，重投返回原命令收据，同键异内容冲突。所有接口使用当前认证owner，不接受owner字段。

- GET `/projects?after=&limit=20`：`{items,nextCursor}`，items为项目摘要（无goals），上限100。
- POST `/projects`：`{requestId,title,assistantId?}`，title最多120字符，assistantId只能关联自己的core端点；返回详情。
- GET `/projects/{id}`：详情。
- POST `/projects/{id}/goals`：`{requestId,expectedVersion,agreement}`，追加目标版本并回到draft。
- POST `/projects/{id}/confirm`：`{requestId,expectedVersion}`，确认当前约定并标ready；没有执行含义。
- POST `/projects/{id}/end`：`{requestId,expectedVersion,outcome,reason}`，outcome为not_met或cancelled；仅记录领域结束，`resourceCleanup=not_observed`。ended不能再修订，继续研究建新项目。

详情字段：`id,ownerId,title,assistantId,state,currentGoalVersion,goals,ending,createdAt,execution`。state为draft/ready/ended。新项目version0。goals按版本升序：`{version,agreement,createdAt,confirmedAt}`。agreement字段 `objective,evaluation,stopConditions` 为1–4000字符；`resourceRefs`为slot到已有资源ref，最多30项，仅保存引用、不验证或授予执行权限；`budget`为下例。执行准入将由P5按当前资源权限再次检查，P4不创建预算scope或预留资源。

```json
{"objective":"测试目标","evaluation":"可核对评价标准","stopConditions":"达标或预算用尽停止","resourceRefs":{},"budget":{"rounds":3,"toolCalls":12,"tokenLimit":null,"amountMicros":null,"currency":null}}
```

budget沿core scope语义：rounds/toolCalls为正整数；tokenLimit为空时amountMicros/currency同时为空（不可宣称金额硬上限）；否则tokenLimit/amountMicros非负且currency为USD/EUR/CNY。目标历史agreement不可覆盖，confirmedAt是单次确认元数据。修改、确认、结束都检查expectedVersion；409 `RESEARCH_GOAL_VERSION_CONFLICT`要求读取最新状态，不能无条件重试写入。

错误使用现有HTTP异常封装，code为`RESEARCH_PROJECT_NOT_FOUND`、`RESEARCH_AGREEMENT_REQUIRED`、`RESEARCH_GOAL_VERSION_CONFLICT`或`RESEARCH_PROJECT_ENDED`。权限/幂等异常沿core契约。

## 显式运行

安装本仓库发行包后，用`agent-factory-research`启动包含研究应用的组合；默认`agent-factory`仍只启动底座。源码开发需`PYTHONPATH=applications:platform:deployment`。前端`npm run build:research`构建研究入口，`npm run build`构建无应用入口；运行时只绑定配置的地址，不由构建命令公开服务。
