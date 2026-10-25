# Proposal

## Why

长期成员助手需要跨任务的稳定地址，其他成员才能发送请求并观察原收据。现有应用runtime owner、task事件和composition inbox都不提供该语义；不得为此再建执行/恢复控制链。

## What Changes

- 成员配置持久助手端点，固定已发布应用版本、mode与资源引用；owner管理启停，团队只发现非秘密摘要。
- 发送者提交有限文本消息，接收者端点配置决定执行；消息幂等键关联既有ApplicationRuns请求，失联只查原身份。
- 投递读取与执行状态分离，收件者离线不要求浏览器在线；当前成员/端点权限在准入重新检查。
- 首单元只交付P1端点与测试，第二单元实现P2消息准入；P3订阅/预算、限定证据共享、研究应用在其各自spec完成后实施。

## Capabilities

### New Capabilities

- `member-assistant-messaging`: 成员拥有的助手身份、固定配置、消息收据与原任务关联。

### Modified Capabilities

无；本仓库尚无主spec，既有实现与验收契约保持不变。

## Impact

基线PR104 ddc82b2642e8784099e5590040ef7d4223df18b1；本地计划91cb2a83。涉及core新助手/消息服务、main显式路由接入及专属测试，不增加依赖、模型调用或研究schema。验收A02/A03/A05和无app启动A01；真实问答C03仍需真实模型冻结参数。
