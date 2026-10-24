# Tasks

## 1. Baseline

- [ ] 1.1 保存未清理提交完整 CI 的原始日志、环境、成功/跳过 ID 与阶段耗时，核对 head 和 full 模式。
- [x] 1.2 为候选测试建立删除、替代与保留映射，并以定向基线结果确认实际观察边界。

## 2. Behavior tests and dependencies

- [x] 2.1 连接 PubMed transport，收敛诊断和描述符镜像，替代锁身份断言；运行定向回归和有效反例。
- [x] 2.2 将 composer 序列化断言改为 DOM 行为，删除重复源码扫描并保留唯一依赖规则；运行 checker 正反例与 Web 回归。
- [x] 2.3 更新受影响开发依赖和 lock，取得生产/完整审计及 Node 24 下类型、构建和测试结果。
- [x] 2.4 修复基线 Windows 隔离安装与并发 MCP 夹具失败，保留原始重现、针对性验证和独立复核。

## 3. CI and browser

- [ ] 3.1 证明保留的普通成功用例由完整 PG 执行覆盖，消除 full Linux 重复行为执行并运行路由/汇总回归。
- [x] 3.2 加入锁定 Chromium 的两个短流程，真实运行并确认缺依赖、构建和无有效场景会失败。
- [x] 3.3 更新开发命令、覆盖边界和计划状态，核对文档命令可运行。

## 4. Integration and review

- [ ] 4.1 在最终代码提交执行完整 Linux PG/required、独立核心、Windows 与 Web/浏览器 CI，保留失败和跳过事实。
- [ ] 4.2 对照前后成功 ID、执行次数、阶段耗时与 runner 用时，解释测试增减和覆盖保留。
- [ ] 4.3 完成独立审查并关闭具体发现；主代理检查最终 diff、OpenSpec strict 和全部证据。
- [ ] 4.4 将 PR96 更新为最终实现说明，在精确 head CI 通过后合入并核验 main。
