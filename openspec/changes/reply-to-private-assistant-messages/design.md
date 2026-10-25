# Design

## Context

参见proposal。当前AssistantMessages.message_for_task已核对原receiver/task/request/allocation，read限定双方但仅投影text/delivery。ApplicationContent内容不可变，set_visibility在Store.transaction取得af_admission锁。GovernedStorage读写复用当前事务连接。

## Goals / Non-Goals

Goals：原消息一次回复、双方当前来源交集、撤回串行、旧数据兼容。Non-Goals：多轮聊天协议、模型工具调用、研究schema、第二队列/ACL/答案表、公开发布、自动重试。

## Decisions

### 接口与持久化

可信同步Python接口 `AssistantMessages.reply_for_task(receiver, task_id, text, content_ids=()) -> message_projection`。receiver来自已装配运行上下文，不由模型/HTTP自报；函数仍使用message_for_task核对原owner/request/allocation和endpoint归属。没有原message拒绝，普通task不可回复。不增加HTTP写入接口。

text复用现有消息2–2000字符，content_ids复用ApplicationContent ObjectId类型和精选artifact列表20项上限；排序去重后作为规范来源集合。同一原消息只写一次，完全相同text/规范contentIds幂等，不同则409 ASSISTANT_REPLY_CONFLICT。以原消息为幂等身份，不添加requestId/hash表。空来源允许普通文本consumer；应用不能靠省略来源把实际基于证据的回复逃出撤回约束。

原af_assistant_messages增加nullable JSON reply，保存 `{taskId,text,contentIds,createdAt}`。不存独立执行状态。read/request/send现有投影增加 `reply`：无回复为null；可读为`{state:'available',text,contentIds,createdAt}`；任何依赖不可读为`{state:'source_unavailable'}`，不返回正文、来源或对方状态细节。内部taskId不额外暴露。原问句和delivery照旧保留。

### 事务与权限

具体依赖：AssistantMessages构造新增显式ApplicationContent参数，main已有该实例可直接传入，不引入服务发现或通用callback。所有模型/工具在应用，core只处理字符串和内容ID。

提交使用Store.transaction → 原admission锁 → message namespace写锁；在同连接内核对当前双方member、原task绑定、每个content的双方read权限再唯一写reply。内容服务复用连接，不持事务await。缺失或不可读来源明确拒绝且不保存回复；只捕获预期权限/不存在错误，数据库等错误不能伪装撤回。相同幂等提交也不返回已撤回正文。

回复读取在Store.transaction取得admission锁，再核对actor为消息一方、双方成员及所有来源当前权限，并在锁内构建快照。问句本身仅按既有当前actor/双方范围授权；另一方禁用仅使已存reply不可用，不让问句消失。source_unavailable是读时投影，不持久改写reply或receipt，不allocate/submit/recover。无reply的旧读取不需要来源检查。无sources回复仍要求双方当前member。

与ApplicationContent.set_visibility串行：回复提交/读取先获得锁则可以完成当时合法快照；撤回先获得锁则提交拒绝/读取隐藏整段回复。用确定性屏障验证两种顺序，不要求撤销已经返回网络的字节。来源以后重新共享且双方可读可恢复显示同一原回复，不生成新回答。撤回不删除原答复。

endpoint停用或budget到期不改写原身份，不因其停止新准入而阻止原完成记录；调用只写结果，不授予模型/工具额外运行权。运行授权仍由原native流程负责。

## Risks / Trade-offs

- 已读字节无法远程撤销 → 明确读取时授权语义，不承诺消除客户端副本。
- 无来源回答不能自动证明内容干净 → 应用QA输入仅双方共享证据且所有依据显式引用，单独验收；core不判断科学真伪。
- 锁内调用原收据可能引入额外工作 → 锁只覆盖消息/权限与回复快照；既有只读delivery查询在快照外，不调用start或observer。

## Migration Plan

沿仓库既有逐列检查迁移模式，在metadata.create_all后为旧表补nullable JSON列，PG/SQLite均验证旧行null、已有命令和任务ID不变；新表直接定义列。重启幂等；回退旧程序忽略多余列，不删数据。无破坏性迁移。
