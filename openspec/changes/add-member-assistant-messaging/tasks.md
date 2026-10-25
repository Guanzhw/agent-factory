# Tasks

## 1. P1 成员助手端点

- [x] 1.1 assistant_endpoints实现固定配置/owner启停/团队摘要及专属tests；验证重启同身份、幂等冲突、禁用和无秘密摘要（A02/A03）。
- [x] 1.2 root集成main路由与服务；真实PG/HTTP验证无app仍启动，published pin/mode撤回后拒绝，更新API文档（A01/A02）。
- [x] 1.3 作者之外review完整base/head diff含spec并整改复审；保存精确检查证据，不能把端点pass当完整协作pass。

## 2. P2 消息与原执行准入

- [x] 2.1 消息保存/有限文本/双方读取/同键冲突与当前端点权限；专属契约tests证明无owner/config覆盖、第三方拒绝（A02/A03）。
- [x] 2.2 原ApplicationRuns准入与receipt投影；真实PG/native验证并发重投、丢回执/重启后同task且dispatch一次、离线浏览器不影响入队（A03/A05机制范围）。
- [ ] 2.3 作者之外完整diff精简review、必要整改复审，串行相关回归/独立core；记录C03真实模型未运行及P3预算/唤醒缺口。

## Workflow follow-up

- 后续变更先建spec：P3事件订阅/自动消息预算；P6限定内容共享；P4–P8研究项目和协作应用；P9综合17项验收。完整旅程不削减，真实C/D参数不虚构。
