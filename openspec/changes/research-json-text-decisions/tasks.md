# Tasks

## 1. 规范与实现

- [ ] 1.1 提交规范，coordinator与独立review确认明确文本协议和严格失败边界。
- [ ] 1.2 仅修改研究Workflow模型指令/output_schema配置；保持原Decision/Evaluation解析与生命周期。

## 2. 验证

- [ ] 2.1 真实OwnerChatModel + synthetic HTTP + native包装验证正确JSON及文本请求，不换模型，原凭据/授权/预算调用保留。
- [ ] 2.2 非法JSON、缺失/额外字段、无证据达标零child/零额外模型调用；无效评价不发布最终决定/后继。
- [ ] 2.3 保留首失败，轻量检查与必要串行PG；作者外完整base/head精简review，提交精确证据供集成。
