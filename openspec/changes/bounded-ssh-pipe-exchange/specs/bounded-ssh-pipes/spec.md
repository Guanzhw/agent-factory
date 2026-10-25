## ADDED Requirements

### Requirement: 有界 SSH 管道交换
系统 SHALL 以单一工作deadline和响应字节上限完成受控SSH子进程交换，不依赖POSIX pipe select，不使用无界communicate/wait。

#### Scenario: 同时双向传输
- **WHEN** 子进程在读取请求期间输出超过管道容量但未超过响应上限的数据
- **THEN** 读写同时推进且结果字节准确；只在stdout EOF及零退出状态都确认后返回成功

#### Scenario: 阻塞与超限
- **WHEN** 子进程不读stdin、不结束stdout、退出后管道仍被短命子孙持有或输出超过上限
- **THEN** 单一deadline或字节上限终止交换，本地进程kill并在最多5秒清理额度内reap、关闭owned管道；不能返回部分成功

### Requirement: 新鲜授权与取消清理
系统 MUST 在spawn、每次请求写入及EOF前检查同步授权，取消后不留下owned I/O任务或新增后台读写线程。

#### Scenario: 部分请求后取消或撤权
- **WHEN** 取消Event或fresh guard在请求发送过程中拒绝继续
- **THEN** 不再写入或发送EOF，先kill本地SSH再关闭管道，收回owned任务并有界reap；不得启动替代操作

#### Scenario: 已发送原请求回执未知
- **WHEN** 原请求已完成发送但响应无法确认
- **THEN** helper只返回传输失败，不重试或推断远端停止；原消费者保留原operation恢复责任

#### Scenario: 平台证据分开
- **WHEN** Linux受控真实子进程测试通过但Windows runner尚未执行
- **THEN** 只记录Linux管道能力，不能将mock平台或本helper通过记作完整Windows SSH控制端支持

#### Scenario: spawn 返回前取消
- **WHEN** OS子进程已创建但subprocess创建await尚未返回就收到取消或超时
- **THEN** connection_made登记的transport仍被回收，迟到transport在清理状态立即kill/close；清理失败明确报告而非成功

#### Scenario: 同步guard跨过期限
- **WHEN** 受信任的同步guard返回时工作期限已过
- **THEN** 不再启动写入或EOF；记录超时且清理，本helper不声称能抢占该同步回调或OS创建调用
