# Tasks

实现尚未开始。主代理核对源码和验证回执后才勾选；下列 ownership 为派发边界，重叠文件须串行交接。无 #97/#99 前置依赖。

## 1. 操作与独立账号（core/API owner：主代理）

- [ ] 1.1 在 `platform/agent_factory/personal_tools.py` 及新增 app-independent operation 模块实现不可变操作表、完整 recipe hash 和幂等创建/读取 API；在 `platform/tests/test_member_tool_resources.py` 和新增 operation tests 验证每个配方字段变化、非法输入、幂等冲突及旧资源不自动公开，补计划中的 API 说明。
- [ ] 1.2 同 owner 实现账号创建、投影、共享和撤销；复用 `connections.py` 精确 adapter 检查，验证 Alice/Bob/第二账号引用同一操作，撤销 Alice 不影响 Bob、错误版本/hash 业务 dispatch 为零；测试归 `test_personal_tools.py`、`test_resource_sharing.py` 及新增 operation tests。
- [ ] 1.3 同 owner 负责 `personal_tool_execution.py` 与恢复装配，操作先恢复并保持唯一 adapter 对象，新路径绑定完整 operationHash，旧 fingerprint 不变；`test_personal_tool_execution.py`、`test_personal_tool_assembly.py` 验证双账号对象一致、篡改/缺失操作失败、旧 plan/effect 连续性与材料即时撤销。

## 2. 操作选择与真实工作流（依赖阶段 1 接口）

- [ ] 2.1 UI owner 独占 `web/PersonalToolConnections.tsx`、`web/personalToolConnectionApi.ts` 及对应 UI tests，接公开配方创建和账号连接入口，复用材料发布/任务选择；通过浏览器验收公开预览、个人/共享选择和错误显示，补用户说明；不得自动带入旧私有参数。
- [ ] 2.2 集成测试 owner 独占新增 `platform/tests/test_reusable_tool_operations_postgres.py`、本地合成 CLI/MCP fixture 及必要 `test_personal_tool_native_postgres.py`，从正常认证 API 提交真实 native 多步/支持的 child 工作流；同材料 id/version/hash 下验证 Alice/Bob 独立账号、第二账号及显式共享身份，不以 resolver 直接调用代替。
- [ ] 2.3 同测试 owner 在真实 PG/native 进程重启及确认丢失处验证操作先恢复、原连接延续、completed 不重放、UNKNOWN 原 call identity 与业务计数不增加；两步之间撤销共享/凭据/材料及禁用 actor 均无下一次 dispatch，检查合成秘密及共享 credential ref/revision 不出现在模型输入、投影、错误或日志。
- [ ] 2.4 主代理串行运行上述 PG/native/browser 集成、`npm run check`、相关依赖审计与独立 core/架构检查，记录实际结果及未验证范围到既有计划；独立 reviewer 对精确 adapter/object guard、配方 hash 完整性与旧效果身份复查后才更新验收状态。
