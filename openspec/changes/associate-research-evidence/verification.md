# 主动关联本地实施检查点

## 状态与范围

基线为独立QA后端`76fc1c3`。规范`314619e`与准入快照补充`261fefa`已作者外独立审查通过。实现仍等待全diff独立审查及最终原生组合验证；不将任务勾选为完成。没有推送、部署、真实模型或GPU调用。

新增实际链：显式助手关联资源配置→精选研究记录匹配→原P3事件/队列→同一个无工具QA模型→有出处的领域关联。已配置后自动处理，不逐条审批；旧未配置不冒充完整旅程。固定词项筛选只限制候选，科学适用性由实际模型输入判断。研究context同时给原记录和关联分析，保存完整原来源集合；sourceAssessments对应原内容ID，实际实验goal沿原custody传入。

普通publication仅safe IDs/固定状态，受peer影响的假设、条件、goal、结果、ending等富字段经完整来源读取。继承依赖不受8条展示上限截断。当前已集成独立审查的`bind-content-source-authority`，明确精选附件通过sourceContentIds绑定的core artifact口，无owner代理；普通私问传全部实际选中publication IDs而非模型最终citations，core复核每项全部原依赖。

原attempt准备事务是输入授权准入点：先撤回则拒绝；先提交原意图则允许原授权操作继续，后继重新当前read。原成员、凭据、预算及取消检查不改变。

## 已运行证据

| 检查 | 实际结果 | 边界 |
| --- | --- | --- |
| 9个相关portable模块最终组合 | 50通过、0跳过，13.114s，exit0 | 真实SQLite共享/撤回与Store artifact owner/hash/bytes；事件/执行端口部分合成 |
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

实际PG测试：`test_research_associations_postgres.ResearchAssociationsNativeTests`两个case；在独占PG槽分别执行，使用随机隔离库，自己的TestClient/worker/scheduler正常停止，数据库由fixture清理。新source-bound core整合后尚未重复这两项，不将先前源码验证外推至当前精确head。

日志保留：`/tmp/research-associations-portable-final.log`、`/tmp/research-associations-pyright-freeze.log`、`/tmp/research-associations-native-first.log`、`/tmp/research-associations-native-malicious-first.log`。这是本机原始日志定位，仓库文档为可追溯汇总，不将临时路径当可下载附件。

## 首失败与未闭合问题

- 新peerconsumer夹具首轮2项在setUp失败：直接调用其他TestCase的`super().setUp`并不成立。保留`/tmp/research-associations-peer-consumer-first.log`，提取不含测试的共享round fixture，修后2项通过1.507s，未复制执行原有测试。
- 首Pyright4项Optional收窄错误保留`/tmp/research-associations-pyright-first.log`；修明确构造前置和关联可选分支后0错误。
- 组合full验证发现同一原task/run的永久模型错误可能被Agno QueueWorker再次尝试：普通profile `native_queue_attempts=2`与lifecycle结束存在竞态。正常/恶意QA已在其他隔离任务稳定复现，正在核心独立修复；本关联的单例1call观察不能证明该共享问题不存在。按协调要求暂停新的PG，待核心修复后跑必要最终组合，不放宽次数/超时/断言。
- 新增selected-app旧入口start事件接缝保持同事务及events-before-usage锁序；现原记录回归通过，完整PG组合与独立review仍需核对这一接缝。
- 本分支没有UI接线/真实浏览器证据，B02仍待对应集成。C02/C03真实配对任务、正式模型/费用/评分条件未冻结，仍BLOCKED；不以消息数、引用数量、全沉默或合成固定回答代替价值验收。
