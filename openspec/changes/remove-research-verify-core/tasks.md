# Tasks

## 1. Ownership and dependency audit
- [x] 1.1 root：冻结 main 基线、保留旧数据清单，核对源码/部署/登录和主页依赖。
- [x] 1.2 test worker：分类 Research-only 与通用测试依赖，提出保留/迁移/删除对应表。

## 2. Remove retired application
- [x] 2.1 root：删除 tracked Research 源码、专属材料/工具脚本；整合通用 core 交界，源码改动不删除旧数据；独立清单已获即时确认并完成精确删除。
- [x] 2.2 deployment worker：移除默认装配与专属打包依赖，保持正常 CLI 启停和独立 core。
- [x] 2.3 frontend worker：移除旧页面/注册/导航，修复登录后通用主页与空状态，无新设计。
- [x] 2.4 test worker/root：迁移通用测试夹具，删除仅属旧应用的测试，更新发现与 required 选择。

## 3. Acceptance
- [x] 3.1 root：冻结依赖、静态/架构/Web/审计检查及独立 core 安装启动干净关闭。
- [ ] 3.2 root：新隔离空 PG 的通用套件与初始化/seed/身份/资源验证；保留失败及跳过原因。
- [x] 3.3 root：实际浏览器 demo 和生产模式合成身份登录、主页、导航、资源、退出重登、直接 URL/刷新/旧地址，保存截图。
- [x] 3.4 reviewer：独立审查应用移除完整性、通用能力回归和数据不删除边界。

## 4. Delivery
- [ ] 4.1 root：记录覆盖对应与限制，扫描提交推送独立 Draft PR，跟进精确 CI。
- [ ] 4.2 root：清理本轮临时进程，报告已确认旧数据删除结果与保留项；不合并新 Draft、不部署、不实现新 AutoResearch。
