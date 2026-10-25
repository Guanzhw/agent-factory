## ADDED Requirements
### Requirement: 响应工具调用受本次声明约束
OwnerChatModel SHALL 拒绝本次实际请求未声明的工具名，在交给 Agno 执行循环前返回安全错误；请求之间不得共享可变工具授权集合。

#### Scenario: 无工具问答收到恶意工具调用
- **WHEN** 无工具 Agent 的 CC 或 Responses 响应要求执行 train
- **THEN** 恰好一次合成 HTTP 后失败，零工具执行且无下一轮请求

#### Scenario: 正常文本和原工具仍工作
- **WHEN** 响应是正常文本或仅调用本次已声明工具
- **THEN** 正常完成或按原 Agno 工具/暂停恢复语义继续，包括 stream 委托路径

#### Scenario: 并发请求工具集独立
- **WHEN** 同一个模型实例并发发送不同工具声明
- **THEN** 每个响应只按自身请求声明校验，不借用另一次授权
