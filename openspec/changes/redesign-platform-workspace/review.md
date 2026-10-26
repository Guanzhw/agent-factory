# Review

## 方案独立审查

**PASS，无必修设计问题。** 非作者审查范围为本 change 的 proposal、design、tasks、spec 与 `.openspec.yaml`；调查源码基线为 `768e4adcb0e218f9ec27b81e5627db1fb3f21034`。已直接查看选定原图，独立核验其 SHA-256 与 design 记录一致。本次未修改产品或规范任务状态。

- **真实数据与范围可实现。** `factory_api.py:401` 的任务列表按当前成员查询；`App.tsx:139` 已提供独立读取、旧记录保留和刷新，首页可直接复用。`composition.tsx:21` 默认无应用，`research-composition.tsx:7` 显式安装 AutoResearch，目录不必新增后端接口或假数据。
- **资源摘要语义一致。** `personal_models.py:67` 区分模型启用与凭据保险库启用，`:96` 区分默认选择与当前可用性；必须按已有字段呈现实际默认模型。`personal_ssh.py:264` 区分登记、连接启用与执行授权，`:400` 的能力检查可决定是否读取列表。规范没有把保存、登记或列表成功当作运行验证。
- **导航与恢复有现成边界。** `workspaceNavigation.ts:20` 已校验来源、账号权限和应用指针；`research-composition.tsx:15` 可在现有导航回调补任务来源，通用组件无需依赖 Research。`CredentialForm.tsx:6`、`:31` 保留 owner 范围的原凭据请求并只读取其回执；模型、SSH、工具等也有原恢复路径。分类实现仍需验证面板挂载变化不隐藏或丢失恢复能力，现有 design/tasks 已明确覆盖。
- **验收与简洁性适当。** 原图层级、手机导航、配置字段、权限、失败/陈旧状态、来源往返与 Research 样式隔离均有明确场景；保留现有 React、API、路由和恢复机制，不增加新框架、通用引擎或后端契约。现有全局 CSS 同时被 Research 使用，实施时按限定作用域与同视口截图要求核验即可。

独立执行 `OPENSPEC_TELEMETRY=0 node /workspace/design-audit/openspec-cli/node_modules/@fission-ai/openspec/bin/openspec.js validate redesign-platform-workspace --strict`：PASS。规范文件 whitespace 检查：PASS。未运行产品测试、PostgreSQL、浏览器或外部模型；这些属于后续实施验收。

本结论仅批准方案。`tasks.md:5` 的最终登录 main 基线前置保持有效；完整实现 diff、整改复审、真实浏览器以及精确 PR head/main CI 尚待执行。

## 原凭据离页恢复增量审查

**PASS，无必修项。** 审查 `d9fbd7b4725a2ed567073d99155c65fe3e1b2bd5` 上的 design 决策 3 与 spec「远端凭据原请求离页恢复」增量。`PersonalRemotes.tsx:12`、`:14` 的目标与表单开关重挂后为空，`:88`、`:93` 又使原表单依赖可用提供方与有效目标；因此已有 opaque 标识虽然没有丢失，直接恢复入口会消失。新增入口是满足离页/刷新可恢复性所需的局部前端修正，范围适当。

现有 `CredentialForm.tsx:31` 已显式调用 `recoverCredential(requestId, owner)`，`:11` 在恢复时从成功回执接受真实目标；`credential_vault.py:188` 按 owner 与 request ID 读取既有结果，`:392` 为 GET 路由。复用此路径无需保存目标、秘密或新建恢复机制。实施时入口应独立于新配置表单的 `eligible`/提供方加载条件，未知或失败仍保留原标识；不得因显示入口而自动 GET/POST，成功读取后也不自动配置远端。

已独立重跑 OpenSpec strict 与 `git diff --check`：PASS。本增量没有产品修改；既有最终登录 main 前置与后续实现验收仍有效。

## 实施独立审查

**初审待整改，尚非最终 PASS。** 非作者以 `3ec76ad34a97c3803933df646fd30966d4019024` 为产品基线，审查当前累计产品、测试、公开文档及未跟踪新增文件，直接查看选定方案 1 原图。当前实现仍在补充测试与验收；最终结论须复核冻结 tree、整改增量及浏览器证据。

初审必修项：

1. `web/composition.tsx` 的 `onModels` 在直接打开 `?tab=models`、没有 `modelReturn` 时，点击当前“模型”分类会补 `modelReturn=resources` 并新增同页历史。当前页动作应保持原路由和返回语义，补充此深链接重复点击测试。
2. `platform/tests/browser/personal_tools_smoke.py` 的移动场景仍直接点击默认隐藏的“我的资源”。新导航在 390px 先需展开菜单；修正真实操作步骤并保留全部移动场景。

