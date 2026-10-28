# Spec Delta

## Purpose

让成员选择的个人模型在部署已配置的执行期限内完成正常响应，并准确区分调用取消、超时及提供方结果未知。该约束支持持续研究和代码任务，不以额外的隐含短期限截断仍可继续的请求。

## ADDED Requirements

### Requirement: Model requests use the configured execution lifetime

系统 SHALL 用部署已有的原生执行时限作为每次个人模型 HTTP 请求的总时限，不附加独立的 10 秒或 30 秒短期限。更早发生的原生异步任务取消仍 SHALL 生效。

#### Scenario: Slow valid response
- **WHEN** 已配置执行时限足够，提供方 31 秒后给出有效响应，期间没有取消
- **THEN** 请求成功返回，后续工具循环可以继续，不因旧 30 秒期限终止

#### Scenario: Request expires without a response
- **WHEN** 本次请求到达配置时限且没有可用响应
- **THEN** 本地调用有界结束并保留既有脱敏错误，不自动重试，不断言提供方未执行

#### Scenario: Native asynchronous cancellation occurs first
- **WHEN** 原生任务先取消正在等待的异步请求
- **THEN** 取消向请求传播，不转换成一次新的请求或普通提供方错误

### Requirement: Synchronous auxiliary requests remain bounded

系统 SHALL 为同步摘要等辅助模型调用保留同一有限请求时限，不将外层原生任务退出等同于同步线程或提供方立即停止。晚回复 SHALL 继续遵守既有原任务与摘要 claim 核验，结果未知时不得自动重放。

#### Scenario: Outer task ends while a summary request waits
- **WHEN** 外层任务已结束但同步辅助请求线程仍等待响应
- **THEN** 辅助请求至多等待其自身请求期限，晚回复不能把已失效的原摘要 claim 更新为成功
