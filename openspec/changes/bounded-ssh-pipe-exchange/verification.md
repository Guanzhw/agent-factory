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
