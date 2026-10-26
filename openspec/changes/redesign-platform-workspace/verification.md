# Verification

## 当前状态

方案和远端凭据恢复增量的非作者审查及 OpenSpec strict 通过。产品实施基线为登录 PR #150 合入的 main `3ec76ad34a97c3803933df646fd30966d4019024`；tree 为 `e681f891d2cd7a49e67713a9828696ab9b7eabf8`，与登录最终 head `80ba675df28352b9b928cdef77970ec528a5e969` 完全相同，head 为 main 祖先。已读核验 PR merged=true、main push [CI 40365597025](https://github.com/Guanzhw/agent-factory/actions/runs/40365597025) attempt 1 精确指向上述 main、全部五 jobs 成功。两条规范提交无冲突 rebase 后才开始产品修改。

此前开放 PR 浏览器调查不代替本次最终实现验收。登录历史 full 的 MCP late 测试超时根因仍未明确；后续诊断增强及最终 full 通过不证明该历史根因已修复。

## 实施验收

产品冻结提交 `5a3c11b`；后续仅补充审查与验收文档。沿用 React、既有 API 和路由，不增加框架、后台契约或用户系统。选定设计来源及两个官方技能的只读应用方式见 design.md。

| 边界 | 实际证据 | 结果 |
| --- | --- | --- |
| 定向行为 | 首页空/非空/失败/陈旧与 owner 切换；资源分类、原凭据请求离页恢复；当前页点击、未知路由、权限和应用来源 | 相关组件与路由测试通过 |
| 前端检查 | `npm run check`：56 files、526 tests，lint/typecheck/core build；`npm run build:research` | PASS；保留既有大 chunk 提示，未引入新依赖 |
| 依赖与架构 | 官方 registry 生产及完整 audit 均 0 vulnerabilities；架构 fixture 11 tests；103 modules、0 violations/coverage gaps | PASS |
| 既有浏览器回归 | `personal_tools_smoke.py --browser /usr/bin/chromium`：8 scenes，含 3 手机场景 | PASS；API 是合成 fixture，不代替真实服务验收 |
| 真实浏览器 | 隔离 PostgreSQL 17.11、Agno 3.1.0、真实 CLI 创建普通成员与密码认证；无 demo、身份注入、API 拦截 | PASS，下面逐项说明 |
| 规范 | OpenSpec strict、whitespace | PASS |
| 非作者审查与视觉 | 独立累计代码审查与整改见 review.md；视觉与窄屏见仓库根 design-qa.md | 产品代码 PASS；最终文档和视觉结论以对应报告为准 |
| 发布 | Draft PR 精确 head CI、合入 tree/祖先关系及 main CI | 在发布阶段核验，最终链接与版本记录于 PR 和交付回执 |

真实浏览器使用 `/workspace/design-audit/implementation-validation/results` 与 `screenshots` 保存逐场景记录和 PNG；这些本次隔离运行资料不加入公开仓库。

- 最终桌面首页 1505×1045、手机 390/320、资源总览、服务器、凭据、工具、高级记录、完整表单均正常显示；无横向溢出。键盘 Tab 有可见焦点，手机导航、浏览器前后退与刷新通过。
- 模型本地校验失败没有配置写入；断网发生在 owner 读取前，没有配置写入且显示未确认提示。桌面和 320px 的提交结果均在当前视口内；坐标允许 1px 的浏览器亚像素取整误差，原先 -132px 的错误仍不满足验收。
- 双击实际保存只产生一次 configure POST 和一次 default POST；服务端只存在一条本人无认证默认模型配置。刷新、退出并重新密码登录后仍可读取。测试端点为不可调用的 loopback 地址，仅验证配置持久化，没有发出模型调用。
- 手机双击退出只有一次实际 `/api/factory/logout` POST（204）；刷新后 `/session` 返回 401 并显示登录。重新使用同一隔离普通成员密码登录成功。退出后的 401 与人为断网错误为预期证据，其余最终正常场景无 pageerror/console error。
- Research → 资源 → 模型 → 凭据 → 服务器 → 资源总览 → 刷新 → 返回 AutoResearch 通过。Research 1440×1000 对照旧截图，除测试身份遮罩外逐像素一致；无项目时的入口往返不声称已验证科学任务执行。
- 最终只读数据库核验 `af_tasks=0`、`agno_runs=0`。没有创建生产账号、保存真实 API/SSH 凭据、启动任务或连接外部主机。

登录函数块与已合入基线逐字相同；Research 业务目录、后端、部署模块和依赖文件无产品差异。页面新增只读摘要及资源导航仍遵守原 owner 和能力边界。

## 失败与整改

- 首次完整前端检查因两个新增 status mock 缺少必填 `liveEnabled` 未通过；仅修正测试 fixture，随后完整 525 项及最终 526 项通过。
- 原资源测试选择了错误的同名 checkbox；限定当前凭据表单后通过，没有放宽产品验证。
- 视觉检查修复 CJK 字重、字号/主按钮、说明/侧栏/占位提示对比度，以及模型错误落在视口上方的问题；最后一项以真实坐标和截图复验。
- 首次 Research 截图仍在读取，保留但不作视觉验收；后来等明确空态再截图。一次浏览器运行遇到正常会话过期，使用同一真实密码重新登录，未修改会话协议/TTL。
- 辅助验收脚本曾过早选择未挂载控件、误用返回按钮名称及 logout 路径；保留首失败，按当前 DOM 和实际 API 修正。320px 的 -0.031px 亚像素误差改为 1px 容差后通过，没有修改产品来迁就脚本。

## 交付与部署边界

最终截图先逐张检查和脱敏，再单独保存供聊天查看。部署接续提供最终合入 SHA、Research 配对构建/启动、PostgreSQL 与持久 vault 配置步骤，凭据仅由部署方安全设置。当前云端只有 loopback 自签名测试地址，未发现可用于此 Python/PostgreSQL 服务的受支持用户访问 URL；不将其称为正式托管，不创建匿名服务或第三方隧道。最终 CI、Library 保存与本次隔离环境清理结果由交付回执记录。

外部模型、CLI/MCP/SSH 服务、真实远端执行与用户可访问部署未验证；本轮不以静态页面或合成 smoke 代替这些集成。登录历史 full 的 MCP late 超时根因依然未知。
