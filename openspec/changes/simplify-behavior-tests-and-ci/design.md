# Design

## Context

具体候选与源码依据沿用 PR96 计划。未清理提交的完整 CI 已启动：[run 40078129086](https://github.com/Guanzhw/agent-factory/actions/runs/40078129086)。测试实现和测量由不同代理负责；最终判断由主代理根据源码、回执和独立审查完成。

## Goals / Non-Goals

以可观察行为决定测试去留，以成功用例 ID 和环境差异证明覆盖保留。产品运行时、权限和执行语义保持现有契约。

## Decisions

1. **断言跟随拥有边界。** DOM 测试保护用户能看到和操作的行为；AST/resolver checker 保护源码依赖方向；协议测试连接真实受监控的 transport。保持一个清楚的观察点，移除重复字符串或描述符镜像。
2. **并发验证包含合法后继。** 同任务检索在任一时刻最多一个执行；首调用完成后允许后续检索。用事件握手验证顺序，而非只比较锁对象身份。
3. **Linux 全量只有一次行为执行。** PostgreSQL job 已使用完整发现；将最终成功 ID 与基线普通成功 ID 对照，并审查无数据库专属分支。只有证据覆盖的重复执行才移除。Windows、独立核心真实安装和 required 无跳过契约继续独立验证。
4. **短浏览器检查复用已构建应用。** 在已有 build 后运行 configured 与 bind-loss，固定 Playwright/Chromium 版本；缺少依赖、构建或有效场景明确失败。API 拦截场景的证据范围单独标明。
5. **比较同类运行。** 基线和最终完整 GitHub workflow 使用相同 OS runner 类别与 Node 主版本，分别记录缓存、版本和实际阶段。耗时是单次观察；确定性的重复执行数量与波动的时间收益分开报告。

## Coordination

| 范围 | 拥有者 | 完成依据 |
| --- | --- | --- |
| 前端测试、依赖、前端边界检查 | frontend cleanup | DOM/边界回归、完整 Web 检查和审计 |
| Python 候选测试 | Python cleanup | 定向前后结果与有效反例 |
| CI、浏览器依赖和 smoke | CI/browser | 路由、真实 Chromium 与缺失条件检查 |
| 基线与最终测量 | measurement | 不可变提交、原始日志、ID/耗时比较 |
| 规范、集成、独立审查与合入 | coordinator | 最终源码审查、完整 CI、复核和合入回执 |

## Risks / Trade-offs

- Happy DOM major 改变测试环境 → 小步升级并运行真实 Chromium 和完整 DOM 回归。
- 数据库存在与否可能覆盖不同分支 → 比较成功 ID，并逐一检查测试的环境条件；保留有独有价值的短便携检查。
- 基线 PostgreSQL workflow 只打印末尾 400 行 → 明确缺少完整基线 ID 的限制；最终保留全日志，与基线 Linux 普通成功 ID 逐项对应。
- Windows 或显式外部工具场景可能跳过 → 保留原因，不把跳过计作已验证功能。
