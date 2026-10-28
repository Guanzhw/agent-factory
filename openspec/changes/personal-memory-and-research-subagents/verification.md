# Personal memory verification

2026-10-28。记忆实现与真实使用旅程已验；最终 head full CI 和适用发布门禁另行核验，不代表已合入 main 或已部署。Agno 固定 **3.1.0**。

## Revision and scope

- 实现基线：`04cef0d5e8f6737fa85ae8b53013306d5fabc134`；实际 Go 最终候选：`e023453bb510ecf9d029107ce20c26a47e344dd5`。
- 独立非作者完整审查覆盖上述累计 15 文件及简洁性，无未解决代码阻塞；22 个查询/身份/恢复/工具反例独立复跑通过。
- 本片只给现有研究会话加入本人偏好的查找、保存、纠正、忘记及结果展示，复用 Agno UserMemory/PG、现有执行身份和原操作记录。没有辅助记忆模型、向量库、demo 账户或新的管理系统。
- 临时 subagent 探针在独立分支，尚未进入本片产品；长期助手间异步问答不等于临时子助手或通用动态 teams。

## Actual evidence

| 验证层 | 实际结果与边界 |
| --- | --- |
| Python 回归 | `900e59f` 实现的 101 项通过，无跳过：14 PG 记忆、11 SQLite 记忆、76 个现有会话/上下文/回复/工具/装配用例。`e023453` 只澄清工具查询说明，11 个 SQLite 测试重跑通过；最终 full 仍须准确 head 执行。 |
| 静态与前端 | 全项目 Ruff 通过；Pyright 0 错误、14 个既有 Windows 库来源警告。`npm run check` 的 581 测试、lint、类型检查和构建通过；生产/全依赖 audit 均 0 漏洞。Research 独立构建也通过，未把 core 构建当成 Research 浏览器证据。 |
| 原生 PG/进程 | `900e59f` 的 5 组测试均通过，25 次明确脚本模型请求、0 次真实模型：跨用户已知 ID、停止、DB 异常、提交后回执前退出、后改值不重放、DONE 回执后最终回复前退出。实际 `os._exit(73)`，新服务 PID 读取同 PG；不是手工改 native 状态。 |
| 恢复语义 | 两个退出正例均保留原 task/run，native attempt 1→2 后原轮 ERROR，模型 3→3、写入不重放；核回原记忆后由用户显式下一轮 find，模型才 3→5。原轮没有被改成成功。后改值反例保留 UNKNOWN，不能开始新轮，也未覆盖新值。 |
| 真实 Go | `e023453`：**24 次实际 DeepSeek v4.1 Flash 请求、3 个独立会话、5 条用户指令**，全部 HTTP 200，账单来源 Go、cost 0、无收费回退。A 保存两偏好；真实服务/worker 退出再启动，读取不调用模型；B 找回两偏好，按记住的 unittest 命令复现 3 测试中的 2 失败、只修 `stats.py`，原 3 测试不改，实际和独立复跑均通过；最终回答采用格式偏好并包含于持久化回复。 |
| 真实 UI | 同一真实 Go 旅程用桌面自然语言纠正原记忆 ID、390px 手机自然语言忘记，C 新会话查询确认已忘记；双击仅 1 POST/1 轮。真实密码认证、真实 HTTP API，1440/390/320px 无横溢或 pageerror；刷新/前进/后退 0 写请求。空指令是客户端就地反馈，跨用户拒绝是服务端证据，两者分列。 |

真实 Go 使用测试专用进程入口、正常 Settings/API/原生 PG/worker和真实密码认证；Go 密钥只在进程内存中通过既有代理转发，不进入产物或持久凭据。没有改写模型请求内容/工具结果，不声称这是原封不动产品 CLI 的网络接入验收。

## Preserved failures and corrections

- 首次脚本 stop 复用了创建会话 requestId，正常服务返回 409。仅修正测试请求 ID，保留原失败；没有放宽幂等规则。
- 首次真实 Go 共 25 个请求后失败。第一处实际断言是未找回答案格式偏好：模型把空格分隔的多关键词用于原生连续文本查询，连续空结果被误认为没有偏好。最小产品修复澄清查询语义及无 query 列举方式，不新增检索框架、不把样例文本改成迎合关键词。
- 同轮测试夹具还假定已安装 pytest，实际解释器没有该包。改用已有标准库 unittest，保留相同 3 组测试输入及必须执行测试的断言；没有安装依赖或向模型提供参考修复。
- Go 补充代码审查的一次请求耗尽输出、没有最终意见，标为 INCOMPLETE；未用于替代独立完整代码审查。

## Screenshots

下面是最终候选的真实渲染，使用明确的临时合成账号/偏好；不是产品内置样例或生产数据。

- [桌面：原条目修改前后](../../../docs/images/research-personal-memory/desktop-corrected-memory.png)
- [手机：忘记结果与历史保留说明](../../../docs/images/research-personal-memory/mobile-forgotten-memory.png)
- [手机：空指令就地反馈](../../../docs/images/research-personal-memory/mobile-empty-instruction.png)

## Reproduction and remaining gates

现有隔离回归可用 `PYTHONPATH=platform:deployment:applications:platform/tests:applications/tests python -m unittest test_research_session_memory test_research_session_memory_postgres -v`；PG 需按 DEVELOPMENT_CHECKS 提供一次性 loopback 数据库。真实模型/OS 退出/浏览器脚本及原始失败保留在云端 `/workspace/design-audit/personal-memory-20261028/qa/`，运行必须使用明确测试配置和已有授权，不向产品添加测试模式。

原生汇总 SHA256 `64dd79f822dd0c8b5509dff4a93afa5d0852a40bebe3a6658b838f424f8af35f`；实模结果 `3d8240e35ba76151b203a0eb0fc32d420f23bf8d67b8808a9d952650ff38997d`；独审 `9177e26a50092225ff8d1a198d4f88024cc8b8094a2e23875a778d6281702b94`。

待完成：最终准确 head full CI、适用发布/main 门禁。未验证：真实 GPU/SSH、目标 64GB/30 会话容量、生产部署、一般研究质量与任意长期记忆质量。忘记不删除旧聊天/摘要。全站易用性和正常依赖获取继续原 roadmap。
