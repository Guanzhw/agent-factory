# Verification

## 基线与独立审查

PR104 base a2e021c97ba2257d86c1ec484296bbeda0b6c05a / head ddc82b2642e8784099e5590040ef7d4223df18b1，经作者之外pr104_independent_review完整680文件diff审查无阻断。506cb4e→ddc82b2仅五份证据文档变化，full40171164057可复用；精确head fast40173250842远端核实success。已合并d2090254ac325b8fea2d0bbe39d7a6efc74b57bc，main run40183654044 success。历史MCP时序问题、真实身份/模型/GPU未验收限制保留。

## P1 进行中验证

- architecture checker 11通过，0跳过；Pyright0错误；OpenSpec strict通过。
- 无app独立core wheel真实安装/空PG启动/native worker/关闭通过。首命令误用不支持的`--summary`退出2，未启动检查；纠正命令后退出0，不属于产品失败。
- 便携端点tests：首轮两个fixture API用错已修正；受限sandbox下TestClient/async唤醒停滞，保留栈后有界终止；允许本地网络后同代码6项通过。新增schema边界后7项通过，未改生产期限/断言。
- PG首轮8/8通过42.921s，其中2新端点case与6个被直接import误收集的旧fixture case；已改为模块导入，避免全套重复执行。最终代码PG 2/2通过、0跳过，12.404s；源码变更是文本schema兼容检查，未增加或放宽等待期限。
- 独立预审发现消息只传goal而required inputSchema仍允许配置，会导致永久未确认；先补spec文本入口边界，再修配置校验和消息inputValues映射。不是将失败放宽为通过。

原始本地日志位于本任务 `/tmp/af-research-next-evidence/` 及 `/tmp/assistant-endpoints-*.log`，仅本地证据，不声称公开可下载。最终精确head审查/CI完成后追加结果；未运行的C/D保持NOTRUN/BLOCKED。

## P2 验证

- 便携消息6/6通过0.184s；真实PG/native3/3通过13.404s，覆盖并发重投dispatch一次、丢ACK重启保留原UNKNOWN、required goal schema实际入原任务。
- 首轮受限sandbox asyncio唤醒停滞栈与20s有界退出保留；network权限后通过，未改产品超时。输入schema映射的首版kwargs静态类型错误已修正，最终Pyright0。
- P1独立审查base d2090254 / head836f810d7fc45d8a269ca1926d2b8caa35046cb0完整19文件diff无阻断，包含文本schema整改复审。PR105 CI40184199282待终态，不能当已通过。
