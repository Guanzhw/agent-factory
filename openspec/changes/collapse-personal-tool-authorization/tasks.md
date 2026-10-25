## 1. Implementation

- [ ] 1.1 coordinator装配可信ExecutionBindings guard方法。
- [ ] 1.2 工具callback合并执行guard并保持捕获plan及retained身份。
- [ ] 1.3 便携测试覆盖重复消除、缺失/替换guard、原plan和跨callback/credential撤权。

## 2. Verification

- [ ] 2.1 运行便携回归及静态检查，保留失败证据。
- [ ] 2.2 串行运行原两项PG用例，保留原断言/期限与首次失败。
- [ ] 2.3 coordinator独立精简review并确认适用验收；不以单例通过关闭历史问题。

- [ ] 2.4 核对共享Store fixture全部消费者（adapter integration/member resources），统一原plan与实际tool name登记；完整模块保留撤权/凭据隔离断言。
