# Tasks

## 1. 最小方案

- [x] 1.1 协调者冻结spec、用途/兼容和验收边界，经非作者正式方案review及OpenSpec strict；修正真实问题后才派产品实现。

## 2. 普通模板路径

- [x] 2.1 后端作者完成单字段entry_kind、published模板keyset读取、自动匹配候选、Research新旧准确引用声明；只允许 `platform/agent_factory/applications.py`、`composition.py`、`applications/research/session_setup.py`、`setup.py` 与直接对应测试。验证新旧数据库加列/重启、mixed-mode精确引用保持、未发布隔离、过滤前100截断反例及旧revision跨用途标记重试/孤儿引用不阻断启动的原命令回执兼容；不改require_current权限/执行器/凭据/认证，不写分类/迁移框架。
- [ ] 2.2 前端作者完成应用到模板列表/详情/创建及必要输入、资源返回，保留接受≠启动和原请求。只允许 `web/ApplicationCatalog.tsx`及其CSS、`ApplicationComposer.tsx`、`ApplicationInputs.tsx`、`api.ts`、`models.ts`、`workspaceNavigation.ts`、`composition.tsx`、`research-composition.tsx`、`App.tsx`及一个模板临时草稿文件和直接对应tests；资源页只接现有返回接口，不改编辑主体。先跑一个测试模板完整路径，再覆盖刷新/后退/换owner/缺项/UNKNOWN/双击/旧业务seed锁定；复用现有smoke，无新表单/路由/预算引擎。

- [ ] 2.3 修复独审 TE-001/TE-002：只读复用后端匹配，先显示必填字段再预览；列表详情后退不重加当前页。仅上述既有文件与对应测试，原反例日志保留，契约小补充须非作者核对。

## 3. 整合与验收

- [ ] 3.1 非作者QA以真实PG/密码/browser完成目录与Research内部定义共存、普通模板预览→接受0任务→显式开始1任务→结果、补资源返回；1440/390实际PNG，保留错误与注入说明。脚本模型/测试seed/本地工具与外部模型分别记录；0外部GPU/SSH、Go429未解除不得探测。
- [ ] 3.2 作者外review完整base..head及可删代码/原生复用，整改后运行npm check、core/research构建、既有Chromium smoke、官方依赖audit、适用Python/PG/边界与准确head full。唯一CI/发布负责人处理门禁和main核验，作者不push/PR/dispatch。合入不等于用户部署，真实部署链并行，不等待B或全部维护页。

## Workflow follow-up

- Auto Research独立登录→资源→自由会话任务→结果/停止→重启显式继续是当前部署优先链，不被本模板片阻断。真实账号/模型整链和可达部署环境由协调者推进。
- 后续B：作者复制/草稿续编/发布（含V2通用元数据编辑）；随后按实际问题整理资源工具/凭据内页、共享材料、存储和历史/账号，不能声称仅外壳已全站完成。
