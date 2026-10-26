# Verification

基线 `768e4adcb0e218f9ec27b81e5627db1fb3f21034`；先审方案 `28d730de5667656454dbedcbd6733022f805bae3`、被测实现 `40b8342ddb84bc97959f18849df6fdebfa53165d` 均由非作者 `audit_quality` PASS。此后仅文档收尾。

| 检查 | 实际结果与边界 |
| --- | --- |
| 本地密码/原身份回归 | 最终新用例 5 项便携 + 4 项真实 PostgreSQL 全通过；既有 OIDC/会话/禁 demo 回归通过。覆盖 hash/冲突/中断、失败无 session、禁用、CSRF、退出及私有产物 owner 隔离；复验不累计为新增覆盖 |
| 前端与依赖 | `npm run check` 53 文件、503 测试通过；生产/全量 npm audit 均 0 vulnerabilities；保留既有大 chunk 提示 |
| 静态/包装 | ruff、pyright、architecture 通过；0 errors、14 条既有 Linux pywin32 源码 warning；531 modules、0 violation/gap。独立 core wheel 三项通过，含实际入口 `--help`、Argon2 依赖、源码一致与无应用导入 |
| 既有浏览器/选择器 | personal-tools 的 configured/bind-loss 两场景通过；fast 完整收集验证通过，collect-only 不计执行；OpenSpec strict/diff 检查通过 |

独立真实验收 `audit_crosscheck` 于 2026-10-26 在该实现首跑通过：真实 getpass CLI 创建两普通成员，密码不回显、不进入参数/环境；另一密码 76 个 Unicode 码点、141 个 UTF-16 单位（65 个非 BMP 字符）经 CLI→正式表单原值登录。core 与显式 Research 的正式 build/真实 HTTPS 均完成错误密码 401 且无新 session、正确登录 200、刷新、Expected-Owner 403、退出后旧 cookie 401；core 实际进程重启保留两会话，core 目录为空，Research 主页→空工作台→刷新→返回通过。浏览器只证明 owner guard，业务私有产物隔离由上述 PG 用例验证。最终任务数为 0；自有服务进程/端口、PG 容器/卷、临时 TLS/工作区均已清理。

首次结果保留：后端首红仅为新模块尚未实现的 ImportError，不是行为 bug 复现；前端首轮 17/24 通过、7 项为缺新入口。初实现一项测试误读 fieldset 的继承 disabled，修正测试后通过；随后 Unicode 密码真实表单合法性回归先失败，删除 HTML UTF-16 长度限制后目标 24/24 通过。最终后端/浏览器行为检查没有失败重试。提交工具曾因执行环境断连未创建进程；只读确认 HEAD 仍为方案且修改未暂存后才正常提交，未重发不明写入。

[Draft PR #150](https://github.com/Guanzhw/agent-factory/pull/150) 的先审方案映射为 `28d730de5667656454dbedcbd6733022f805bae3` → `264355cc54a4a4cd7aa4ba9d01656c7f3a242844`，实现映射为 `40b8342ddb84bc97959f18849df6fdebfa53165d` → `d42408e5d02b91aab2b752c249b74daf71eb1220`（同 tree `d6bc7c70d0ed3b49a954a0841f7aee5e71eaee90`）；元数据 SHA 差异不是恢复旧提交。最终发布 head 的 CI 仍待协调者核验，任务 3.2 保留未完成。

原始日志仅存本次云端 `/workspace/local-login-evidence/`，不入 Git。无真实外部 IdP、模型、研究执行、GPU、用户本机验收或部署；不得把隔离本地登录通过提升为这些边界已验。
