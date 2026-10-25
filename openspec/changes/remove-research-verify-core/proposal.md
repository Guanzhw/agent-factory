# Proposal

## Why

用户希望先移除现有 AutoResearch/Research 应用，通过空数据库实际启动和浏览器登录、主页验证底座是否独立。新 AutoResearch 只进入用户旅程讨论，本次不实现。基线为 main `a2e021c97ba2257d86c1ec484296bbeda0b6c05a`；原 #97–#103 已合并且主线 CI 成功。

## What Changes

- **BREAKING** 删除旧 Research 应用源码、专属界面/路由/导航、部署注册、材料种子及无其他消费者的依赖和测试。
- 保留可复用 Agno3.1/PostgreSQL 底座、通用 CLI/MCP/SSH/模型/连接资源、执行预算、取消和 UNKNOWN 原身份恢复边界。
- 默认部署不注册 Research；空库初始化可进入通用登录、主页、资源入口，不残留旧研究页面或死链接。
- 用新建隔离空数据库和工作目录完成实际服务与浏览器验收，区分 demo、生产模式合成身份与真实生产身份。
- 不删除旧数据库、用户记录、凭据、vault key、产物、备份或 Git 历史；永久删除独立等待准确目标清单确认。

## Capabilities

### New Capabilities
- `standalone-core-workspace`: 不安装旧 Research 的登录、主页、资源工作区与空库启动边界。

### Modified Capabilities
- 无已归档基础 specs（`openspec list --specs` 返回空）；保留历史 change 验证记录，不将其改写为当前应用仍存在。

## Impact

`apps/research`、deployment、打包/检查配置、前端 composition/navigation、依赖应用的测试夹具和当前用户文档。没有破坏性数据库 migration，没有部署或付费/真实外部模型访问。新独立 Draft PR 不在原七 PR 的合并授权内。
