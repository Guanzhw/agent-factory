# Verification

基线 `e52dd2774cd5ba9b2687d11bf811875e64ba1ccc`；产品提交 `bfc9cb6ae4fd3fada5a726c565090bd8fd3212ec`。Agno 保持 3.1.0，只有两个 QA 产品文件新增 13 行；无依赖、UI、配置、存储或双版本组件变更。

| 证据 | 结果与边界 |
| --- | --- |
| 服务回归 | 11 项便携测试通过；消息端口为明确测试替身，不代表原生重启。 |
| 既有原生回归 | 独立临时 PostgreSQL 中 QA、协议与关联分析 10 项通过，0 失败/错误/跳过。 |
| 实际保存后退出 | 原回复提交后 PID183764 以 90 退出，PID184001 重启；同 task/run attempt 1→2，脚本模型总调用 1 次、重启新增 0。回复正文/来源/时间不变，native COMPLETED、平台终态、原分配 SETTLED；GET/重复原请求不增加执行。 |
| 实际撤权后重启 | 撤回原输入中未被引用的来源；PID184872→185030，同 run attempt 2 拒绝，模型新增 0。原回复保留，读取隐藏为 source_unavailable。 |
| UNKNOWN 契约 | 真实 PG/native，测试显式注入合成 UNKNOWN，再直接调用当前 context 复用回复。UNKNOWN 不变；native COMPLETED，平台未终态，原分配 HELD、占用 4 次工具额度。不是第三个 OS 退出或真实外部副作用测试。 |
| 静态检查 | Ruff、Pyright、diff check 通过。未改前端，不重复宣称本片新增浏览器验收；完整 CI 在 PR 中记录。 |

实际退出由非作者执行；全部自有临时进程/PG 已清理，没有 Go、GPU、用户部署或持久凭据操作。首次保存场景在 spec 提交加冻结产品字节上执行，之后逐文件映射到上述产品提交；撤权/UNKNOWN 在该提交执行。

冻结 SHA256：

- `qa.py`: `10e68616fbc45b1bb789300aecfeb72524d1c4a5902a73bc8e8ce5d1d20f4484`
- `qa_workflow.py`: `75cf46e367a2e75893ea5499cffabc048cc5f8593e54a1885401a1bcf5ee5629`
- 新 QA pin: `8e776d65772bd843542d3e70b9c321f18536fd30bef338147fd8de41e81ab1ac`，由实际源码自然生成，不兼容伪旧 pin。

原始证据在执行环境 `/workspace/design-audit/research-qa-reply-recovery-20261028/`：`author/freeze-01.json`、`qa/REPORT.md`、`qa/version-map.json`，以及 `qa/os/run-saved-1793203387659371216`、`qa/os/run-withdraw-1793203468165373199`、`qa/unknown-contract-1793203516632518328`。原旧基线双模型调用失败保留；一次使用过期 head 的 QA 启动在创建 PG/服务前拒绝，修正为真实 head 后执行，未改变断言或产品代码。

未承诺模型调用后尚未保存回复、关联分析尾窗、真实模型质量或目标硬件容量。目标用户部署及旧 pin 在途状态未核实；实际部署切换须先核对，不能从本轮临时测试推断没有用户数据。
