# Design

## Context

参见proposal。`MemberCliAdapter.invoke`经既有personal_tool_registration运行并将受限JSON输出持久到原effect；af_effects只有原task/run/fingerprint/status/result，不能反推出argv、源码版本或adapter身份。`DelegatedOperations._observe`的output.result是模型正文，不是CLI测量。当前ResearchRounds.results已有原custody closed检查；原生函数支持注入application_context，write_artifact复用授权、输出限制和原run。ApplicationContent已负责团队读/作者写及精确artifact引用。

## Goals / Non-Goals

完整目标：自动记录实际选中证据，交付原始依据、配方、负结果及继续入口；确定性CLI独立复现验证机制，真实科研另验。非目标：通用collector插件、自动脱敏任意文件、任意shell执行服务、全空间分享、复制archive/恢复、UI变化、远端清理。

## Decisions

### 1. 唯一当前消费者及确认边界

采用一个具体CLI JSON证据消费者，不另造CLI runner。项目Agreement新增可选evidence配置：`toolMaterial`精确已发布材料pin、`fields`角色到JSON顶层key的有限映射。当前具体CLI消费者只产出metrics/source/run_recipe三种角色；依赖、数据前提和预期输出写在run_recipe中，不提前建立未被实际消费的独立角色。映射中的key为普通属性名，不支持路径表达式或脚本。选择由owner确认目标时写入不可变目标版本，不能由Decision/Evaluation或程序输出替换；未配置保留旧项目并明确证据未配置。

v1自动消费者限定原child计划仅有一个个人CLI工具且精确匹配toolMaterial及其已确认operation/runtime binding；从既有材料/绑定读取验证transport=cli。若不能证明唯一来源则明确不采集，不以输出自报toolName或文件名赋权。这个限制是可证实的首个collector边界，不是最终限制所有研究只能单工具；多工具自动归因需先增加真实调用来源证据，不能假定af_effects存了它没有的字段。

程序输出不是分享授权。仅取fields明确选中的原JSON字段；其他output、stderr、环境变量、连接、聊天和未选附件不进入artifact/共享内容。模型可解释/引用，不能选更多字段或把私有日志自动公开。明确选择不是逐轮人工发布审批，符合契约的每轮自动采集和分享。

### 2. 准确调用链与core依赖

既有child Agent → personal_tool_registration → MemberCliAdapter → 原effect持久化不变。parent `research_results`原生Step增加已支持的application_context参数，将其传给具体ResearchEvidence.capture。沿ResearchRounds._bound、attempt.operation_id及custody.read确认原owner/root/run/closed child身份；UNKNOWN不启动新实验、不猜测输出。

core依赖已由coordinator独立规范/实现审查：9ad11a0、be25678（/workspace/agent-factory-original-tool-results），应用在本规范复审后摘取。具体接口`ApplicationRuns.tool_results(owner, task_id, run_id)`返回taskId/runId/planId/materialRef/operationRef/binding{adapterId,revision,toolName}/receipts{effectKey,outcome,output}，要求本地ordinary executor、完整唯一工具、持久MemberToolOperation CLI证明；不支持时409 APPLICATION_CLI_PROVENANCE_UNAVAILABLE，不退回弱推断。应用对原custody child、原run及owner已确认toolMaterial再次核对；所有缺失归因保留为明确未采集，不从输出内容猜测。端口无HTTP/执行/更新，不返回rawconfig、connection或任意metadata；不证明argv/source真实性。当前唯一消费者ResearchEvidence。

owner只读端口可读取已停止原task；不要求旧预算仍可花。应用选中字段在仍获授权的parent结果步骤通过`application_context.write_artifact`写入，不在终态callback临时创建执行上下文。父artifact附原child/task/run/effectKey及材料pin来源，不能冒充child自行写的文件。content.publish的附件引用实际父task/artifact/hash。

### 3. 证据数据与原子性

每个原attempt保存一次selection JSON（新增nullable列，不另建执行状态表）：source原root/child/operation/effects；选中artifact引用；缺少角色；采集结果的明确类别。该行仅是领域证据，不重写native状态。fields配置属于原目标版本，同attempt不同选择冲突。

使用原应用Store.transaction及既有锁序，把artifact_write（借用同conn）与selection写入一次提交；重复capture先读原selection，沿原身份返回，不能重复写artifact或重新调用CLI。数据库故障回滚全部。artifact损坏/原身份冲突明确失败，不转成缺项。未配置、没有成功CLI结果、缺某选中字段是缺项，不伪造值，不因此阻止正向停止任务清理。

原完成callback仅引用已持久selection，将精选记录和后继事件纳入既有完成事务。当前owner撤权时沿已有authorization_withdrawn保留领域终态但不发布/续跑。没有selection时发布已有运行事实及missingEvidence；禁止最后一次猜测模型报告补齐。

每个角色输出使用有限JSON或UTF-8文本artifact，不访问输出声明的本地路径/URL。metrics仅有限标量指标及原effect/字段定位；source/recipe为程序输出声明与原CLI来源绑定，标注producer_declared，不把任意程序自报commit/命令升级成经core独立证明。确定性fixture将实测源码/命令与声明逐项核对；一般科学有效性仍unverified。完整执行recipe需提供代码/依赖/数据/命令/预期输出，缺任一明确列出。只拥有Factory材料hash不能代替研究代码/data版本。

