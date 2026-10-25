## Purpose
研究应用通过成员明确选择的 SSH 计算资源执行训练，复用底座原生 root/child、持久操作身份、凭据和资源托管。连接可以经过透明 TCP 端口映射，但连接成功不等于训练能力或真实 GPU 验收通过。

## ADDED Requirements

### Requirement: Explicit SSH compute selection
研究运行 SHALL 使用已确认约定中的计算资源与训练规格，MUST NOT 将连接检查、隐式默认目标或未知集群调度方式视为可执行训练。

#### Scenario: Forwarded endpoint with pinned final host
- **WHEN** 成员选择通过透明 TCP 转发到最终 SSH 主机的已保存连接
- **THEN** 使用映射入口端口与最终用户/主机公钥完成严格验证，目标主机身份不符即拒绝，不关闭校验或自动建立新隧道

#### Scenario: Missing execution prerequisites
- **WHEN** 缺少匹配 runtime、执行权限、明确训练入口或要求尚未适配的 scheduler
- **THEN** 拒绝新训练且说明具体缺项，不在登录节点自动执行、不安装 runtime、不创建凭据或改网络安全配置

### Requirement: One native research control chain
研究 root 与实验 child SHALL 保留 Factory 原生任务身份与同一原预算，远端训练仅为该 child 的原外部操作；系统 MUST NOT 为失联新建替代任务或第二恢复执行器。

#### Scenario: Child waits and resumes after controller restart
- **WHEN** 原 child 提交训练后原生暂停，控制器重启后取得同一原操作的完成与停止证据
- **THEN** 继续同一 child/run/requirement，结果返回原父操作与 root；原任务/远端任务数量不增加，模型评价实际结果

#### Scenario: Acknowledgement unknown
- **WHEN** 提交可能已送达但应答丢失，或查询无法证实原运行身份
- **THEN** 保持 UNKNOWN 与资源 holds，仅按原身份查询/取消，不重新提交、不把超时或 SSH 会话结束当作停止

#### Scenario: Continuation acknowledgement lost
- **WHEN** 原 child 的继续命令已发送但回执丢失，随后服务重启
- **THEN** 找回原 requirement/version 的持久命令与原 native queue 接受证据，不创建替代命令或 run；父研究等待与 child 的 SSH 等待分别由精确绑定负责

#### Scenario: Budget, cancellation and foreign continuation
- **WHEN** 原预算耗尽、父任务已取消、资源权限撤回，或试图用其他任务的操作结果继续
- **THEN** 禁止新执行与越权续跑，保留原可授权观察/取消路径；取消只有正向停止证据才释放 holds

### Requirement: Original evidence before scientific assessment
系统 SHALL 从原训练目录收集明确选择的证据并通过既有产物权限分享，MUST NOT 将普通退出成功当作研究达标或把未经选取的私有输出共享。

#### Scenario: Results and cleanup
- **WHEN** 原训练退出并获得完整停止证据
- **THEN** 收集原退出状态、限定日志/指标与精选文件，按原身份和完整来源依赖归档；保留负结果，归档失败不删除源证据、不伪造完整成果

#### Scenario: SSH receipt provenance
- **WHEN** 研究应用请求读取某个 SSH 实验的结果
- **THEN** 仅以当前owner与原child/run/operation/lease精确匹配的SSH证据读取口返回结果；不得伪装唯一CLI回执、放宽原CLI来源检查或接受模型编写的receipt

#### Scenario: GPU allocation and release evidence
- **WHEN** 训练声明使用GPU或请求释放其资源占用
- **THEN** 核对实际设备绑定及原进程停止/设备释放观察；仅有环境变量、平台额度声明或SSH会话退出不能证明GPU分配、强制隔离或释放，缺证据保持对应hold或阻塞验收

#### Scenario: Read-only peer question
- **WHEN** 团队经验询问或恶意来源要求启动训练
- **THEN** QA 路径没有 SSH 训练工具，远端 dispatch 为零，不因共享内容扩大资源授权

### Requirement: Separate mechanism and target acceptance
验收 SHALL 分开真实本机 SSH/转发机制、合成模型决策与目标机 GPU/正式模型结果，MUST NOT 用准备接口或 mock 代替 D01。

#### Scenario: Target is not configured
- **WHEN** 本机真实 sshd 的原身份恢复测试通过但目标集群资料/资源尚缺
- **THEN** 仅报告机制通过，真实目标训练与 D01 标为 BLOCKED，并列出最小缺项

#### Scenario: Cancellation during request transmission
- **WHEN** submit 在 SSH 可写等待或分片传输期间被取消
- **THEN** 每次写入及正常发送 EOF 前重新核对原准入/取消状态，不继续发送剩余完整请求；已完整发送或可能送达的原操作保持 UNKNOWN/hold，并只按原身份核对，不能声称已撤回远端执行
