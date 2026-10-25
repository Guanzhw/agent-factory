# 主动关联本地实施检查点

## 状态与范围

基线为独立QA后端`76fc1c3`。规范`314619e`与准入快照补充`261fefa`已作者外独立审查通过。初次实现独立审查发现项目写入口锁倒序、遗漏直接原记录读取及重复正文存储；均已整改，当前等待整改复审，不将任务勾选为完成。没有推送、部署、真实模型或GPU调用。

新增实际链：显式助手关联资源配置→精选研究记录匹配→原P3事件/队列→同一个无工具QA模型→有出处的领域关联。已配置后自动处理，不逐条审批；旧未配置不冒充完整旅程。固定词项筛选只限制候选，科学适用性由实际模型输入判断。研究context同时给原记录和关联分析，保存完整原来源集合；sourceAssessments对应原内容ID，实际实验goal沿原custody传入。

当前精选publication正文仅存一次，通过core sourceContentIds检查完整来源；研究运行投影撤回后仅safe IDs/固定状态，受peer影响的假设、条件、goal、结果、ending等富字段隐藏。继承依赖不受8条展示上限截断。当前已集成独立审查的`bind-content-source-authority`，明确精选附件通过sourceContentIds绑定的core artifact口，无owner代理；普通私问传全部实际选中publication IDs而非模型最终citations，core复核每项全部原依赖。

原attempt准备事务是输入授权准入点：先撤回则拒绝；先提交原意图则允许原授权操作继续，后继重新当前read。原成员、凭据、预算及取消检查不改变。

## 已运行证据

| 检查 | 实际结果 | 边界 |
| --- | --- | --- |
| 9个相关portable模块整改后最终组合 | 51通过、0跳过，7.346s，exit0 | 真实SQLite共享/撤回与Store artifact owner/hash/bytes；事件/执行端口部分合成 |
| 重点来源测试 | 全来源跨轮、10来源不截断、原字段/附件canary撤回、source→decision→原goal、准入前后边界 | 固定输入只证明机制，不证明真实科研团队价值 |
| Ruff | exit0 | 应用源码及新测试 |
| Pyright | 0 errors / 0 warnings | 本worktree源码+锁定venv，60s有界执行 |
| 原生正常关联单例 | 1通过，7.247s，exit0 | 真实deployment/PG/HTTP setup/双用户/P3/native/OwnerChatModel；仅provider HTTP为合成 |
| 原生恶意train单例 | 1通过，6.658s，exit0 | 观察到1HTTP、failed原root、0child，无关联假发布；**不能据此关闭下述队列重试问题** |

Portable命令：

```sh
PYTHONPATH=platform:platform/tests:deployment:applications:applications/tests \
timeout 90 /workspace/agent-factory-core-only/.venv/bin/python -m unittest \
  test_research_associations test_research_qa test_research_assistants \
  test_research_rounds test_research_workflow test_research_projects \
  test_research_assistant_projects test_research_runs test_research_records -v
```

实际PG测试：`test_research_associations_postgres.ResearchAssociationsNativeTests`两个case；在独占PG槽分别执行，使用随机隔离库，自己的TestClient/worker/scheduler正常停止，数据库由fixture清理。整改后最终组合同时覆盖source-bound core与永久错误fence依赖，见下表；首次两个单例结果仍保留为历史证据。

日志保留：`/tmp/research-associations-portable-final.log`、`/tmp/research-associations-pyright-freeze.log`、`/tmp/research-associations-native-first.log`、`/tmp/research-associations-native-malicious-first.log`。这是本机原始日志定位，仓库文档为可追溯汇总，不将临时路径当可下载附件。

## 首失败与未闭合问题

- 新peerconsumer夹具首轮2项在setUp失败：直接调用其他TestCase的`super().setUp`并不成立。保留`/tmp/research-associations-peer-consumer-first.log`，提取不含测试的共享round fixture，修后2项通过1.507s，未复制执行原有测试。
- 首Pyright4项Optional收窄错误保留`/tmp/research-associations-pyright-first.log`；修明确构造前置和关联可选分支后0错误。
- 组合full验证发现同一原task/run的永久模型错误可能被Agno QueueWorker再次尝试：普通profile `native_queue_attempts=2`与lifecycle结束存在竞态。正常/恶意QA已在其他隔离任务稳定复现，首次检查点暂停PG并保留单例观察限制。现已集成独立审查PASS的永久错误原task fence（上游5fe414c，本地1cda14a），在下述最终组合复验，无放宽次数/超时/断言。
- 新增selected-app旧入口start事件接缝保持同事务及events-before-usage锁序；现原记录回归通过，现原记录portable回归通过；独立review仍需核对这一接缝。
- 本分支没有UI接线/真实浏览器证据，B02仍待对应集成。C02/C03真实配对任务、正式模型/费用/评分条件未冻结，仍BLOCKED；不以消息数、引用数量、全沉默或合成固定回答代替价值验收。

## 独立审查整改后的最终组合

精确实现整改在同一独立工作区。核心source-bound content与permanent protocol fence均已独立PASS，并由协调者确认已合入main（cd50b9c）；本分支保留原cherry-pick身份，不通过重写历史伪造验收。

| 目标 | 断言 |
| --- | --- |
| 项目写入口与来源guard真实PG双向barrier | create原receipt和change均先admission后research，竞争线程可完成，无锁环 |
| 无任何association的原记录→实际研究child | 真实deployment/native模型接收相关原记录、排除无关负对照，按原记录字段选择goal；真实factory-executor child的模型输入包含该goal，原始source ID关联到最终决定；模型仍为合成机制fixture |
| 正常P3关联 | 真实双用户配置、原事件/原task、一次OwnerChatModel合成HTTP、全来源撤回隐藏 |
| 恶意工具请求 | 真实provider响应请求train，固定错误、一次HTTP、零child，原任务失败不伪成功；包含新core永久错误fence |

四项同次串行运行 **4通过、0跳过，30.389s，exit0**。命令选`test_research_source_locks_postgres`、`test_research_associations_postgres.ResearchDirectEvidenceNativeTests`、`test_research_associations_postgres.ResearchAssociationsNativeTests`；总外层180s有界，无改产品超时。日志`/tmp/research-associations-review-pg-first.log`保留原warning与任务身份，全部自身worker/scheduler/随机库由fixture清理；PG槽已释放。

整改后portable日志`/tmp/research-associations-review-portable-final.log`，Pyright日志`/tmp/research-associations-review-pyright-final.log`。Ruff、diff check、严格OpenSpec验证通过。未运行浏览器或真实模型/科研价值对照，不将机制4PG通过外推C/D。
