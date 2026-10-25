# Design

## Decisions

### 原任务输入读取

`delivery_for_task(owner, task_id)`先require_member，再用Store.task(task_id, owner)读取原任务。沿原task.request_id调用既有scopes.request_delivery；没有映射的人工任务返回None。存在映射时核对delivery.owner、原request对应allocation、allocation.owner/task_id及delivery关联；不一致明确409，不把损坏映射伪装人工任务。

返回仅含contentId、eventId、deliveryId、rootId、depth、scopeId、allocationId。不接受caller提供的contentId或lineage；不allocate、create、recover或重新准入。引用不是读取授权，应用随后调用既有ApplicationContent.read，以当前身份核对内容可读性并解释研究语义。原任务历史输入引用不因订阅停用变成另一个身份；内容撤回仍由原内容读取边界执行。

在GovernedStorage.read借用连接中完成读取，不取得写锁/usage/admission锁，不跨await；不创建第二身份摘要或证明链。现有request映射不可替换、allocation原绑定不可改，读取只核对这组持久事实。

### 深度由明确配置与预算共同约束

EventSubscription.maxDepth保留非负整数，移除le=20。不会新增configure maxDepth<=scope.rounds检查：depth是从事件链根累计的传播位置，rounds是当前receiver scope的累计执行预算，两个量的起点不同；小scope接收深链事件仍合法。每次delivery仍只能allocate一轮，scope总额、期限及原root/depth继承提供实际运行边界。应用可按已确认研究轮数选择maxDepth，不暗中强设22轮或无限预算。

### 安全错误码

集中一个小格式函数：HTTPException.detail若为dict则取code；若为str则直接作为候选。只保留本交付路径显式列出的Factory预算耗尽/过期、端点停用、内容不可读、传播限制和原身份冲突code；有限常量集合之外均退回异常类名。大写正则不能证明安全，全大写敏感文本也不得保存。其他情况保留异常类名。已有error列兼容，不增加字段/报告框架。该码表达技术拒绝，不表示科学未达标或实际停止证明。

## Verification

便携测试覆盖原owner隔离、人工任务None、绑定不一致拒绝、无写入/恢复、超过20深度仍受原depth/TTL边界、安全code与秘密样式文本不落库。真实PG针对实际request/allocation绑定核对只读引用和跨owner拒绝；重型测试由coordinator串行分配。无真实模型/GPU声称。
