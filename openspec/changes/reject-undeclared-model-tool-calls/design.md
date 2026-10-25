## Context
真实只读 QA 消费者没有 tools，Agno 未知工具调用循环仍可再次请求模型。OwnerChatModel 已区分 CC/Responses 并有严格 codec、固定选定模型和零重试。

## Goals / Non-Goals
拒绝未声明工具，保留合法工具和原生等待。无第二计数器、重试、共享 last_tools 或应用特判。

## Decisions
在原 _request 构造实际 wire body 后取该请求工具名快照；CC 从 function.name，Responses 从 name。在原 transport try/except 之外、同一调用内解析响应并验证每个返回工具名属于该快照，异常保持固定安全错误；不保存模型实例级可变工具集合。已有 invoke/ainvoke 解析的 ModelResponse 幂等分支复用，两个 stream 委托路径同受约束。校验以已通过 codec 的实际请求为准，不再重复输入 schema。

## Risks / Trade-offs
禁止 provider 凭空发起工具调用属于协议边界，不替代调用时权限/预算检查。真实 Agent + MockTransport 各协议测试恶意 train 仅一次HTTP且零函数执行，正常文本成功；实际声明工具和等待回归继续通过。并发不同工具请求与同步/异步 stream委托覆盖防串线。没有外部模型或 PG 验收声明。
