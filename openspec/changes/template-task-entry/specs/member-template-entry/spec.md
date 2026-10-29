# Spec Delta

## Purpose

让普通成员从明确用途的已发布任务模板填写本次目标并核对后启动，避免手填应用内部运行标识；同时保留独立应用、精确版本、原请求恢复和所有权边界，不把模板入口作为独立研究工作的前置条件。

## ADDED Requirements

### Requirement: Explicit template entry
系统 SHALL 依据生产者明确的入口用途展示普通任务模板，不按名称、输入schema、native类型或bootstrap猜测。入口用途 MUST 与执行权限、资源就绪及不可变正文分开。

#### Scenario: Research definitions coexist with ordinary templates
- **WHEN** 目录有普通模板、Research自动生成的会话定义和research/experiment混合定义
- **THEN** 普通入口仅展示明确的任务模板，内部标识不作为普通必填项，原应用及高级准确引用路径仍可使用原版本，不改正文/hash或任务

#### Scenario: Existing Research configurations survive restart
- **WHEN** 已有Research精确配置在加列后重启
- **THEN** 仅由其所属应用标注默认入口，重启不产生新版本或任务，原准确版本和原操作仍可核对

### Requirement: Complete published template browsing
系统 SHALL 在已发布、可作为模板入口的范围内分页，且让成员读取100项之外的准确版本；未发布他人草稿不得进入目录。没有模板与读取失败 MUST 呈现不同状态及实际下一步。

#### Scenario: Unrelated versions do not consume the first page
- **WHEN** 存在超过100个无关草稿、多个谱系和同谱系超过100个版本
- **THEN** 分页仍能到达每个符合条件的已发布模板，自动匹配不被无关草稿遮挡；撤回版本不能借旧目录绕过创建前检查

#### Scenario: Empty and failed catalog
- **WHEN** 目录确实为空或读取失败
- **THEN** 空态提供返回已安装应用和现有作者入口，失败提供重读；不造内置假模板或暗示Auto Research不能工作

### Requirement: Necessary task inputs and resource return
系统 SHALL 让普通模板固定版本但保持本次目标可编辑，只要求该模式真正必要的输入/本人资源；原应用来源固定目标 MUST 保持原约束。补资源后应回到同一次未提交任务。

#### Scenario: Create from one-mode template
- **WHEN** 成员从准确模板版本进入创建
- **THEN** 可以填目标且无需重复选择唯一mode，原材料默认保留，高级范围仍可查看，字段错误在对应输入附近

#### Scenario: Missing resource and return
- **WHEN** 成员带着未提交目标进入已有资源页并返回
- **THEN** 同owner目标/输入恢复，连接重新读取；未保存刷新明确提示可能丢失，已提交提案可按原记录恢复，退出换人不能读取前一人的草稿

#### Scenario: Source-bound request stays fixed
- **WHEN** 原业务来源携带固定快照进入创建
- **THEN** 不能借普通模板可编辑目标绕过来源约束，不猜Research session或project返回地址

### Requirement: Preview acceptance and start remain separate
系统 SHALL 复用现有提案、固定方案和任务动作；预览与接受均不得自动启动。重复输入 MUST 保持原命令身份，UNKNOWN不得变成新请求。

#### Scenario: Accept is not start
- **WHEN** 用户预览后接受方案，包括快速重复点击/按键
- **THEN** 只获得同一固定方案且任务数仍为0；另一次明确开始最多创建同一任务；remote目标仍不能设置本地计划

#### Scenario: Recover original operation and active proposal
- **WHEN** 预览/接受/启动回执丢失或成员返回活跃创建记录
- **THEN** 核对同一原请求/提案/方案，不静默重放未知副作用；允许动作、拒绝/修订、原版本及资源检查保持

#### Scenario: Automatic matching is preserved
- **WHEN** 用户不显式选择模板
- **THEN** 只匹配普通模板入口，保留既有关键词评分及ID同分顺序；无命中且没有唯一默认项才要求明确选择
