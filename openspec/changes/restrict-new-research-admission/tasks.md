# Tasks

## 1. 独立方案与依赖

- [ ] 1.1 提交 spec-only SHA，经作者外方案 review PASS；记录新/旧请求判别及原 pin 边界。
- [ ] 1.2 等协调者整合 R1 已审实现为精确新 base，作者与 reviewer 核对 R1 触及 rounds/public 的增量后再实施。

## 2. 单一新准入与历史恢复

- [ ] 2.1 先补公开新误选模式、无 Workflow fresh、旧命令升级后恢复、同键冲突的失败回归，保留首失败日志。
- [ ] 2.2 实现持久命令优先路由、历史原 intent-only 恢复与当前 pin 新准入；以便携/真实 PG 验证新请求零分配/dispatch，原 UNKNOWN/reserved/history/end 不增派、不换 pin，原 scope 取消仍有效。
- [ ] 2.3 用显式历史 fixture 保留原 owner/请求/预算/取消测试；新准入与事务回滚由 rounds 路径验证，不降低原断言或把缺失旧 executor 说成已兼容。

## 3. 配置选择与最终验证

- [ ] 3.1 ExecutionEditor 使用现有候选 workflowPin 过滤当前应用/mode并显示不兼容原因；UI 回归验证 research/experiment/错误 sha 和已有旧选择，不自动代选。
- [ ] 3.2 运行受影响 Python、UI、静态/边界与 npm check/audit，预约串行 PG；记录精确 base/head、首失败/修后及真实旧 paused/外部运行未验边界，经作者外完整 diff/简洁性复审，主代理核验后勾选。
