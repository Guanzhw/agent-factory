# Design

## Context

参见proposal。`MemberCliAdapter.invoke`经既有personal_tool_registration运行并将受限JSON输出持久到原effect；af_effects只有原task/run/fingerprint/status/result，不能反推出argv、源码版本或adapter身份。`DelegatedOperations._observe`的output.result是模型正文，不是CLI测量。当前ResearchRounds.results已有原custody closed检查；原生函数支持注入application_context，write_artifact复用授权、输出限制和原run。ApplicationContent已负责团队读/作者写及精确artifact引用。

## Goals / Non-Goals

完整目标：自动记录实际选中证据，交付原始依据、配方、负结果及继续入口；确定性CLI独立复现验证机制，真实科研另验。非目标：通用collector插件、自动脱敏任意文件、任意shell执行服务、全空间分享、复制archive/恢复、UI变化、远端清理。

## Decisions

### 1. 唯一当前消费者及确认边界

采用一个具体CLI JSON证据消费者，不另造CLI runner。项目Agreement新增可选evidence配置：`toolMaterial`精确已发布材料pin、`fields`角色到JSON顶层key的有限映射。角色仅metrics/source/dependency_lock/run_recipe/data_descriptor/selected_result，key为普通属性名，不支持路径表达式或脚本。选择由owner确认目标时写入不可变目标版本，不能由Decision/Evaluation或程序输出替换；未配置保留旧项目并明确证据未配置。

v1自动消费者限定原child计划仅有一个个人CLI工具且精确匹配toolMaterial及其已确认operation/runtime binding；从既有材料/绑定读取验证transport=cli。若不能证明唯一来源则明确不采集，不以输出自报toolName或文件名赋权。这个限制是可证实的首个collector边界，不是最终限制所有研究只能单工具；多工具自动归因需先增加真实调用来源证据，不能假定af_effects存了它没有的字段。

程序输出不是分享授权。仅取fields明确选中的原JSON字段；其他output、stderr、环境变量、连接、聊天和未选附件不进入artifact/共享内容。模型可解释/引用，不能选更多字段或把私有日志自动公开。明确选择不是逐轮人工发布审批，符合契约的每轮自动采集和分享。

### 2. 准确调用链与core依赖

既有child Agent → personal_tool_registration → MemberCliAdapter → 原effect持久化不变。parent `research_results`原生Step增加已支持的application_context参数，将其传给具体ResearchEvidence.capture。沿ResearchRounds._bound、attempt.operation_id及custody.read确认原owner/root/run/closed child身份；UNKNOWN不启动新实验、不猜测输出。

需要最小可信只读端口（由coordinator审定并实现）：`ApplicationRuns.tool_results(owner, task_id, run_id)`，当前member+Store.task(owner)+精确task.run_id核对，返回有限原personal-tool effects `{effectKey,status,outcome,output}`，非完成状态不给成功output。仅Python服务，无新HTTP、无代他人read、无提交/重试/更新；限制沿原已存在工具结果大小/调用预算。当前唯一消费者ResearchEvidence，应用禁止自行直查af_effects。端口不声称知道工具名/argv，归因依赖上条精确单CLI计划。若无法从现有选定材料证明唯一CLI，实施停在此边界报告，不能降为schema看起来相似就接受。

owner只读端口可读取已停止原task；不要求旧预算仍可花。应用选中字段在仍获授权的parent结果步骤通过`application_context.write_artifact`写入，不在终态callback临时创建执行上下文。父artifact附原child/task/run/effectKey及材料pin来源，不能冒充child自行写的文件。content.publish的附件引用实际父task/artifact/hash。

### 3. 证据数据与原子性

每个原attempt保存一次selection JSON（新增nullable列，不另建执行状态表）：source原root/child/operation/effects；选中artifact引用；缺少角色；采集结果的明确类别。该行仅是领域证据，不重写native状态。fields配置属于原目标版本，同attempt不同选择冲突。

使用原应用Store.transaction及既有锁序，把artifact_write（借用同conn）与selection写入一次提交；重复capture先读原selection，沿原身份返回，不能重复写artifact或重新调用CLI。数据库故障回滚全部。artifact损坏/原身份冲突明确失败，不转成缺项。未配置、没有成功CLI结果、缺某选中字段是缺项，不伪造值，不因此阻止正向停止任务清理。

