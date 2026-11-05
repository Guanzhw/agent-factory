# Proposal

## Why

普通成员的通用装配目录混入 Research 内部运行定义，实际手机页面要求手填 sessionId/turnId/sessionContext；从模板到填写目标也没有独立入口。修复这个日常路径，而不等待作者工具或全站维护页重做。Auto Research 的独立主页、研究会话与运行路径已经存在，不受通用模板缺口整体阻塞。

## What Changes

- 应用页增加任务模板入口；只列明确供普通创建的已发布模板，提供详情、必要输入与资源补齐返回。
- 用一个治理字段声明默认入口用途，Research 创建及其持有的旧准确版本明确归应用入口；原精确引用执行、既有草稿/历史和混合mode高级用法不被封禁。
- 增加只读模板分页，先按已发布/非历史bootstrap/用途过滤，再稳定分页，自动匹配复用完整候选而不被前100项截断。
- 复用现有提案/方案/启动/原请求；固定模板版本仍可写本次目标，来源快照继续锁定；接受与启动保持独立动作。

## Capabilities

### New Capabilities
- `member-template-entry`: 普通成员识别、选择与使用任务模板，保留应用入口、权限、精确版本和创建恢复。

### Modified Capabilities

无已发布 spec（当前 inventory 为空）；既有应用、Research和提案接口行为按 design 保留。

## Impact

基线 main `b6c383a5c5543fd0cf7d8c08c043ee8ad0f69abe`，独立分支 `feat/template-task-entry-20261029`。只改模板目录、Composer/必要导航与草稿、一个治理字段及 Research 创建声明/旧精确引用标注和对应测试。Agno固定3.1.0，不改执行引擎/认证/角色/凭据。作者复制编辑B、v2可视化编辑、资源长表单和维护页后置；不合并旧dirty UI或旧候选。首轮证据为隔离PG/真实密码/API/浏览器，脚本执行与外部模型证据分开；Go通道429暂停，不新调用或收费回退。
