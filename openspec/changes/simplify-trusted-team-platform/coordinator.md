# Coordinator

主代理拥有 OpenSpec 文档、文件分工、任务状态和最终验收。实现者不得自行勾选任务。表中“待验证”表示已有修改但尚未完成对应任务的完整验收。

| 负责者 | 任务 | 文件范围与边界 | 当前状态 |
|---|---|---|---|
| trusted_team_auth | 1.1、1.2，2.2 测试 | auth/accounts、身份测试、credential vault/local credential 测试；不编辑 main/config | 已验收；真实原生 HTTP/WebSocket、SQLite/PostgreSQL 回归通过 |
| account_resource_ui | 1.4，3.4 SSH/凭据界面 | AccountManagement、App/navigation、PersonalCredentials、PersonalSSHServers 及对应测试 | 账号浏览器已验收；SSH 界面由端点负责人完成真实流程 |
| open_resource_endpoints | 2.1 端点、2.3、3.2 | HTTP/model transport、SSH 身份/凭据/连接、科研 transport 消费者及对应测试 | 实际 HTTP/TLS/SSH 和 Linux 浏览器通过；Windows SSH 的 POSIX 运行时限制单独记录 |
| resource_sharing | 2.1 可选凭据、3.1、3.3、3.4 模型/远程界面 | resource_sharing、connections、personal_models/connections 和相关 UI/测试 | 共享与撤回实际调用、两账号远程服务浏览器流程均通过 |
| user_tool_connections | 2.4、5.3、3.3 工具 | personal tool/CLI/MCP 模块及 UI/测试 | CLI/MCP 与新工作进程执行、真实 MCP 浏览器及最终完整 PostgreSQL 均通过 |
| member_catalog_management | 4.1、4.2、4.3 | applications/material_governance 和对应 UI/测试 | 63 项 Linux/PG、37 项 UI 通过；旧历史、同名工具隔离及文档已复核 |
| execution_simplification | 5.1、5.2，5.3 按需注册 | plan_policy、execution_bindings、runtime、store、科研 controller/compatibility 及对应测试 | 已验收；旧工具许可模块删除，取消/预算/UNKNOWN 和祖先约束通过 |
| member_callsite_migration | 1.3、5.4 脚本 | 其既有成员调用迁移文件、bootstrap/candidate/baseline/public workflow/accept 脚本及测试 | 已验收；最终 Go 入口旧配置修复后 15 项 Linux/PG 通过 |
| bootstrap_policy_cleanup | 5.4 preflight | research_bootstrap_*、research_candidate_state、autoresearch_operator_bindings 及对应测试 | 46 项含真实 PG 通过；当前操作文档已同步 |
| integration_assembly | 2.2 实现、2.5、5.5 | core main/config/local_credentials、research assembly/config、deployment main/validation、native ingress/assembly/deployment 测试和部署文档 | 核心独立安装、vault 和真实 PREPARING 恢复通过；独立装配审查关闭 |
| core_fixture_migration | 6.1、6.2 核心夹具和数据库全量 | 已分配的核心/恢复/调度测试文件；最终全量验证只读源码 | 完整 PostgreSQL 3140 通过、61 显式跳过，七组 required 全通过，accepted=true；快照完整性通过 |
| research_fixture_migration / scientific_fixture_migration | 6.1 科研夹具 | 已分配的科研测试文件，不改生产代码 | 原生科研与三端科学执行通过；已修正旧身份 mock、隔离 stdlib 夹具和快照 CRLF 差异 |
| linux_custody_review | 6.1 Linux 环境差异 | 四个未改动的文件身份/科研文件测试；生产代码只读 | 已在原始主线复现 inode/时间戳测试不确定性，修正夹具并记录实际边界 |
| coordinator / 独立 reviewer | 6.1—6.5 | 全量验证、真实浏览器、独立审查与最终差异核对 | 26/26 任务完成；Linux 便携、Web、PostgreSQL 全量及独立审查通过，Windows 限制已记录；OpenSpec 严格校验、原工作区保留和专用服务清理完成 |

环境：Windows `.venv`；Linux 隔离 Python 环境；任务专用 PostgreSQL 16.15，`127.0.0.1:55432/factory_test`。测试用唯一数据库或 schema，未访问原工作区数据库。专用 PostgreSQL/SSH 服务已在 runner 退出后关闭；数据库、密钥及证据保留。全量验证日志保存在 `.local/validation/`，第一轮 Windows 失败日志保留。

跨所有权修改需先协调。实现者返回任务编号、实际 diff、精确验证命令、通过/失败/跳过和未决假设。所有历史审批与效果记录保留；生产代码不为旧测试恢复审批兼容层。