### 4. 交付manifest与下载

具体ResearchDelivery服务：owner按project生成应用内不可变成果修订，复用projects.db命令幂等，新增应用领域delivery表保存id/owner/project/version及manifest；不是运行状态机或另一份artifact仓库。输入只含requestId和目标版本，不允许模型注入任意artifact授权。manifest保存原项目目标/ending、全部相关实验/负结果及原selection来源内容ID；不复制resourceRefs/connectionRefs/原聊天。**不得把派生manifest正文或附件再次publish为可独立读取的ApplicationContent**，否则generic core read/list/artifact会绕过派生依赖撤回检查。

原精选证据本身继续使用ApplicationContent，core是唯一来源权限及字节读取权威。派生manifest的每次读取和导出，在既有admission事务锁中先检查当前actor成员及全部原source content的当前读取权，再构造正文/字节快照；使用当前actor，不代理owner。任一来源撤回或不可读则整段派生正文与下载拒绝；数据库/完整性错误不吞成缺项。所有依赖包括原实验记录、目标来源、selected content，不允许只检查附件来源而泄漏别处复制来的摘要。

应用只保存引用和有限成果领域事实，不建立新的成员目录/分享ACL。作者有原领域写权；团队成员读权来自全部原source在core中的可读交集。没有可共享source的项目只可owner读取，不用空集合校验给全团队新权限。只有已在原共享记录中明确公开的目标/条件/结论才能进入团队manifest；其余owner私有信息不因manifest生成而公开。

manifest包含原共享目标/评价/停止条件、原运行与材料pin、源码/recipe/metrics证据引用、agent_analysis标签、missingEvidence、remainingQuestions和继续说明。recipe包含依赖/数据访问前提/预期比较条件；没有源码/数据/配方时不能标完整。process completed不等于scientific met；继续需要新项目/预算/身份，不重派原UNKNOWN。

HTTP仅应用router：POST `/projects/{id}/deliveries` owner生成；GET `/deliveries`分页列出当前actor可读成果的安全目录；GET `/deliveries/{deliveryId}`按当前actor读manifest；GET `/deliveries/{deliveryId}/download`有界导出。目录只有opaque deliveryId、作者ID、createdAt，不保存或返回目标/结论/题目/指标摘要；目录查询也逐项调用同一全部source权限判定，不可读项不出现，不以能列出推断拥有内容权限。当前actor有效但第三方项目原有private读不被目录放开。

分享入口为现有研究应用成果目录与具体delivery链接，不增加core ApplicationContent派生条目。不新增UI，后续经视觉确认的界面消费该目录。core generic read/list/artifact找不到派生正文或派生附件，原source本身仍按其已有权限读取。导出仅读取当前可读原content及精确artifact，不下载外部URL、不执行recipe；已下载字节不能远程撤销。

单次导出原始字节总量含manifest及选中文件，复用settings.experiment_output_bytes作为明确总上限；先核对元数据再读取，逐项核对hash/长度；超过上限明确拒绝整包，不静默遗漏。归档固定`manifest.json`及`evidence/<artifactId>`安全名；zip仅是请求期下载容器，不持久复制归档仓库。应用manifest正文复用现有16KiB JSON限额，附件分享沿20项限制；超限不声明完整，可读取原记录，不调高底座限制掩盖容量问题。

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

### 跨应用集成中的真实来源权限接缝

P7实际consumer会让精选证据依赖peer来源。已审定core固定sourceContentIds契约统一保护正文、read/list/artifact及重放；精选publication继承P7实际使用的完整来源集合。直接使用core content.read/artifact读取受来源保护的完整正文与字节，不再需要safe-shell、影子正文或应用回填读取口。manifest仍应用持有，每次检查完整sourceIds；recordIds另行标识实际交付的实验记录。依赖来源可以约束读取权，但不会因此把其正文、selectedEvidence或附件额外纳入导出。授权使用当前actor，不代理owner。

### 当前配方的有限完整性判据（实现审查整改）

三角色保持不变。metrics与run_recipe.expected均为非空对象，值只允许字符串、布尔或有限数字，不接受嵌套对象/NaN/Infinity。source是非空文本。run_recipe为对象：command为非空字符串数组；dependencies为非空字符串或字符串数组（空数组明确表示无额外包），不能是bool/number；data为已声明的字符串、数组或对象（无额外数据用空数组/对象明确声明），不接受null/bool/number；expected为上述非空指标对象。字段不符合就把run_recipe列为缺项且不发布其artifact，不推测默认值、不执行命令。数据/依赖可取得性及科学容差仍需实际复现，不由schema通过声称验证。

当前领域没有独立remainingQuestions输入，manifest明确写`remainingQuestions: {status: 'not_provided'}`；不伪造空items集合表示没有问题。未来只有实际owner/model持久字段存在时才收录其来源，不从reason自由文本猜测用户已问完所有问题。
