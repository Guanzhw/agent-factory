# Verification

基线 `db6d62a4880466f3bf50879809e2339e57cf8a44`；方案提交 `1bb109819625bb3a5b476105ed00e5fe0118d052` 经主代理非作者审查后实施。2026-11-05 使用 Node 24.19.0，复用已安装依赖，不修改 package.json 或 lockfile。

## Behavior

两项预设只更新新选择时填入的值。DeepSeek 保留原 preset ID，改为 V4.1 模型和显示名；GPT 6 Luna 保持 Responses。删除无消费者的 GO_BASES，保留 LEGACY_GO_BASE 与 Longcat thinking 条件。独立 UI 期望校验表单和完整配置请求；旧 Go 输出调整及原请求恢复保留旧配置。

## Executed

- `npm test -- --run tests/owner-model-settings.test.ts`：43/43 通过。
- `npm run check`：lint、typecheck、60 个测试文件 / 646 项测试和生产构建通过。构建保留 >500 kB chunk 警告；日志 `/tmp/go-presets-npm-check.log`。
- `npm audit --omit=dev --audit-level=moderate --registry=https://registry.npmjs.org --cache=/workspace/.npm-cache`：0 漏洞，通过。
- 对应完整 `npm audit`：失败，既有锁定 minimatch 10.2.6 经 ESLint / TypeScript ESLint 链共 10 项 moderate，关联 [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249)。未静默放宽门槛或自动修改依赖；原始 JSON 保存到 `/tmp/go-presets-audit-full.json`，交主代理处理独立修复范围。
- `openspec validate refresh-go-model-presets --strict` 与 `git diff --check`：通过。按小变更跳过可选 design；apply 状态 ready，任务待主代理最终源码与回执验收后勾选。
- Python Playwright + `/usr/bin/chromium`：基于本次构建及既有 browser smoke 合成 API/静态服务辅助工具，两个预设选择与保存、旧 Go 输出调整 lost-ack/刷新/原请求恢复共 3 场景通过；页面错误、非预期 console 错误、外部请求和模型调用均为 0，无水平溢出。临时脚本 `/tmp/go-presets-browser.py`，结果及截图 `/tmp/go-presets-browser/`。

首次浏览器尝试因临时脚本选择了两个并存的 status 元素失败，保留 `gpt-luna-failure.json/png`；收窄到成功提示后通过，未因此改产品代码。

## Unverified

官方 Go 文档只读核验了当前模型 ID 与协议路径，未读取密钥或发真实 Go 请求；未执行 PostgreSQL、真实模型/远程集成、AutoResearch 或部署验证。完整依赖 audit 仍失败，不构成全部门禁通过。无 push、PR、Ready、merge、Approve 或 workflow dispatch。
