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
