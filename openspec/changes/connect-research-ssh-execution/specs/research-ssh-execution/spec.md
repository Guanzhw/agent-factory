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

#### Scenario: One host through multiple connection aliases
- **WHEN** two validated connections have the same final host key but different owner, reference, root or forwarded endpoint
- **THEN** their providers share the same capacity namespace and fixed pool; exact per-operation configuration pins remain distinct, and a different host key has a different namespace

#### Scenario: Distinct wait names and unique original result lookup
- **WHEN** Research root delegates a child with the exact SSH launch/wait materials
- **THEN** the child wait is named `factory_wait_ssh_process` while the root retains `factory_wait_operations`; existing child authority subset checks are unchanged
- **AND** result lookup accepts only owner/child task/run and core requires one exact SSH custody operation; absent or ambiguous originals are rejected without dispatch or application SQL

#### Scenario: Explicit SSH output selection for research delivery
- **WHEN** the user selects evidence `kind: ssh-process`, the exact launch-material pin, and named metrics/source/run_recipe fields
- **THEN** the application resolves the original delegated child through the core read port, including failed or cancelled children, and reads the original SSH receipt/output without dispatch
- **AND** only stdout whose complete original bytes pass core strict UTF-8 verification (`utf8Valid: true`), non-truncated and of at most 16 KiB containing one strict JSON object is eligible for selected-field artifacts; unselected output and raw log artifacts are never automatically shared
- **AND** absent child/output, truncated output, invalid JSON or invalid role values yield explicit missingEvidence while preserving original execution status, exit code and provenance; none is guessed or replaced with model text
- **AND** omitted evidence kind remains the existing CLI contract, with its original tool_results checks unchanged

### Requirement: Private bounded original execution results
Core SHALL expose a read-only original delegated-child lookup and bounded private SSH output without relying on successful child output or application SQL.

#### Scenario: SSH continuation is accepted before its acknowledgement is lost
- **WHEN** the actual native continue call has returned after persisting its original command proof, but the caller loses that response
- **THEN** recovery checks the same run and command fingerprint and recognizes the persisted decision (DECISION_RECORDED or EXECUTION_CONTINUING), rather than requiring UNKNOWN despite positive proof
- **AND** service reconstruction and repeated receipt reads do not send continue again or launch another helper; the separate before-send UNKNOWN case remains unchanged

#### Scenario: Original SSH helper survives an actual controller kill
- **GIVEN** the actual native job is PAUSED with its original SSH operation journal and running bounded helper child
- **WHEN** the controller OS process is killed without shutdown callbacks, and a different controller PID opens the same isolated database/workspace
- **THEN** the original helper child identity survives the kill, its retained inputs and task/run/operation/lease identities remain unchanged, and its completion resumes the original wait exactly once
- **AND** tests reuse the existing process-worker lifecycle and local helper transport substitute; they do not claim real remote networking, provider or GPU acceptance
- **AND** before killing the controller, the test records only its own SSH-agent PID/birth and socket-directory metadata; cleanup verifies those identities and terminates only those agents, then removes only their unchanged empty directories. This explicit test cleanup does not prove production bare-PID crash recovery of agents; deployment supervisor/process-namespace behavior remains a separate gate.

#### Scenario: Failed child remains attributable
- **WHEN** an owned original delegated operation failed or was cancelled
- **THEN** its unique original delegation link identifies only the same owned child task/plan/run; absent or unbound child returns null and inconsistent identity rejects without creating or observing work

#### Scenario: Native child consumes archived output
- **WHEN** the original SSH wait is completed through its versioned command
- **THEN** its same child receives the validated execution status, exit code and at most 16384 original output bytes decoded as UTF-8 with replacement, with explicit truncation and original artifact reference
- **AND** output remains untrusted private data; never-dispatched output is null, foreign evidence rejects, and receipt replay does not request a fresh model execution

#### Scenario: Actual typed experiment conditions reach training
- **WHEN** two experiments supply different schema-valid conditions to the same trusted training profile
- **THEN** their derived argv contains the fixed input argument plus their respective canonical JSON as two separate entries, and each original operation stores its exact validated input and derived target identity while sharing the host capacity pool

#### Scenario: Native PostgreSQL fixture preserves distinct original inputs
- **GIVEN** the existing actual native queue/PostgreSQL fixture substitutes only the SSH transport with a local helper subprocess, and a controlled model calls the real registered launch/wait tools
- **WHEN** two native child-shaped runs use different typed conditions and the controller is recreated while the first original wait is paused
- **THEN** the actual helper program parses the fixed argv input argument and emits its received conditions; the controlled model reads that archived output from the actual wait function result, not a fabricated completion string
- **AND** both runs retain distinct task/run/operation identities and their exact original inputs, the first resumes without adopting the later conditions, and each starts once
- **AND** this fixture proves neither delegated Research parent orchestration, real SSH networking nor live model/GPU behavior; the separate loopback fixture covers the network mechanism

