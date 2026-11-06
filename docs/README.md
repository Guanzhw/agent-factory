# 文档目录

按你当前要完成的任务选择入口。本文只做导航；配置和行为以对应文档及实现为准。

## 启动和使用

- [在 Windows 启动本地服务](WINDOWS_LOCAL_START.md)：安装依赖、准备 PostgreSQL、配置登录和 HTTPS，再启动及停止服务。
- [使用研究助手](PERSONAL_RESEARCH_SESSIONS.md)：配置模型、提交目标、核对产物，以及继续或停止工作。
- [OpenCode 模型配置](OPENCODE_GO.md)：查询当前预设和模型协议。
- [个人工具连接](PERSONAL_TOOL_CONNECTION_LIFECYCLE.md)：连接 CLI 和 MCP 工具。
- [服务关闭说明](SHUTDOWN.md)：区分 HTTP 连接排空、应用清理和停止结果。

## 理解和扩展

- [架构](../ARCHITECTURE.md)：底座、应用、适配器和装配代码的职责。
- [运行机制](RUNTIME_DESIGN.md)：任务、资源、恢复和停止的实现边界。
- [应用开发](APPLICATION_DEVELOPMENT.md)：开发并装配业务应用。
- [应用接口](APPLICATION_INTERFACE.md)：查询输入、资源和原生执行接口。
- [开发检查](DEVELOPMENT_CHECKS.md)：运行检查，并区分真实验证与合成测试。

## 查阅专题和历史

[文档分类表](DOCUMENTATION_MAP.md)标明当前入口、组件专题以及历史设计和验收记录。历史文档描述当时的版本，不能作为当前功能已通过验收的证明。

默认产品采用[自主 Agent 与统一界面](plans/agent-autonomy-20261106.md)。旧固定研究流程和旧双入口方案不再定义默认使用方式；保留的实现或记录通过当前工作界面访问。
