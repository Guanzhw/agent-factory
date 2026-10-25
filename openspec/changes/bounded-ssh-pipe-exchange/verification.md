# 窄管道模块验证

基线 d3ec92f，独立worktree `agent-factory-bounded-ssh-exchange`。规范26a149d获独立设计PASS后实现。没有修改两个消费者、凭据、SSH spawn或CI。

- 命令：`PYTHONPATH=platform /workspace/agent-factory-core-only/.venv/bin/python -m unittest discover -s platform/tests -p test_ssh_exchange.py -v`。
- 首轮11项实际Linux子进程测试通过，2.348秒；补充明确reap失败的断言后12项通过，2.335秒，均零跳过。原日志见[evidence/linux-first.txt](evidence/linux-first.txt)、[evidence/linux-final.txt](evidence/linux-final.txt)。无失败重跑。
- Ruff、git diff --check通过。没有PG、真实SSH、模型、GPU或外部连接。
- 短写通过真实os.write限制单次大小检验；reap失败通过有限mock检验错误/timeout参数。其它管道、deadline、取消、退出、背压、超限均实际本地子进程。成功/失败后检查直接进程退出和管道关闭；不新增I/O线程。
- Windows实际非阻塞pipe/EOF/no-data行为未验证，等待独立runner。Linux成功或模拟短写不能代替Windows证据。
- 两消费者接线及async取消等待原worker清理仍由coordinator集成，不据模块通过宣称完整Windows控制端或取消生命周期闭合。

## Consumer integration and actual Windows checkpoint

This updates the earlier “Windows unverified / consumers pending” status without replacing its original module results.

- Initial consumer group: 94 tests in 9.025s, two errors from old selector-patching fixtures; preserve `/tmp/af-windows-ssh-pipe-consumers-first.log`. The corrected expanded group ran 95: 67 passed, 28 explicit PG skips, 6.582s. These skips are not PG acceptance.
- Independent review then found discarded async guards and swallowed cleanup errors. Product correction `48025fc` and four regressions `a4c0aec` were re-reviewed through `88118b2`: PASS.
- The four-regression first attempt stalled under restricted sandbox async execution and exited 143; it is not a pass. Under authorized loopback permissions the same four tests passed in 0.092s, without changing assertions.
- Final Linux bounded-pipe/consumer group: **50/50 passed, zero skips, 2.657s**, log `/tmp/af-windows-ssh-final-portable-linux.log`. No PG, external SSH, GPU or provider acceptance is implied.

Actual [Windows run40239375015 / job121307678854](https://github.com/Guanzhw/agent-factory/actions/runs/40239375015/job/121307678854)
ran **50 cases: 46 passed, 4 errors, 2.933s**. Its 12 real pipe cases and actual cancellation/repeated-cancellation/cleanup regressions passed. The group as a whole **FAILED**.
Three errors came from remote-profile fixture replacements losing their explicit POSIX remote paths; one came from collecting a directly executed Linux helper case on Windows. Reviewed fixture changes (spec `48998cb`, code `fff64a1`, applied from the PR137 correction) restore the remote paths and label the Linux helper boundary. Linux targeted verification passed **16/16, zero skips, 0.093s**. The revised Windows head has not yet been verified at this checkpoint; Linux targeted results cannot close that gate.

The Windows pipe result is genuine platform evidence, but Windows credential support remains a separate unimplemented responsibility. Neither this module nor its consumer review establishes complete Windows SSH support. No final combined PASS, real remote deployment or GPU outcome is claimed.

## Revised actual Windows portable result — dc1fead

Exact `dc1fead` [Windows run40239805493, portable job121308976958](https://github.com/Guanzhw/agent-factory/actions/runs/40239805493/job/121308976958)
passed **49/49, zero skips, 2.905s**. The selection explicitly includes three
portable classes and excludes the actual Linux-helper case; that helper's Linux
targeted group already passed 16/16. This is the revised Windows pipe/consumer
result, not a successful rerun of the earlier 50-case selection with a hidden skip.
The separate ASKPASS job in the same run failed, so Windows SSH overall acceptance
is **not passed**.

The older d3 [full40239428444 Windows job121307877812](https://github.com/Guanzhw/agent-factory/actions/runs/40239428444/job/121307877812)
ran 2171 cases: **1297 passed, 869 skipped, 4 errors, 1 failure, 272.171s**.
In addition to the four fixture/collection errors already described, the old
selector cancellation test failed because `pause_on=2` never reached its gate
within the unchanged `wait(3)`. Its log at 22:21:26 records the actual task
exception `OSError: [WinError 10038]` (non-socket operation), with call chain
`ssh_process_provider.py:55 → test_ssh_process_provider.py:133 gated_select → selectors.py:323 select`.
This is the old product's Windows pipe/selector incompatibility, not an unexplained
flaky timeout. PR138 replaces that selector path with nonblocking pipe exchange;
the revised exact-head 49-case Windows result above verifies the replacement.
No timeout extension or repeated-until-green explanation is used.

The older d3 full run's PG job is still running at this checkpoint. Its failed
Windows job cannot be relabelled PASS because a later bounded-pipe job succeeded.
ASKPASS/credential behavior remains a separate open gate.

At 1448bb9 the first post-integration actual Linux loopback/onboarding group ran four cases in 8.668s: three onboarding cases passed, the wrong-pin portion of the helper case errored because the new low-level CalledProcessError escaped instead of the existing ValueError protocol rejection. This was an error-contract regression, not evidence that the bad host pin was accepted. The original failure log remains `/tmp/af-ssh-bounded-real-loopback.log`; the existing rejection/no-journal assertions are retained for the correction.