#### Scenario: Parameter bounds and original recovery
- **WHEN** inputs contain quoted/shell-like text, violate the declared schema or total argv bounds, or a restarted operation is presented different inputs
- **THEN** quoted text remains inert data; invalid inputs cause zero SSH/target registration; restart reconstructs only the stored original inputs and changed replay conflicts without dispatch

#### Scenario: Invalid UTF-8 remains invalid evidence
- **WHEN** archived output contains invalid UTF-8 bytes
- **THEN** the private display may use replacement characters but reports utf8Valid false from the complete original bytes; evidence selection cannot treat repaired display text as valid scientific JSON

#### Scenario: Published setup to original SSH evidence in real native execution
- **WHEN** an isolated PostgreSQL test publishes research through the actual ResearchSetup API using a personal model connection and exact SSH launch/wait materials, confirms a project agreement with explicit SSH evidence selection, and starts the root
- **THEN** the unchanged child material-subset guard admits only the declared experiment tools, the child submits one original helper process with validated dynamic inputs, and native waiting resumes the same original root/child identities
- **AND** actual process JSON supplies selected metrics/source/recipe artifacts, the child consumes actual bounded stdout from its native wait, the controlled root model compares the returned actual measurement with the declared target and records the original experimental terminal outcome, and a second member can read/download only selected team evidence; private stdout fields remain absent and withdrawing the source removes access
- **AND** model HTTP and local SSH transport substitution are labelled synthetic; PostgreSQL, owner adapters, native queue, custody, helper subprocess, governance and artifact authority are real; no remote GPU or live provider acceptance is inferred

#### Scenario: Required helper preflight is exercised by actual launch
- **WHEN** a new native SSH launch is requested
- **THEN** the same pinned transport first checks the matching helper protocol, existing private root and required Linux/fork/proc/rlimit mechanisms read-only, before any persistent operation/lease or submit; missing capability/helper returns a safe diagnostic with no capacity hold

#### Scenario: Original operation recovery does not become preflight or redispatch
- **WHEN** an exact original launch is replayed or an UNKNOWN operation is inspected after restart
- **THEN** the original identity/receipt and input-conflict checks apply without a new helper preflight or submit, even if the helper is currently unavailable; original holds remain until positive evidence

#### Scenario: Output and original receipt must fit the supported archival contract
- **WHEN** a new SSH launch uses a local archival allowance below 65536 bytes, or its guardian stdout cap exceeds the smaller of the helper's 256 KiB cap and the local allowance
- **THEN** it fails with SSH_PROCESS_OUTPUT_LIMIT_UNSUPPORTED before target registration, preflight, operation intent or submit, without silently truncating output
- **AND** exact supported upper bounds remain admissible and retain the existing complete output/receipt archive before release; a cap one byte above is rejected
- **AND** an original UNKNOWN replay does not acquire this new-launch restriction or create a replacement operation

#### Scenario: Browser explicitly grants execution without launching a task
- **GIVEN** the real application uses isolated test OIDC and a synthetic SSH credential whose connection preparation is enabled but execution is not
- **WHEN** the member visits the existing connections page and explicitly permits configured training, and the network loses the successful response
- **THEN** the UI retains the original request across refresh and recovers its actual server receipt without a second bind request; execution becomes enabled while task, delegation and SSH launch counts remain zero
- **AND** this is unknown HTTP acknowledgement recovery, not proof of an UNKNOWN remote process reconciliation

#### Scenario: Browser selects only explicit SSH evidence fields
- **WHEN** the member creates a project with no selected evidence, switches between CLI and SSH sources and chooses an exact published SSH launch material
- **THEN** incompatible material/field selections clear, missing configuration remains visible, and saving/reloading preserves only the chosen SSH kind, exact pin and explicitly selected metrics/source/recipe fields
- **AND** no run or fabricated evidence is created by configuration; actual execution/evidence authority is established by the separate native integration case

#### Scenario: QA publication cannot acquire the SSH launch tool
- **WHEN** QA is prepared and published while SSH adapters are registered
- **THEN** its exact published tool set remains research_qa_context and research_qa_record, its model has no callable tools, and an unsolicited provider tool call fails without tool dispatch or a delegated child
