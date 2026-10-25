## ADDED Requirements

### Requirement: Same-database removal preserves original unfinished work
独立core SHALL 在不安装研究应用时继续提供健康、登录鉴权、任务读取和通用资源入口；移除应用不删除原数据、不重新派发或将未知效果伪造为完成。

#### Scenario: Remove installed research with an unfinished native root
- **WHEN** 真实安装应用已产生暂停root、唯一完成child与未确认原operation，测试进程硬停后同库启动无应用core
- **THEN** 原owner仍可读同task/run，原operation/child身份与数量不变；未观察闭合前task非终态且预算holds保留；原observer取得root native cancelled、child停止及custody FAILED/allStopped正向证据后允许task failed与allocation SETTLED，不生成科研成功或应用业务收尾/后继；core健康和资源GET成功，研究路由404，无新增应用/默认研究注册
