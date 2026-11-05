# Spec Delta

## Purpose

成员在既定资源与预算内执行独立任务；并发、撤权和不确定回执不会破坏原操作身份。该契约区分新执行的当前权限与既有操作的停止责任，避免不必要的串行限制。

## ADDED Requirements

### Requirement: Independent original operations
系统 SHALL 允许不同SSH租约独立并发，并对相同租约保持一次启动和原始绑定；已有不完整意图不得重新启动。

#### Scenario: Independent and duplicate requests
- **WHEN** 两个不同租约并发提交，且其中一个收到重复提交
- **THEN** 两个原操作均可推进，重复请求不产生第二次启动

### Requirement: Revoked execution retains original cleanup
系统 SHALL 在撤销执行绑定或禁用执行成员后继续内部清理和结算其原操作，仅使用原始目标、原始凭据版本和可信运行事实；凭据不可用不得被绕过。跨服HTTP身份不可用时，原端仍保留待核对状态，不伪造结算成功。

#### Scenario: Receiver disabled during execution
- **WHEN** 接收任务运行后成员被禁用，或原接收确认丢失后成员被禁用
- **THEN** 接收端可内部确认原停止事实并关闭原导入额度，不重提任务、不开放该成员的一般查询权限；原端HTTP通道被撤销时明确保留未结算

### Requirement: Ancestor budgets constrain descendants
系统 SHALL 在预览与创建后代时遵守所有祖先已保存的子树数量与根相对绝对深度预算，不通过更宽的根预算覆盖中间预算。

#### Scenario: Narrow intermediate allowance
- **WHEN** 根允许四个后代但中间任务只允许一个子任务，且该中间任务已创建一个
- **THEN** 预览和第二次创建均指出预算耗尽

### Requirement: Successful output is bounded ordinary data
系统 SHALL 接受预算内合法JSON业务输出，包括URL、换行、Unicode及普通业务字段；仍验证原操作身份、状态和停止证据。

#### Scenario: Report output
- **WHEN** 原操作完成并证明停止，返回包含URL和token计数的有限报告
- **THEN** 正常结算该输出；错操作身份、非法JSON、超预算或未证明停止仍不能结算为成功

### Requirement: Configured capacity and shared shutdown
系统 SHALL 接受正整数worker配置并遵守实际容量预留；两个官方服务启动入口 SHALL 使用同一既有关闭期限与失败退出语义。

#### Scenario: Operator selects eight workers
- **WHEN** 操作者配置八个worker
- **THEN** 原生队列与计划准入使用八个配置容量，不要求额外审批；零和非整数配置被拒绝

#### Scenario: Cleanup stalls
- **WHEN** 任一官方启动入口的关闭清理失败或超出既有期限
- **THEN** 服务非零退出，原操作恢复记录保留
