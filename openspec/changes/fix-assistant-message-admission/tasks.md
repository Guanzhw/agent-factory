# Tasks

## 1. 方案独立审查

- [x] 1.1 提交 spec-only SHA，经作者外方案审查 PASS 后实现；review 记录精确 base/head。

## 2. 容量与共同准入修复

- [x] 2.1 增加 C2/C3 失败回归并保留基线失败输出，覆盖容量恢复原身份、无预算撤权与指纹、原 UNKNOWN 不重派。
- [x] 2.2 修改 Store 精确容量错误分类及 AssistantEvents pending 行为；真实 PostgreSQL 容量释放后原 allocation/request 形成唯一 task/native dispatch。
- [x] 2.3 统一 AssistantMessages fresh gate；验证无预算 sender/endpoint 禁用和原指纹拒绝，已有 task 仍只观察。

## 3. 集成与独立验收

- [x] 3.1 运行 Python 静态、相关便携与 PostgreSQL 回归及仓库要求检查，记录首失败、修后结果和未验边界。
- [x] 3.2 作者外交叉复核精确最终 base/head 的完整 diff 与职责简洁性；主代理核对源码和回执后更新任务状态。
