# Design

## Context

见proposal。已有`ProjectDetails.tsx`提供目标编辑、确认、结束与历史；`RunRecords.tsx`读真实实验/轮次；`AssistantSettings.tsx`已用CAS设置QA，`useResearchCommand`已保留owner/request/body恢复。无需重做这些链路。当前UI直接读取goal.agreement、experiment.conditions及terminal.runtime，而P7保护投影会省略它们；当前目标编辑重组body只保留execution，会遗漏P8 evidence。

## Goals / Non-Goals

**Goals:** 接通已确认工作台到P7/P8真实接口，保护撤权后界面，完整表达证据选择、目标版本与成果缺项。

**Non-Goals:** 新视觉设计、第二聊天/通知历史库、自动重试控制器、客户端执行配方、下载代理服务、后台常驻轮询、真实GPU或科学价值宣称。

## Decisions

### 1. 三组现有界面接缝

- `AssistantSettings.tsx`和assistantClient类型接`associations:{enabled,maxRecipients}`；首次表单默认可见启用和2个收件人，但只有显式配置提交生效；旧缺字段仍未启用。沿原revision/预算/未计量提示，不另建订阅管理器。
- 团队页保留助手目录，增加分页关联与成果目录；关联详情显示作者、relation、agent分析、sourceIds/inputContentIds。来源读取复用core application-content富publication及当前权限，不加研究来源HTTP或影子正文。新有限URL指针沿`research-composition.tsx`现导航和资源返回，不复制router。
- `ProjectDetails.tsx`新增成果页；作者生成manifest复用应用命令hook及owner/project范围恢复键，payload仅requestId/expectedVersion。团队成员只读，不获得项目/原job写权。manifest展示原记录、缺项、未验证标签及继续研究说明。无“下载后即复现成功”状态。

### 2. 已与P7作者核对的受保护响应

P7作者确认下列形状在整改中保持，实施以最终提交再核对；UI用显式联合类型分支，而不是给缺字段补空对象伪装正常：

| 对象 | 来源不可用时保留 |
| --- | --- |
| project | sourceUnavailable:true；ending为null或{state:'ended'}；其他安全项目身份/固定状态 |
| goals | version、confirmedAt、sourceUnavailable:true；没有agreement/createdAt |
| experiment | id、projectId、goalVersion、sourceUnavailable:true、attempts:[{id,operationId}]；没有hypothesis/conditions/operation |
| round | 原id/goalVersion/scopeId/allocationId/taskId/deliveryId/terminalRecordId/continuations；sourceUnavailable:true、decision:null、terminal:null或{state:'ended'} |

在`types.ts`/`runs.ts`表达并在ProjectDetails、助手侧栏及RunRecords使用。撤权后不进入依赖agreement的编辑器，不显示旧正文/产物。{state:'ended'}仅证明原终态存在，不证明新取消成功或资源已清理。原身份/重新核对及当前后端允许的取消入口保留，不重新派发。owner/选中ID切换、重读及403/404清空旧派生正文，迟到读取不能复原它。沿已实现AbortSignal/auth epoch，避免新增状态机。

### 3. 精选字段与目标编辑

`Agreement.evidence`按P8实际契约为可空`{toolMaterial:精确已发布pin,fields:{metrics?,source?,run_recipe?}}`，字段值为有限JSON顶层属性名。用户选择精确材料、勾选角色并填写字段名，不输入任意JSON或脚本；从既有发布材料/应用选择读候选，是否满足唯一CLI来源仍由后端判定。缺可确认候选时给现材料/资源入口，不虚构默认collector。

目标编辑从原约定保留execution和evidence，只有用户明确修改选择才变更。历史显示每版本选择与公开范围。运行后budget/deadline/execution继续受原commitment限制；目标修订不是停止命令。若保存新版本但原轮次未终结，明确提示核对原轮次；新目标如何续接沿现后端availability/start事件，不自造执行序列。现取消/结束文案和原请求恢复继续复用。

### 4. Manifest与ZIP的边界

已核对P8的POST `/projects/{id}/deliveries`，GET `/deliveries`、`/deliveries/{id}`、`/deliveries/{id}/download`；列表只有安全id/owner/createdAt，不能猜项目标题。详情包含sourceIds、recordIds、records、missingEvidence、verificationStatus、remainingQuestions及continuation。任何缺项显著显示；remainingQuestions.status=not_provided不解释成没有疑问。

JSON沿factoryRequest(expectedOwner)。ZIP是应用整体导出，不是有独立job/hash元数据的artifact，不能套`verifiedArtifact`宣称SHA通过。窄下载函数沿现同源credentials、redirect:error、auth epoch/expected-owner和AbortSignal边界；读取失败不触发浏览器保存，成功只称已交给浏览器下载。避免持久Blob或将源码/配方自动执行。无需为一个ZIP新增泛型传输框架；若共享fetch需窄调整由coordinator确认ownership。服务端每次生成字节重查全来源，前端不能仅靠先前manifest授权。

### 5. 验收序列与复用

契约A02/A03/A06/A07/A08、B01/B02及C04机制边界；不复制17项完整矩阵。

1. 确定性UI测试：旧配置不自动启用、显式关联提交；所有受保护union不崩溃/无旧正文；目标编辑保留evidence；成果同键恢复/CAS；owner切换中止下载和迟到来源；缺项/未验证标签。
2. 串行真实后端浏览器：两成员显式配置→选中字段后实际确定性执行→自动关联及来源→在途目标修订/原预算→结束或负结果→作者生成成果→另一成员从可读目录下载。核对实际manifest/ZIP，不拦截业务API。
3. 撤回未显式引用的输入后重读关联、项目/轮次与成果，验证整段隐藏/下载拒绝；保留原操作身份。覆盖深链、刷新、重登、资源往返与窄屏焦点。只模型HTTP传输可合成；实际独立复现由P8相应CLI验证/真实C04负责，不能以下载测试替代。
4. Web完整适用检查、作者外完整base/head精简review、精确CI由coordinator核对。首失败保留；不改变超时/通过线追绿。

## Risks / Trade-offs

- 保护形状较普通对象窄 → 明确union和实际撤权fixture，而非一串可选链掩盖语义。
- P7/P8接口仍在整改 → 上述已确认边界先立spec；最终响应字段/源码SHA冻结后更新映射再实施，不以当前分支截图当新head验收。
- ZIP与单artifact不同 → 不杜撰hash保证；当前来源授权和错误可见性是下载门槛。
- 真实模型/科研/远端参数尚未冻结 → 对应C/D项仍BLOCKED，浏览器仅证明真实界面与机制。

## Migration Plan

纯前端消费者，无数据库/凭据迁移。旧无evidence和无associations配置按缺项/未启用显示，不自动共享或调用模型；回退不修改已有项目/原任务。保留独立平台入口与已确认布局。