已核对：登录/会话函数与协议未改；普通成员账号入口及路由归一保留；首页沿用 owner 范围只读模型/SSH接口和原任务记录，未造个人 KPI；模型禁用与无保险库的无认证配置区分；摘要取消旧读取并保留失败/陈旧语义；资源用途、可信绑定/引用/租约入口完整；原远端凭据恢复仅使用 owner 范围 opaque 请求标识、显式 GET，不恢复秘密或自动配置。新增样式限 `.factory-shell`，Research 业务目录未改，未引入框架、通用恢复引擎或重复兼容层。上述是源码审查结果，不等同于浏览器或外部服务验证。

仍待复核：最终累计测试/文档增量、全套检查和审计结果、真实密码登录与保存/失败/恢复/退出、320px 与 Research 同视口回归。没有真实截图证据前不宣称视觉 PASS。

首轮整改复核：`onModels` 已对当前模型页直接返回，新增直达无 `modelReturn` 连续点击测试；移动 smoke 已先展开导航，默认八场景及三个手机场景保留。独立运行 `workspace-home`、`resource-workspace`、`workspace-shell-navigation`、`personal-remotes`、`personal-ssh`、`core-workspace` 六个测试文件，**66/66 通过**；`git diff --check` 通过。两个初审问题源码已修复，尚待最终验收与冻结 tree 复审。高级页面深链接时折叠的“更多”已有 `aria-current="page"`，展开后显示精确子项，无需增加导航状态或自动展开机制。

产品冻结增量 `5a3c11b60be4900f1c5b1fbeb8304697f7d7f82f` 源码复核：**PASS，无必修代码问题。** `f15435c` 后的字体、尺度、对比度及 D04 占位说明修正均直接调整原规则并限定底座作用域；D05 模型反馈只在显式提交/原操作结果后聚焦并滚入现有状态容器，首次读取不抢焦点，同一校验错误可重复揭示，未改原锁、owner 核对、请求身份或凭据存储。独立重跑模型设置与原请求恢复两个测试文件，**52/52 通过**，whitespace 检查通过。登录函数块仍与最终 main 基线逐字相同，Research 业务、后端及依赖文件无累计修改。此处只关闭产品代码审查；真实视口中的反馈、最终视觉 QA、验收和发布文档仍待各自证据，不将单测通过作为安全或视觉推断。

### 最终累计复审

**PASS，无剩余必修项。** 范围为最终登录 main `3ec76ad34a97c3803933df646fd30966d4019024` 至冻结产品 `5a3c11b60be4900f1c5b1fbeb8304697f7d7f82f` 的全部累计产品、测试、浏览器脚本和公开文档，以及本轮最终 design、tasks、verification、review 与新增 `design-qa.md`。已复核全部整改；冻结后 `web/`、测试和依赖文件无增量。当前两处初审问题与视觉报告 D01–D05 均已关闭。最终文档提交后仅需核对其 SHA 与已审内容一致，不重新开放产品范围。

- **职责与简洁性。** 首页使用真实 capability/list 与本人任务，默认/禁用/失败/陈旧状态分开；资源所有分类和原请求恢复入口保留，来源与历史导航保持，账号入口仍受原角色限制。没有新框架、后端接口、权限系统、凭据存储或通用恢复引擎；局部样式直接替换原声明。独立再次比对登录函数逐字一致，Research 业务目录、认证/API、后端和部署模块无累计差异。
- **验收证据。** 已逐项读取最终 `npm run check` 的 56 文件/526 测试、lint/typecheck/core build、Research build、两组零漏洞 audit、11 架构 fixture/103 modules 零违规以及八场景（含三个手机场景）合成 smoke 记录。真实结果 JSON 确认无效和断网提交零配置写入、双击保存仅一次 configure/一次 default、退出204及刷新401/真实密码重登、保存后本人默认模型仍存在、320px反馈在1px亚像素容差内。只读数据库记录为零任务/零运行。本人没有运行浏览器；视觉结论引用非作者 `design-qa.md` 的最终 passed 与其已查看的真实截图，未将组件测试代替浏览器证据。
- **文档与交付界限。** 两个指定技能记录固定官方源码版本、实际读取的原则和未安装/未执行脚本；Impeccable 名称已与来源记录的 operate/shape/distill/clarify 对齐。真实 API、合成 fixture 和未验证的外部模型/SSH/研究执行明确区分；没有把 loopback、自签名服务或静态预览称作用户可访问部署。失败与整改保留，历史 MCP late 超时根因仍明确未知。发布、精确 head/main CI、截图交付和隔离环境清理仍由后续发布回执完成，当前未冒称已合入或部署。

本审查仅编辑本文件的实施段，未修改产品或测试、未勾选任务。最终 whitespace 检查通过。
