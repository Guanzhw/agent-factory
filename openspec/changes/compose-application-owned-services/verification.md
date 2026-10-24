# 验证记录

## 阶段一

基线97adbc8，集成#98 5799403、#97 965350f（后者fast40112590106成功，full40112603820仍待终态）。root串行运行重型检查。

- composition-two-apps：真实PostgreSQL/ASGI/Agno双应用、两种安装顺序2项通过，14.253s测试/17.628s driver，零skip。安装期间inert、原任务/取消/占用隔离与positive stop释放均验证；worker在运行期间补充model构造计数断言，不能外推新增计数也已执行，需后续固定源码复验。非TCP/live验收。
- composition-shutdown-assembly：原#98真实关闭/非零退出/重启原身份及原装配5项通过，108.716s测试/130.681s driver。process证据见scratch/task-history-20261024/composition-shutdown-evidence。没有延长35s生产期限或原fixture界限。
- 独立审查发现第二app启动失败时首app清理先于guard启动。现已在组合stack unwind之前调用幂等begin_shutdown并发布同一期限；实际短子进程同步阻塞清理exit1，保留原Timer35s参数，fixture仅加速真实timer。同步constructor/shutdown/abort契约禁止async callable静默漏await。
- composition-core-research-pure：131项，129通过/2失败/零skip（3.858s）。失败暴露新多owner取消实现扩大至外层workflow顺序，破坏旧不确定cleanup必须先传播的契约。已恢复该生产顺序，保留两个旧断言；新owner之间仍全部通知后传播。首次定向33项有1个新fixture仍要求旧候选错误顺序，记录保留，修正其预期为原外层契约后再验证。
- 首次静态失败569 missingimports源于新worktree没有独立venv；offline uv sync缺editables缓存，获准frozen安装锁定68包后重试，发现真实1项旧staticmethod override冲突。改为instance wrapper并让纯helper测试直接调用ResearchControlHooks，不忽略类型错误。最新静态结果另录。

证据目录/workspace/scratch/task-history-20261024，各label有command、UTC、exitCode与log。所有输入合成/loopback，无paid/live模型。阶段二graph全局桥接仍未迁移，不能声明#99完成。

最终stage1 Pyright零错误/警告，Ruff通过、架构739modules零violations/coverage gaps。取消顺序修正后33项通过（24.319s，runner27.161s）；旧131中的其余129已有通过记录，未机械重复所有131。新step1.5额外model计数还需固定源码复验，原验收语义已有两真实case通过。独立审查未发现新的确定阻断；全然丢失声明的未知历史binding不能自动识别为缺owner，声明缺席owner则保持UNKNOWN/held，此限制保留。
