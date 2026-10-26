# Verification

## 精确范围

- 已审 R1 依赖/base：`e4afcb6eb230ad079f13ac87dc5e3d581701b390`。
- R4 spec-only：`00e32d01cb08758fd54138049b79a4ef64849984`；与原已审 `57ddd10f88289efdaa6b0f3185c57c5035f99b30` 的 change subtree 相同，独立 reviewer 已确认 R1 增量适用。
- 首失败回归提交：`67574c82597ac5b998f538c283648287253667e9`；产品仍为上述 base。
- 产品/测试实现：`93064bc6b2926ed8e4c3c67705ea2c1736a0f237`。R4 不改 R1 完成/发布方法、旧基线 pin 的 finalization-only 注册或 Workflow 实现。
- 独立审查记录由 reviewer 维护；作者不勾 tasks，不把本地通过视为发布许可或整套 release 验收。

证据目录：`/workspace/agent-factory-fix-research-admission-v2-evidence/`。只有合成 fixture；未使用真实凭据、付费模型或远程 GPU。

## 首失败与修正

| 检查 | 原结果 | 修正后 |
| --- | --- | --- |
| 新后端回归 `test_research_admission` | `backend-baseline.log`：7 项，2 FAIL、4 ERROR、1 PASS；新无 Workflow 可建旧 intent，旧 round 被当前 pin 路由为 legacy 指纹等 | `backend-fixed-targeted.log`：新回归与原 rounds 共 18 PASS |
| UI 固定候选回归 | `ui-baseline-tests.log`：4 FAIL、2 PASS；experiment/错误 pin 仍可选，缺候选不会禁用保存 | `ui-fixed-related.log`：ExecutionEditor/ResearchWorkspace 共 18 PASS |
| 原 legacy 测试适配 | `legacy-suite-first.log`：15 项，4 FAIL、5 ERROR；旧测试直接从已删除 fresh creator 建历史 | 显式持久历史 fixture 保留原 owner、完整目标、请求、UNKNOWN、预算、取消断言；新创建/事务回滚转由当前 rounds 路径验证；33 项便携套件 PASS |

初次 UI 工具检查因借用目录缺 happy-dom/锁定版本不一致失败（`ui-environment-first.log`）；在本 tree 运行锁定 `npm ci` 后再取得上述真实红/绿结果，未改 package/lock。初次 pyright 错误（`pyright.log`）来自借用 venv 的旧安装源码：补上本 tree 的 `PYTHONPATH=platform:deployment:applications` 后 `pyright-source.log` 为 0 errors/0 warnings；未修改产品来消除环境错误。

## 实际执行结果

Python 使用 `/workspace/agent-factory-cleanup/.venv/bin/python`，模块路径为 `PYTHONPATH=platform:deployment:applications:platform/tests:applications/tests`。

- `python -m unittest test_research_runs test_research_records test_research_admission test_research_rounds test_research_projects -v`：33 PASS，3.808s（`backend-fixed-portable.log`）。
- 独占 loopback PostgreSQL 17.11，`FACTORY_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/postgres`：`test_research_admission_postgres test_research_runs_postgres test_research_records_postgres` 共 9 PASS/0 skip，21.884s（`pg-first.log`）；`test_research_workflow_postgres` 5 PASS/0 skip，22.775s（`pg-native.log`）。
- PG 证明公开 experiment/no-Workflow 新请求拒绝、零新分配/派发；持久原命令重启恢复、原 UNKNOWN 不重派、原 scope 取消、绑定后失败事务回滚。真实 current round 的 saved plan pin 未替换。无 Workflow 的 round-shaped 历史 command 是明确合成持久 fixture，不是旧 Workflow 执行兼容证明。
- `ruff check platform deployment applications scripts` PASS；全项目 pyright 0 errors/0 warnings；Python architecture 512 modules，0 violations/coverageGaps；OpenSpec strict、`git diff --check` PASS。
- `NODE_OPTIONS=--no-experimental-webstorage npm run check` PASS：lint、tsc、53 files/495 tests、build（`npm-check.log`）；production/full 两次官方 registry `npm audit --audit-level=moderate` 均 0 vulnerabilities；`npm run build:research` PASS。

## 实际浏览器

使用现有 Chromium 与 Playwright 1.62.0，`scripts/accept_live_research_workbench.py --viewport desktop`，真实 loopback TLS/OIDC、业务 HTTP 与隔离 PG；模型 transport 和本地工具为合成 fixture，没有浏览器 API 拦截。

- `browser-first.log` 保留新增 exact label 选择器错误；改为现有脚本一致的 combobox role/name 选择器，固定 value/options 断言不变。
- `browser-fixed.log` 保留旧 harness 退出后立即导航的竞争；失败页仍是 Alice。增加“退出后登录按钮可用”的明确等待，再导航 Bob；没有放宽 timeout、跳过检查或无改动追绿。
- `browser-synchronized.log` 与 `browser-desktop-synchronized/evidence.json`：PASS。发布配置同时含 research/experiment，选择器只提供空项/research；实际 1 round、1 experiment，decision=met、原 artifact/运行终态证据，刷新/浏览器返回/原用户重登，Bob 读取与结束均 404。pageErrors/consoleErrors 均 0。
- `postgres-cleanup.log`：仅 `postgres/template0/template1`；fixture sessions 0，`af_tasks` 表查询为空，live fixture processes 0。PG 时段已归还协调者。

## 未验边界

未运行 full release、Windows 或移动端浏览器，未测试真实模型/ORX/远程 GPU；不把 synthetic native 通过当作上述兼容证明。真实旧 paused Workflow 若原 executor 缺失，不能据此宣称跨版本继续执行；只保证持久原命令/收据、已有历史入口与原清理边界，不改 pin、不新增旧 executor，也不为未部署的 R1 中间 source pin 注册兼容。无 Workflow 装配不承诺 ResearchRounds 列表或领域执行步骤。该 PR 仅 R4，R2/R3 不在范围内。
