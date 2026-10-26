## Purpose

落实产品仅使用显式配置身份与运行资源的既有边界，使安装包、现行指南和任务展示不提供可启用的合成模式，同时保留隔离测试与历史证据的准确来源。

## ADDED Requirements

### Requirement: Test transport is excluded from product distribution
产品分发 SHALL 不包含仅供合成验收的 loopback 模型 transport；测试 SHALL 通过显式测试 helper 保持原 wire 与资源清理契约。

#### Scenario: Installed core with real model adapter
- **WHEN** 独立构建并导入 core wheel
- **THEN** 正式模型适配器和通用 transport 注入保持可用，合成 loopback transport 不在产品包中，产品不依赖测试模块

#### Scenario: Explicit loopback acceptance
- **WHEN** 隔离测试显式使用本机 HTTP peer
- **THEN** 原协议、端点限制和正常/异常清理保持；peer 不接收 Authorization，观测只保留是否存在的布尔值

### Requirement: Current guidance and task labels reflect configured execution
现行指南及任务页 SHALL 描述实际配置与证据，MUST NOT 宣称默认 demo 登录、模型或种子；历史验收 SHALL 保留且标明退役入口。

#### Scenario: Current deployment and task inspection
- **WHEN** 成员阅读部署指南或查看任务
- **THEN** 指南说明显式身份/应用/资源配置，任务保留实际 source、evidenceKind、validationStatus 与指标，不从旧 demo runtime 标签推断证据或已验证结论
