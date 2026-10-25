# Proposal

## Why

用户已选择方案2「研究工作台」，需要先用可点击演示确认平台首页到研究应用的体验，再决定正式UI。当前研究页面复用了平台壳，不能直接表达已选三栏工作台；平台本身仍须有独立主页。

## What Changes

- 在隔离分支提供明确标注合成数据的研究工作台demo：项目概览、项目详情、团队经验、资源说明和助手对话交互。
- 保留平台首页，增加明确的AutoResearch进入/返回路径；复用现有登录与history导航，不建立第二认证或路由控制链。
- 基于1487×1058已选图还原布局、文字层次和图标，并验证窄屏与键盘操作。
- 只演示本地状态，不连接研究后端写入、模型、GPU或真实协作；正式UI合并仍等待用户体验确认。

## Capabilities

### New Capabilities

- `research-workbench-prototype`: 平台和研究工作台之间可返回、可直接定位且明确为演示的完整交互原型。

### Modified Capabilities

无。通用安全登录return由独立core变更负责，本demo消费其结果，不在应用复制认证实现。

## Impact

基线f25c8992f5c286db3cca3554e3c74a255dfe9f82，分支demo/research-workbench-20261025。预计新增web/apps/research-demo、显式demo composition/entry、Vite demo mode、针对性测试；App.tsx仅加入可选应用壳slot，默认平台行为不变。不push、不合并、不公网部署、不新增凭据；无数据迁移。
