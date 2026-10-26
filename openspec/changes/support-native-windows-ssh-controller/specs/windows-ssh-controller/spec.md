## ADDED Requirements
### Requirement: Native Windows existing SSH execution
The factory SHALL use system OpenSSH from a native Windows controller with the existing scoped vault and original remote Linux execution lifecycle, without WSL or a new controller.

#### Scenario: Fresh scoped invocation
- **WHEN** an authorized unexpired Windows lease spawns SSH
- **THEN** resolve only its original credential identity and release one per-call password to the authenticated fixed helper
- **AND** no private key plaintext or password is written to disk, argv, environment or logs

#### Scenario: Revocation or expiry
- **WHEN** the original guard or lease expiry fails before resolution, password release or an effect write
- **THEN** the corresponding fresh action is denied and owned local resources are closed without inventing a new remote operation

#### Scenario: Bounded local carriers
- **WHEN** concurrent Windows carriers reach the configured limit or the service closes
- **THEN** further carriers are rejected and every existing carrier retains bounded owned cleanup

#### Scenario: Process scope failure
- **WHEN** normal exit, cancellation, timeout or an exception ends either SSH consumer
- **THEN** the explicit process scope reaps its owned processes and removes its per-invocation files
- **AND** hard controller termination stops live secret-holding descendants while any residual ciphertext is acknowledged honestly

### Requirement: Independent packaging and original identity
The production fixed helper SHALL be available from the standalone core installation with explicit Windows dependencies, while preserving the existing Linux path.

#### Scenario: Lost remote acknowledgement
- **WHEN** a Windows SSH connection loses an original operation acknowledgement
- **THEN** the existing journal/custody path inspects the same original operation and does not submit a second launch

#### Scenario: Unavailable real integration environment
- **WHEN** no authorized Windows-to-Linux helper endpoint is available for the final real check
- **THEN** mark that gate BLOCKED rather than equating Windows loopback or synthetic protocol checks with cross-machine acceptance


#### Scenario: Unicode installed helper path
- **WHEN** a Windows SSH invocation uses a core installation and carrier parent containing Unicode and spaces
- **THEN** invoke only a byte-identical copy of the fixed installed helper at a fixed relative filename in the protected invocation directory
- **AND** authenticate that exact copied helper and the original installed interpreter chain before releasing the password
- **AND** preserve strict host pinning, one-use release, cancellation and cleanup without changing system locale or using an alternate credential path
- **AND** a launcher that cannot run from that location fails closed rather than weakening identity checks


#### Scenario: Space-containing private known-hosts path
- **WHEN** the protected carrier parent contains spaces or Unicode
- **THEN** resolve the fixed known_hosts filename only from the original owned SSH child cwd with the original exact pinned host key
- **AND** strict host checking and exclusion of global trust files remain enabled
- **AND** a wrong host pin is rejected before any password release

### Requirement: Shared deadline and bounded cleanup failure scope
Windows SSH SHALL 在原 caller deadline 与 lease expiry 的最小绝对期限内执行认证，不在最终授权查询之前另起更短 broker 总期限；清理错误 SHALL 保留真实失败与有界容量记账。

#### Scenario: Successful slow authority check or helper connection
- **WHEN** 最终 guard 或 helper 连接等待超过六秒但仍早于原绝对期限
- **THEN** 不因废弃的六秒预算拒绝原调用
- **AND** 原期限到达或撤权仍在密码释放前拒绝，关闭原进程范围且不重试

#### Scenario: Only encrypted invocation files remain
- **WHEN** 原进程范围、broker 和 pipe 已确认关闭，仅 invocation 目录删除失败
- **THEN** 抛清理失败、清除内存密码，保留 failed slot 并计入原容量上限
- **AND** 其他 owner 可使用剩余 slot，全部容量被占用后仍拒绝
- **AND** 显式 manager close 不伪报清理成功或重试旧工作

#### Scenario: Secret holder cleanup remains uncertain
- **WHEN** 原 process/broker/pipe/kill 清理无法确认
- **THEN** 保留原 failed slot 并关闭新 admission，不弱化现有失败证明

### Requirement: One pinned command policy across controllers
两平台 SHALL 共用固定 SSH 信任与 endpoint 参数构造，同时保留平台凭据和进程生命周期。

#### Scenario: POSIX private paths contain spaces or quotes
- **WHEN** 私有 agent socket 和调用临时目录包含空格或引号
- **THEN** 原 child 仅使用配置的 agent、public identity 与严格 pinned known_hosts
- **AND** 不因 OpenSSH `-o` 二次解析失败，不读取外部 agent/config，不改变父 cwd

### Requirement: Product checks own the default Windows lane
默认 Windows PR 检查 SHALL 运行真实产品管道/进程与独立安装验收；独立候选认证探针 SHALL 仅按需运行并保留原证据。

#### Scenario: Candidate probe becomes manual
- **WHEN** 将重复 Stage B job 改为手动触发
- **THEN** 产品两消费者、错误 pin 零释放、原取消、expiry/revoke、Unicode/空格安装及进程/helper 停止断言仍默认执行
- **AND** 不把探针专有 AGAIN/N 或历史 Stage A 证据称作当前产品新增覆盖
