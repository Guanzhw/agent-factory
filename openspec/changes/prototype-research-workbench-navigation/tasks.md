# Tasks

## 1. 平台与应用导航

- [ ] 1.1 增加可选applicationView宿主slot及隔离demo composition/entry；测试默认core首页/无应用不变、AutoResearch入口清空旧项目、返回平台与history前进后退。
- [ ] 1.2 复用白名单query表达项目与页签；测试直接URL、未知项目、刷新、退出重登；记录演示登录与待集成通用SSO return的区别。

## 2. 已选视觉与合成交互

- [ ] 2.1 按测量实现三栏工作台、项目详情、团队经验及资源入口，使用许可清楚的图标/字体与synthetic图表；DOM测试覆盖选择/页签/空状态与导航。
- [ ] 2.2 实现新建项目、助手输入/引用/附件说明及可关闭弹层；测试每个核心动作的可见反馈、按owner隔离演示状态及零研究写入/模型/GPU请求。
- [ ] 2.3 完成窄屏与键盘焦点；真实浏览器验证390px无横向溢出、正常点击无遮挡、Tab/Enter/Esc与关闭后焦点返回，保存截图和console结果。

## 3. 集成与交付门槛

- [ ] 3.1 在独立core安全return修复可用后集成，验证合法深链登录返回与恶意外部地址拒绝、未安装应用回core；未具备则明确blocked而非用demo login代替。
- [ ] 3.2 运行Web/架构与相关回归、依赖审计；实际Chromium走平台→工作台→详情→平台与刷新/back/forward，保留首次失败。
- [ ] 3.3 同视口同状态比较参考与实际截图，保存design-qa.md并修复P0/P1/P2；作者之外审查完整diff/spec及精简结论，绑定精确head，重大未知不伪造通过。

## Workflow follow-up

- 本地可点击demo供用户体验；用户确认前不合并正式UI。本任务无push/merge/公开部署。
