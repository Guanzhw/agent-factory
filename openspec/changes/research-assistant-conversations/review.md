# Independent review

## Scope and conclusion

**累计代码、简洁性及分层实测证据审查 PASS，可冻结交付 head 进入 CI。准确最终 head 的 CI/发布仍 pending，本记录不表示已经发布。**

- Base：`0acb41e02ac9453bd8c5be751cecf13dc04ef02f`。
- 产品 head：`66f39158a865916a6c2b4389ec9b9a37d442a402`；后端冻结提交 `59010b5219fbb7016582d831e09cae4dfd81de0b` 的字节未再变化。
- `/root/compare_review` 审查完整累计 34 个已提交文件及随后恢复契约/使用文档；28 个产品及测试文件逐 SHA 对照作者冻结清单和独立测试快照一致。`/root/compare_review/hook_early_review` 另审全部 12 个前端文件及恢复反例。两位 reviewer 均未编写产品实现。
- 方案 `ac041a3` 由另一非作者 `/root/context_capabilities` 审查。依赖 PR #152 的首次 Ready 拒绝没有被绕过；取得针对动作的新明确授权后已正常合入上述 base，tree 与已验 `9566a94f` 相同，本 reviewer 已本地核对。后续发布由协调者另行执行。

本片只有人工 UI 发问、B 既有预授权 QA 运行、原问题接续及 A 下一轮采用。Agent 自主询问/通知/采用明确留给紧接续片，不把人工入口变成全局逐条审批。

## Findings and fixes

### P1：回复采用与协议取消锁序相反，已关闭

原新路径持会话写锁后，由 `AssistantMessages.read` 获取 admission 锁；既有 `Store.reject_model_protocol` 先持 admission，再经取消回调获取会话写锁。作者把 13 个短写入口统一为 admission → session，模型调用和执行准入仍在事务外，没有新增锁框架。

作者原回归检查安全终态任务；独审另用真实 PostgreSQL、真实消息读权和另一个仍活动的研究任务进行双线程 barrier 配对：取消方持 admission 时可以取得 session 锁，真实协议拒绝/取消完成，采用方随后保留正确原回复。只在测试内移除新增 guard 的负对照确实观察到相反锁顺序，随后释放锁，未故意留下死锁。回复生成在该独立反例中是明确的 SQL 合成夹具，不冒充模型问答。

### P2：已提交消息被当成未发送，已关闭

真实 QA 已准入后禁用成员，旧代码的最终投影返回普通 403，前端可能删除原请求指针。原失败日志保留。修复只把提交后的 HTTP 失败归为 `RESEARCH_QUESTION_ADMISSION_UNCONFIRMED`；恢复成员权限后，同 request 查询仍为原 task/allocation，不能重新派发。

另一个真实 HTTP 反例发现预算关闭字符串经全局 handler 丢失具体码。现只在提交前转换五个已知原因，不扩大全局异常处理，不把数据库或未知错误猜成“未发送”。两类修复均经作者之外的真实 PG 复跑通过。

### P2：迟到回执和无记录恢复，已关闭

初审 45 个原组件测试通过，但两个独立反例失败：旧实例迟到错误删除新问题指针；预算关闭让无记录请求永久占住发送入口。现只由存活实例、匹配原 request/assistant 的回执清理指针，且只认精确提交前错误。

网络失败后，仅原 request GET 返回精确 `404 + RESEARCH_QUESTION_NOT_FOUND` 才显示手动“按原请求再次发送”。复用不可变原 ID/助手/文本，不自动 POST、不生成新 ID；服务端既有 reservation 决定首次创建或只读原记录。正文沿现有 draft 清理边界保存，退出登录后只留下 opaque IDs；缺少原文时只能核对，不猜测或使用可编辑草稿替代。独立反例覆盖其他读取错误、原 POST 和重复 POST 双迟到、双击、跨挂载及退出清理。

## Complete-diff checks

原消息、预算和会话关联共享现有 metadata transaction；网络执行在提交后。并发/重复请求沿原 endpoint、allocation、task，不替换未知任务；旧独立问答不可改绑。内容事件消息仍由原 delivery 管理，Research 的手动接续不能丢弃 delivery 身份；原 trusted recovery 未改。

采用回复只给下一轮的独立请求字段，不混入纠正。服务端绑定原问题、不可变回复和来源；即使来源列表为空仍核验双方成员。已采用副本、主请求、摘要和工具边界重新核权；读取时隐藏失授权引用，旧摘要不能恢复执行权限。回复属于非权威引用，不代替任务完成或实验成功。既有历史结果不被删除，已经送到模型的内容也不宣称可撤回。

简洁性通过：复用原消息/QA、事务、预算、组件及存储清理规则，只增加 Research 关联表和局部 UI 状态；core 不导入 Research。未新增队列、harness、角色系统、通用重试层、兼容 CSS 层、demo 或模拟身份。无新依赖、凭据迁移及后端数据删除；必要错误转换均为窄边界。

## Independent evidence and remaining gates

- 独审临时 PostgreSQL：**80 tests，0 failures/errors/skips**，包括原子关联/回滚、原请求 UNKNOWN、旧事件恢复、真实 native QA 的提交后撤权、采用/摘要权限和既有会话回归。测试前后六个关键源码 SHA 一致，隔离 fixture 已清理。
- UI 独审：原 45 项通过；修复后 18 项产品回归和 10 项独立反例共 **28 项通过**，其余未改文件保持初审字节。仅 happy-dom/API 模拟，不替代真实手机/桌面验收。
- 证据位置（审查环境）：`/workspace/design-audit/research-assistant-conversations-20261028/independent-pg-review/`、`ui-review/fix-review.md`、`independent-final-code-manifest.json`。历史失败和修复后结果分别保留。
- 另一独立 QA 在 `b74ba67bab3617fbefd3704646175d8fb7cb3936` 完成真实 PostgreSQL、临时密码登录、HTTPS/Chromium 桌面和手机链路；此提交仅增加文档/图片，产品等于 `66f39158`。主 reviewer 已读执行脚本、原结果及前后源码/构建清单，确认 B 浏览器离线由原生 QA 回答、A 明确选用后下一轮收到引用、成员/来源隔离、撤权隐藏、预算草稿、刷新和双击无新增调用。网络故障由测试显式阻止首次 POST 到达，专用 404 后手动重复保持原 payload；不冒充真实网络故障统计。TLS 是临时自签 loopback 夹具，不是生产证书。
- 两次实际 OS 退出分别位于消息/关联已提交但未准入，以及原 task 已 RESERVED 但未 enqueue。重启后读/重复 POST 不执行；前者仅 B 明确接续创建一个原任务并产生一次脚本调用，后者保持原 task、null runId，连 B 的接续也不重放。没有 SQL 写终态。**RESERVED 与 UNKNOWN 不混称**；UNKNOWN/丢 ACK 由前述独立 PG 专项覆盖。这两次 OS 退出由 QA 执行，本 reviewer 审查脚本、退出 PID/代码和原始 before/after 结果，未额外复跑。
- 对应证据：`qa/browser-1793191981388782114/` 与 `qa/restart-conversations-1793192070698788313/`。源码/构建前后稳定；已实际查看采用回复、手机字段错误、撤权隐藏及手动原请求恢复四张 PNG，明确标记 SYNTHETIC QA，无真实个人资料或秘密，适合随仓库交付。脚本 provider 不是实模研究证明。
- 本片没有真实模型、GPU/SSH 或部署调用。最终 CI 仍须在准确交付 head 成功；不以本地测试、旧依赖 CI 或本审查替代。自主协作、容量、生产隔离及用户部署仍未覆盖。
