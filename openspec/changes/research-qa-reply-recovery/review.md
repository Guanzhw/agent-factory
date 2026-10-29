# Independent design review

**PASS — 当前直接修复方案可实施；产品、真实退出验收及发布门槛尚待完成。** Reviewer `/root/compare_review` 未编写产品。基线 `e52dd2774cd5ba9b2687d11bf811875e64ba1ccc`；审阅五个方案文件，aggregate `b11b55c45f2f9430256f84417a218fec0da52cac3233bb61715558aec3cd52bb`（相对 change 路径排序，拼接 `<SHA256>  <路径>\n` 后取 SHA256，不含本 review）。独立 OpenSpec strict validate 通过；本轮未运行模型或修改产品。

- 真实故障是 reply 已提交、原生运行尚未完成时退出，原 task/run 重领再次请求模型。首要验收锁定这条实际 OS 退出正链：模型增量零、原回复与身份不变、原生完成及原分配正确结算；不能以单元测试数量代替。
- 直接改 `qa.py` / `qa_workflow.py` 足够。原身份校验及事件关联分支在先；私问原回复确实存在后，在既有来源/admission 事务内核原输入、完整依赖和双方当前权限，再调用 `reply_for_task` 的既存分支核对 task/正文/依赖。缺原输入拒绝，不重新选来源；无回复走原三步，不创建占位回复。
- 内部 `savedReply` 判据由上述可信服务分支生成，不能从模型正文推断。首步 `StepOutput(content=原回复投影, stop=True)` 可复用固定 Agno 3.1.0 原生正常结束路径；源码支持不等于真实 worker 已验证。取消、未知 effect 和 custody 仍由已有机制决定，不凭回复手写终态或提前结算。
- 现有 implementation hash 自然更新，单一组件、注册与配置结构不变。旧 pin 精确匹配是已有代码约束，不是必须保留双版本的实际用户证据。历史记录受权读取保留；不伪造旧 pin、自动改绑或重放任务。

**过度实现结论：无方案级阻塞；当前范围已足够小。** 不需要 v2、版本 registry、迁移器、额外 API/UI/配置、缓存、新 worker 或通用恢复框架。必要反例围绕既有身份、来源撤权、无回复、关联分支与未知操作，不追加假设性的防御机制。

实际用户部署尚未接入，因此真实旧 pin 在途情况为未核实；这不阻塞隔离实施。真正部署时检查获授权目标，仍有在途则保留原运行版本完成再切，不把 synthetic 清理记录解释为全环境无数据。旧双版本方案及审查已完整保存在审计目录 `superseded-v2/`，不再适用；legacy pin 基线 JSON 仅为指纹变化的审计参照，不构成兼容层需求。

后续仅待实现后的完整累计 diff 独审、真实 PG/原生队列 OS 退出正链及精确 head CI。本方案 PASS 不改变任何 PR 已被拒绝或尚待确认的发布动作。

## 完整实现与证据复审

**PASS — 无产品代码或简洁性阻塞，可进入最终交付 head 的 CI；不代表 CI/发布已完成。** 累计基线 `e52dd2774cd5ba9b2687d11bf811875e64ba1ccc` → 产品头 `bfc9cb6ae4fd3fada5a726c565090bd8fd3212ec`，审阅全部九个变更文件。产品仅两文件增加 13 行；另一个测试文件与方案文档无范围扩张。两产品 SHA256 为 `10e68616fbc45b1bb789300aecfeb72524d1c4a5902a73bc8e8ce5d1d20f4484`（qa.py）、`75cf46e367a2e75893ea5499cffabc048cc5f8593e54a1885401a1bcf5ee5629`（qa_workflow.py）。

生产装配保留原来源/admission 锁与共享事务；公开消息读取只查原回执，既存 reply 分支精确核对 task/正文/完整依赖且不更新原时间。无 reply 与关联分析保留原流程，服务生成的内部 marker 不受模型正文控制。没有新框架、配置、fallback、审批或限额；已有生命周期与额度结算负责 UNKNOWN/custody，未另造防御层。当前 `research-qa` 的真实 pin 自然变为 `8e776d65772bd843542d3e70b9c321f18536fd30bef338147fd8de41e81ab1ac`，未冒充旧 pin 兼容。

- 独审自行复跑 11 项 portable 测试，零失败/错误/跳过；其中消息端口为 Mock，不能代替 PG 权限全链。另审作者 10 项真实 PG/native QA、协议拒绝和关联分析回归原日志，全部通过；没有重复付费调用。
- 独立 QA 的实际 OS 退出正链经本 reviewer 核脚本、原始前后记录、provider 日志及源码 SHA：PID 183764 退出 90 → PID 184001；原 task/run attempt 1→2，总模型调用仍为初次的一次 scripted 请求，原回复正文/依赖/时间不变，native COMPLETED、平台终态、原分配 SETTLED。保存场景运行于 spec 头上的已冻结产品字节，12 个所记录源文件逐一与产品头核对一致，不称 spec-only 原代码通过。
- 配对撤回原输入中未被答案引用的来源：实际退出与重启后同 run 拒绝、零新增模型，原 raw reply 保留，当前读取为 source_unavailable。两条 OS 用例均无手写任务终态，GET/原请求重复 POST 未新增执行。
- UNKNOWN 专项严格限定为真实 PG/native 首次三步运行中，在 record 后写入明确合成 UNKNOWN，再直接调用已存回复 context；effect 未变，native COMPLETED 后平台非 terminal，两次原额度结算仍 HELD。它没有重进原生首步 stop=True，没有 OS 重启或真实外部未知副作用/进程 custody，不能与另一用例拼成这些组合已实测。该范围与原日志/REPORT 一致；现有生命周期源码另行核验仍阻止提前结束与结算。

证据根目录为 `/workspace/design-audit/research-qa-reply-recovery-20261028/`：`independent-complete-review.json`、`independent-portable.log`、`qa/REPORT.md`；实际 OS 目录 `qa/os/run-saved-1793203387659371216` 与 `qa/os/run-withdraw-1793203468165373199`，UNKNOWN 目录 `qa/unknown-contract-1793203516632518328`。修前双模型调用证据保留。全部为隔离 synthetic 输入和 scripted 模型；回复提交前窗口、关联分析尾窗、真实模型质量及实际用户部署未在本片解决或验证。未来目标部署的真实旧 pin 在途检查仍是部署前提，不能从本轮临时资源已清理推导全环境无数据。
