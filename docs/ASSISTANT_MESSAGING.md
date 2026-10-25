# 成员助手端点与消息

助手端点是成员拥有的持久地址，固定一个已发布应用版本、mode、材料与连接引用。它不是任务或常驻进程；每次实际执行仍使用原生任务、预算和凭据机制。

端点API（均需当前成员身份）：

- `POST /api/factory/assistants`：`requestId`、`name`、精确`applicationRef`、`mode`及可选`materialChoices`/`connectionRefs`。同键同配置返回原端点，不同配置409。配置不可变，新配置创建新端点。
- `GET /api/factory/assistants?after=<nextCursor>&limit=50`：团队可发现启用端点的最小摘要；不返回连接/材料选择配置。
- `GET /api/factory/assistants/{id}`：最小摘要。
- `POST /api/factory/assistants/{id}/state`：owner以`requestId`和`enabled`启停。停用不等于取消已有任务。

文本入口接受无inputSchema的mode，或只要求string `goal`的schema；不能配置需要其他必填输入的mode。端点引用不会替代实际准入时的当前发布、成员和资源校验。接口不接受owner或凭据覆盖字段。

消息API：

- `POST /api/factory/assistants/{id}/messages`：`requestId`与2–2000字符`text`；以接收者固定配置提交原生任务，发送者不能覆盖执行身份/配置。
- `GET /api/factory/assistant-message-requests/{requestId}`：发送者丢响应后查询原消息。
- `GET /api/factory/assistant-messages/{id}`：双方读取正文和限定delivery收据，第三方不可读。

重复POST只读原收据，不重新提交。首次保存后、准入前崩溃显示`unconfirmed`，不猜测可重试；`prepared`或`unknown`不表示运行完成。浏览器离线不影响已配置端点准入；这不证明完整问答、自动订阅、QA零GPU或真实研究效果已实现。相关验收见[最终验收契约](plans/research-platform-acceptance-contract.md)。
