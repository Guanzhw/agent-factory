# 窄管道模块验证

基线 d3ec92f，独立worktree `agent-factory-bounded-ssh-exchange`。规范26a149d获独立设计PASS后实现。没有修改两个消费者、凭据、SSH spawn或CI。

- 命令：`PYTHONPATH=platform /workspace/agent-factory-core-only/.venv/bin/python -m unittest discover -s platform/tests -p test_ssh_exchange.py -v`。
- 首轮11项实际Linux子进程测试通过，2.348秒；补充明确reap失败的断言后12项通过，2.335秒，均零跳过。原日志见[evidence/linux-first.txt](evidence/linux-first.txt)、[evidence/linux-final.txt](evidence/linux-final.txt)。无失败重跑。
- Ruff、git diff --check通过。没有PG、真实SSH、模型、GPU或外部连接。
- 短写通过真实os.write限制单次大小检验；reap失败通过有限mock检验错误/timeout参数。其它管道、deadline、取消、退出、背压、超限均实际本地子进程。成功/失败后检查直接进程退出和管道关闭；不新增I/O线程。
- Windows实际非阻塞pipe/EOF/no-data行为未验证，等待独立runner。Linux成功或模拟短写不能代替Windows证据。
- 两消费者接线及async取消等待原worker清理仍由coordinator集成，不据模块通过宣称完整Windows控制端或取消生命周期闭合。
