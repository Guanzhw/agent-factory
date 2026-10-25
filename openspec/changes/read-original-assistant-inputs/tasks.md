## 1. Implementation

- [ ] 1.1 coordinator审阅原身份读取、锁/权限与深度判断后实施只读port。
- [ ] 1.2 移除固定深度上限并保留已有传播和预算约束。
- [ ] 1.3 在已有error列统一记录安全code或异常类型。

## 2. Verification

- [ ] 2.3 Add the original-event status projection for the concrete research successor consumer; verify rejected-before-task visibility, owner isolation and no execution side effects.

- [ ] 2.1 便携测试原绑定/权限/深度/code，记录首次结果；不把mock当PG证明。
- [ ] 2.2 经协调安排串行PG原绑定测试，独立完整diff精简审查后冻结。
