## ADDED Requirements

### Requirement: Research-free default deployment
系统 SHALL 在未安装旧 Research 包、未导入其源码且不注册其材料/应用的条件下，从空 PostgreSQL 和工作目录启动通用底座。

#### Scenario: Empty core startup
- **WHEN** 操作者使用新建隔离空库与默认部署入口启动服务
- **THEN** 健康、原生 worker、通用身份与资源接口可用，且没有 Research 路由、种子或运行期依赖

### Requirement: Standalone authenticated workspace
系统 SHALL 在不包含旧 Research 页面或导航的情况下提供正常登录、主页、通用模型与连接资源入口以及退出重登行为。

#### Scenario: Empty authenticated workspace
- **WHEN** 合成用户通过实际认证协议登录空底座，并刷新或直接访问有效通用入口
- **THEN** 页面正常呈现明确空状态、资源管理入口和退出能力，旧研究地址不呈现旧应用或死链接

#### Scenario: Demo and production-mode evidence
- **WHEN** 分别验收 demo 与生产模式的本地合成身份
- **THEN** 记录各自真实浏览器流程与截图，并明确真实外部生产身份是否未验收

### Requirement: Data preservation during application retirement
移除源码与默认装配 MUST NOT 删除现有数据库记录、用户凭据、vault key、运行产物、备份或 Git 历史。

#### Scenario: Retire without data cleanup authorization
- **WHEN** 旧数据清单仍等待针对准确目标的即时确认
- **THEN** 只在新建隔离 fixtures 上验证，不调用 destructive migration 或删除旧数据路径
