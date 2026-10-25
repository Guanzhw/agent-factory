# Proposal

## Why
平台与可选应用共用浏览器登录，但OIDC回调固定返回首页，用户从项目深链接登录后丢失目标。

## What Changes
登录时保存根工作区的query/hash到原OIDC flow；成功完成原state后回到该目标。只接受根路径`/`，不接受外部地址、协议相对地址或认证/API路径。应用继续复用平台导航，无第二登录器。

## Capabilities
### New Capabilities
- `browser-workspace-return`: 登录中断后恢复原工作区目标。

## Impact
仅公共浏览器登录及其测试；没有OIDC配置、凭据、权限或部署变更。默认目标仍为平台首页。
