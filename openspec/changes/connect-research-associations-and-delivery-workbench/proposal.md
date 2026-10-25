# Proposal

## Why

已确认工作台已接真实项目与私密问答，但尚未接主动关联与精选成果。新后端撤权投影会省略目标/实验正文，现界面直接读取这些字段会崩溃；目标修订还会丢失新evidence选择，必须在接线时保持原授权与出处。

## What Changes

- 接入明确有界关联配置、真实关联列表及当前授权来源，沿用已批准布局与core内容读取。
- 在目标约定中选择并保留精准CLI材料及有限输出字段，呈现真实成果manifest、缺项与下载；不假造可复现性。
- 明确来源不可用联合类型与原运行身份，保留目标版本、原预算/执行配置和原请求恢复；不将修订或取消接纳当停止证明。

## Capabilities

### New Capabilities
- `research-evidence-workbench`: 已确认工作台中的关联出处、精选证据约定、成果交付及撤权呈现。

### Modified Capabilities

无已归档能力修改。本change是进行中的`associate-research-evidence`和`deliver-selected-research-evidence`的前端消费者，补充`connect-research-assistant-workbench`，不重定义其后端执行/分享策略。

## Impact

UI基线`3e7e660`；只读核对P7 `f848c6a`、P8 `210810f`，两者仍在整改，最终接口须由coordinator冻结后实施。范围为`web/apps/research`、研究composition参数与必要前端测试/浏览器脚本；不改核心首页/认证，不增加依赖、控制器或凭据。当前仅规范本地提交；生产代码与PG验证未开始。真实模型/GPU/科学价值不由本change的合成验收替代。