原完成callback仅引用已持久selection，将精选记录和后继事件纳入既有完成事务。当前owner撤权时沿已有authorization_withdrawn保留领域终态但不发布/续跑。没有selection时发布已有运行事实及missingEvidence；禁止最后一次猜测模型报告补齐。

每个角色输出使用有限JSON或UTF-8文本artifact，不访问输出声明的本地路径/URL。metrics仅有限标量指标及原effect/字段定位；source/recipe为程序输出声明与原CLI来源绑定，标注producer_declared，不把任意程序自报commit/命令升级成经core独立证明。确定性fixture将实测源码/命令与声明逐项核对；一般科学有效性仍unverified。完整执行recipe需提供代码/依赖/数据/命令/预期输出，缺任一明确列出。只拥有Factory材料hash不能代替研究代码/data版本。

### 4. 交付manifest与下载

具体ResearchDelivery服务：owner按project生成不可变成果修订，复用projects.db命令幂等与ApplicationContent source/revision。输入只含requestId和目标版本，不允许模型注入任意artifact授权。服务收集原项目goals、ending、全部原实验/负结果及已发布selection内容ID；正文不复制resourceRefs/connectionRefs/原聊天。只有当前原记录在core中可读时才能引用分享，不能把撤回来源复制成新公开正文。

manifest包含目标/评价/停止条件、原运行与材料pin、选中源码/依赖/recipe/data/metrics证据引用、agent_analysis明确标签、missingEvidence、remainingQuestions、继续说明。没有精确源码/数据/配方时不能标完整；process completed不等于scientific met。继续需要新项目/预算/身份，不重派原UNKNOWN。

HTTP仅应用router：POST `/projects/{id}/deliveries` owner生成，GET `/deliveries/{contentId}`按当前actor读manifest，GET `/deliveries/{contentId}/download`有界导出。复用ApplicationContent.read/artifact验证所有依赖内容及精确附件；不代理作者全job。任一来源撤回时整个派生manifest正文/下载拒绝，不只删链接留摘要；已下载字节不能撤销。导出只读取本地已有artifact，不下载外部URL，不执行recipe。

单次导出原始字节总量含manifest及选中文件，复用settings.experiment_output_bytes作为明确总上限；先核对元数据再读取，逐项核对hash/长度；超过上限明确拒绝整包，不静默遗漏。归档固定`manifest.json`及`evidence/<artifactId>`安全名；zip仅是请求期下载容器，不持久复制归档仓库。manifest正文仍受现有16KiB限制，附件分享沿20项限制；超限不声明完整，可读取原记录，不调高底座限制掩盖容量问题。

### 5. 具体责任与实现顺序

应用作者拥有evidence.py/delivery.py、projects Agreement及nullable selection、rounds/workflow/public窄接缝和专属测试。core tool_results端口及精确单CLI身份读取由coordinator独立决定/集成；不在应用引用core私有表或重写工具调用。QA/core model/UI不动。

先实现选中证据与manifest消费；CLIcollector的只读端口与归因契约审定后接真实原运行。A（手动已有artifact导出）只可作为机制子步骤，不能报告自动P6/P8已完整。每一集成点独立完整diff review，重型PG串行。

## Risks / Trade-offs

- 输出含私密字段 → owner固定fields选择、私有canary测试、不共享未选字段；不做假自动脱敏。
- producer自报recipe不可信 → 明确producer_declared、真实CLI独立复现检查，不靠模型验证。
- 远端artifact不能由当前ApplicationContent直接读取 → 本change不导入、不清源；远端归档另有窄core契约与D02验收，保持BLOCKED而非虚构local引用。
- 正式模型/科学容差/硬件未冻结 → 合成与确定性CLI只证明机制，不关闭C04/D02真实要求。

## Migration Plan

Agreement新增可选字段，旧值无配置；attempt仅加nullable selection。旧记录、原task/预算/消息不变，无数据清空。移除应用仍保持core可用。回退代码忽略新增列，不删除artifact或历史内容。
