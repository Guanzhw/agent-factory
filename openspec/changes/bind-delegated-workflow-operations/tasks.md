# Tasks

## 1. 原操作适配与身份

- [ ] 1.1 实现core本地delegated-operation四方法及静态精确pin装配，记录治理函数复用原RunContext/单一custody.start；测试输入边界、相同operation唯一child、冲突拒绝及placement仍不可用。
- [ ] 1.2 实现原operation/context/parent/link/child核对和lookup只读恢复，真实PG注入create丢回执/缺link/缺child，证明lookup零create/dispatch并保持原UNKNOWN与预算。

## 2. 清理与实际等待

- [ ] 2.1 实现core窄原custody观察/取消桥接；真实PG证明成员禁用或父scope取消后原child可清理、不可新执行，交换owner/句柄被拒绝，子树停止不包含父operation且无自循环。
- [ ] 2.2 使用实际native Workflow与child测试暂停、服务重启、原requirement恢复及重复reconcile，保存实际结果进入后续模型Step的轨迹；验证父子累计预算和原operation身份，不把合成结果计为C/D通过。

## 3. 集成与独立审查

- [ ] 3.1 独立审查完整base/head diff及spec，排除第二恢复器/权限绕行/不必要抽象，整改复审；运行受影响静态、架构与串行PG检查，记录首次失败、计数、精确head、进程清理和仍未支持的远程边界。

## Workflow follow-up

- coordinator核对证据后才勾选任务并允许研究Workflow接入；当前仅规划，不代表adapter已实现或真实模型/GPU已验收。
