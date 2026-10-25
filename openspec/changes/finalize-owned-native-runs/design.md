# Design

## Context

动机见proposal。基线03e1dab57ecd189ec4796dfc1463947a49a194a4。

`lifecycle_observer.py::_facts`从原native ticket/effect/custody判断停止，不依赖task.terminal；`_observe_stopped`目前按child→root提交终态，tick扫描nonterminal原root。`local_budget_scopes.py::settle`要求原root及child terminal、无未解效果和原usage已结算。`Store.reserve_task`和`admission_failed`另有直接terminal路径。`task_status.py::finalized_status`已经区分原生完成和持久收尾；`storage_governance.py::release`只做事务内元数据/事件更新。

## Goals / Non-Goals

**Goals:** 针对明确装配的研究Workflow完成消费者，让原task终态、预算结算和应用完成记录/outbox作为一次数据库完成动作；借现有observer核对UNKNOWN用量，保留真实停止事实。

**Non-Goals:** 不实现研究Workflow本体、科学判断或后继执行器；不新增通知表、worker、UsageLedger hook、通用插件发现、任意回调框架或UI；不替代Agno恢复或原effect控制者。

## Decisions

### 1. 完成消费者是显式可信装配

仅对明确声明完成责任的原计划运行应用完成动作。新增精确nativeComponent pin选择是当前消费者的实际需要：现有application(id,version)选择仅在没有binding owner时生效，研究Workflow带其他工具owner会漏选，且同一组件可被多个成员应用复用。组件选择须以既有完整pin(kind/id/revision/sha256)附加research owner，同时保留其他binding/effect owner，不另造摘要或证明链，不按用户app名称/前缀匹配。没有声明的core任务维持原有语义。旧pin声明仍存在但hooks缺失时保守保留；若删除全部声明，registry无法凭空识别旧责任，本change不声称具备这种识别能力，装配撤回必须保留旧声明。不能为完成流程移除其他effect/custody的正向停止要求。

采用单一同步接口 `finalization_context(conn, task)`：应用在传入的同一事务连接上获取自身/content/event锁并yield完成回调；core在该context内完成terminal/settle后调用该回调。context不得提交、吞异常或另外开启事务。只允许一个完成消费者，歧义明确拒绝，其他owner仍参与停止证明。只读完成事实含原owner/task/run/plan引用、原group结果、scope/allocation及settled statement。稳定完成身份使用原task/allocation，不额外制作hash链。回调只写自身领域记录和现有内容/outbox，不submit、取消、调用模型/网络或改写core事实。真正研究意图/是否发后继由应用核对；core不理解研究结论。暂用测试消费者验证事务，不能把它算作研究产品已交付。

### 2. 原root完成事务

现有observer继续在原root锁下验证task/plan/native身份及全部child正向停止；原task仍运行、effect未知或清理未确认则保持当前观察路径。

停止证明满足时，为该消费者使用覆盖整个已停止group的短metadata事务；不能先单独提交child终态或storage释放。完成以下动作：

1. 重新核对原root及其已停止group，按现有停止保护写全部已停止成员terminal。若保护拒绝任何必要成员terminal，不继续结算或回调。
2. 对原allocation调用公开settle；没有绑定预算的消费者按其明确契约处理，不构造假scope。返回HELD则回滚此root事务，退出为正常的finalization-pending观察结果，不把它当新的执行失败。
3. 结算成功后调用同步完成回调写应用记录和outbox，再共同提交整个group的terminal、storage释放、原root reclaimed、结算及记录。HELD或回调失败全部回滚，不吞错误或追加内部重试。已有失败/取消仍保留原停止类别。
4. delegation root reclaimed只能在完成提交后生效，不能依据本轮内存groupStopped直接提前释放。

root锁不跨await。当前具体锁次序固定为root→admission→应用/content/event namespace→usage；回调会重入namespace，因此核心协调入口须在settle取得usage锁之前取得这些具体消费者已用的namespace锁。不得在reserve已有admission/metadata锁时倒序取root锁，reserve只跳过该消费者的快捷terminal并留给observer。回调不能重新取root锁；不抽象成通用锁框架。

HELD回滚保留原root nonterminal；现有tick会继续按同一身份核对。UsageLedger.finish_attempt收到真实原attempt证据并结算后，下一正常tick即可完成；没有新通知或丢唤醒窗口。重启同样扫描原root，永不新建task或重派模型。等待可能长期保留容量，这是准确保留UNKNOWN而非容量释放优化。

### 3. 停止与收尾投影分离

禁止把等待账务/应用完成注册为task_held、effect custody或ended_reason，否则_facts、Store终态保护、settle会相互阻断并可能错误取消。groupStopped仍表示执行与效果已正向停止；finalization是否提交是另一个事实。正向停止观察及其原成功/失败/取消类别独立提交到现有任务观察元数据；该标记同时在原执行入口拒绝保留的模型/工具context新增工作，原清理/观察仍允许。以实际保留入口调用计数证明，不只检查显示。正向停止类别不能随完成事务回滚而丢失；以后scope到期或账务等待不能把已停止成功改成失败/取消。原effect仍未知时不得提前写正向停止证明。_observe_summaries不能再仅凭groupStopped跳过尚未提交root：展示原native完成及finalizing/原用量待核对；失败/取消也保留真实类别并说明收尾未完成。显示不能伪造任务仍在训练或清理已全部提交。

最终实验记录/outbox需等待完成事务；等待期间可读取原生实际结果与已持久领域事实，不能把未生成最终记录等同于未产生实验结果。

### 4. 封闭终态旁路

`Store.reserve_task`原有容量清理会直接terminal并释放storage；对声明完成消费者的task不能使用该快速路径，仍由原observer完成，其他task保持不变。`admission_failed`对于无run的rejected任务也不能提前跳过消费者：保留rejected事实，沿observer的“明确拒绝且无native/effect”停止证明完成原记录/预算。没有实际绑定allocation的准备失败只保留已存在事实，不伪造预算结算或成功运行。

所有旁路都使用同一可信消费者识别规则。检查其余terminal写入，不能以terminal布尔先落库、回调以后补写的方式“修复”。

### 5. 并发与验收

真实PG验证：回调写记录后异常、settle后异常、提交响应丢失、原usage UNKNOWN后结算、重启、并发observer与另一个reserve触发容量清理。观察同一root身份、预算hold、storage hold、应用记录与唯一outbox；任何失败窗口都不能出现已释放却无记录，或重复下一轮意图。使用现有P3投递确认结算已提交后才准入；合成provider只证明协议，不是C01真实模型自主验收。

## Risks / Trade-offs

- [未知用量长期占用任务容量] → 明确finalizing原因，保留原usage证据恢复；不靠新task绕过。
- [现有快速终态路径遗漏] → 测试直接触发reserve/admission_failed，不只调用新完成方法。
- [回调锁顺序冲突] → 先明确实际锁协议，真实并发/有界等待验证；不增加通用锁框架。
- [已停止事实与持久终态混淆] → 分别断言groupStopped、native状态、terminal和预算状态，不用页面单词代证据。

## Migration Plan

先由coordinator确认消费者选择与锁协议，再独立分支实施core端口和PG测试；研究change只在该接口通过后接入完成回调。没有历史数据清空或破坏性迁移。撤下实现时保留旧精确pin声明并使其hooks不可用；不声称删除所有声明后还能识别原owner。实际装配撤回边界需与其他binding/effect owner共存一起验证。
