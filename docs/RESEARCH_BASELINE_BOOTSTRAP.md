# 本地受管 baseline：准备 → 训练 → 独立评价

本交接用于已经授权的本地开发训练。入口是
[`scripts/run_research_baseline.py`](../scripts/run_research_baseline.py)；一次调用顺序执行三个阶段，
复用 Factory 的素材发布、方案审批、原生任务、进程租约及证据存储。
它不安装依赖、不创建数据库、不开放远程服务，也不购买模型或计算资源。

**当前真实目标 baseline 完成数为 0，`val_bpb` 为 `null`，尚未完成真实训练/科研验收。**
合成 tokenizer、真实 PostgreSQL/原生进程测试及模拟设备观察，只证明各自测试覆盖的控制流程。
本文提供可执行入口与输入契约，不把这些测试换算成目标训练成功。

## 运行前已有的事实与材料

以下是实际运行所需的事实条件，不是再次申请已经授予的本地训练权限。

- 使用同一个经过检查的研究 venv。Factory 必须实际位于该 venv 的
  `lib/python<major.minor>/site-packages/agent_factory`；仅在 checkout 旁启动，
  或通过 `PYTHONPATH` 指向源码，不满足 runner 的检查。
  runner 的 `sys.prefix` 必须是配置的 `venvRoot`，实际解释器目标必须是
  `interpreterTarget`，并匹配 `interpreterSha256`。
- 已有可连接的 **loopback、专用 PostgreSQL 数据库**。不使用生产库或其他任务的库。
  DSN 单独保存在当前用户拥有、单硬链接、无符号链接的 `0600` 文件中；
  必须使用 `postgresql+psycopg`、字面 `127.0.0.1` 或 `::1`、显式端口、数据库名，
  不含查询参数、fragment、换行或前后空白。读取器另行钉住 `hostaddr` 和连接超时。
  不把 DSN、密码或该文件内容放入配置示例、Git、日志或交接消息。
- 私有工作目录、输入根、项目根和缓存目录使用当前用户拥有的 `0700`。
  配置、tokenizer JSON、数据分片和环境证据使用 `0600`、单链接普通文件。
  `workspace` 必须尚不存在，其父目录已存在；runner 会独占创建工作目录。
  不改共享缓存的权限来满足检查，不通过符号链接或硬链接冒充私有副本。
- `projectRoot/pyproject.toml` 和 **原位置的** `projectRoot/uv.lock` 已确定。
  `projectRoot` 是私有 `0700`，原 `uv.lock` 是 `0600`。锁文件的 environment pin
  绑定该原目录及 inode；不能复制到 `workspace/environment` 再当作原锁文件。
  完整 interpreter capture 还会分别钉住 pyproject、pyvenv.cfg、inventory 和解释器链。
- 已有安全导出的 tokenizer JSON，以及固定训练/验证分片。runner 不在本次调用中下载数据、
  创建 tokenizer 或安装 tiktoken。准备阶段限定词表总量不超过 **8192**、tokenizer JSON
  不超过 **1 MiB**；原始可反序列化的 tokenizer pickle 不能代替安全 JSON。
- 已有实际选定的设备 UUID、接收端 namespace digest、固定 `nvidia-smi` 可执行文件及其 SHA256。
  它们来自操作者的实际本地检查，不能使用本文占位符或虚构 UUID。
  设备观察仍是可信本地观察：Factory 同库独占租约不宣称物理隔离、显存配额或阻止外部进程。

### CoW 与完整环境

若必须脱离共享硬链接缓存，先在**实际目标文件系统**检查 CoW 能力。
Linux/WSL 的名称、磁盘格式名称或另一个目录的成功结果都不能替代该事实。
已有的能力工具与克隆工具为：

```sh
"$REVIEWED_CONTROL_PYTHON" -B "$FACTORY_CHECKOUT/scripts/probe_research_storage_capabilities.py" \
  --scratch-root "$PRIVATE_PROBE_ROOT"

"$REVIEWED_CONTROL_PYTHON" -B "$FACTORY_CHECKOUT/scripts/clone_research_environment.py" \
  --source-root "$REVIEWED_SOURCE_SITE" \
  --destination-parent "$PRIVATE_CLONE_PARENT"
```

这里的 shell 变量均由操作者填写为实际检查过的路径。probe 的成功只覆盖私有小文件；
完整克隆还须实际成功、独立 inode、完整哈希复核及保留私有 clone receipt。
clone 只处理一棵无符号链接的普通文件树，不是整个 uv venv 布局的自动迁移器。
解释器链接、项目文件、实际 site 路径与 Factory 安装仍须与最终配置一致。
**尚未得到目标实际 CoW 结果时，该条件就是未验证；没有 full-copy 或 hardlink fallback。**
失败或未封存的目标目录保留供核对，不重置后隐瞒重试。

完整环境使用 `complete-venv-32768-v1`，不能裁剪库、dist-info、顶层模块、`.pth` 或字节码
来压低计数：最多 32768 文件、65536 树条目、1 GiB/文件、8 GiB 全站文件字节；
完整 interpreter contract 还独立限制目录数与序列化大小。
[`research_bootstrap_inventory.py`](../platform/agent_factory/research_bootstrap_inventory.py)
只静态读取 METADATA、源码字面量及全部 site 文件，生成私有 inventory/kernel；
随后才写入证据并调用原 `capture_interpreter_contract`。
完整 hash、observer 与 guardian 的复核会占用实际时间和内存，均不能从训练预算中隐去。

本 runner 显式选择 **`uv0117-setuptools82-local-v1`**，子进程环境设置
**`SETUPTOOLS_USE_DISTUTILS=local`**。该 profile 包括已审查的 startup `.pth` 和对应 shim
源码身份；不是旧的 `stdlib` 绕过模式，也不允许任意额外启动代码。
库存内包含 `.pyc` 不代表已经通过启动或源码执行检查。

### 公共源码 pin

上游固定为 `karpathy/autoresearch` commit
`228791fb499afffb54b46200aca536f79142f117`。
`upstreamRoot` 必须具有下列原始字节文件；runner 会调用
[`verify_upstream_source`](../platform/agent_factory/research_profile.py)，不会执行上游下载脚本。

| 文件 | SHA256 |
| --- | --- |
| README.md | `3958fd4195ac2f98ed35c4eaa4f3028a335165ee24945e96426c408d25793a41` |
| prepare.py | `4f2ba9cbb8ba8c4a3d35be405a913e2f3be3af9aea103ed52ef7b2a662058150` |
| train.py | `2954175f4ac42ad65164aef40910ef953789abcd05a5cc886ac9ba5a00814414` |
| program.md | `86cf987a5c381e46eefe0d0a82765223fd766d8d7acdc2afacfbbce15ecacece` |
| pyproject.toml | `675c150a9e0769f0e39a43eb7d836934266fa348d6e2403521f1ff99f9b9f1af` |
| uv.lock | `03174c5cce6387418c5b6cc9bbe8f71ad0ae1e1d6fedeaecae5cdcf7321da0a3` |

上游 lock 的源码 hash 与实际本地项目 lock 的环境 hash 分开保留。
源码身份不替代数据来源、使用条款或实际执行证据；保留现有第三方 notices，
不把原数据许可改写为镜像仓库的 MIT 许可。

## 完整配置与一次入口

以下 JSON 列出 runner 接受的**全部精确键**；额外键和重复键会拒绝。
`<...>` 是明确不可直接执行的占位符，必须替换为本地观察值。
`train-a`/`validation-a` 是操作者固定的数据分片标签，不是 Factory 任务或 artifact ID。
`requestId` 是本次调用的稳定相关键（8–40 个允许字符），也不是预先指定的运行 ID。

数值预算是可审查的合法格式示例，**不是目标资源测量、默认推荐或已通过准入的配置**。
须使用已核对的空闲资源、检查点大小、CoW 增长和外部时间预算；不能为通过检查而缩报占用。

```json
{
  "schema": 1,
  "ackLocalDevelopment": true,
  "ackTraining": true,
  "databaseUrlFile": "/<PRIVATE_ROOT>/database-url",
  "workspace": "/<PRIVATE_ROOT>/<NEW_WORKSPACE>",
  "requestId": "<STABLE_REQUEST_KEY>",
  "inputRoot": "/<PRIVATE_INPUT_ROOT>",
  "tokenizerBasename": "tokenizer.json",
  "shards": [
    {"id": "train-a", "basename": "<TRAIN_SHARD_BASENAME>"},
    {"id": "validation-a", "basename": "<VALIDATION_SHARD_BASENAME>"}
  ],
  "validationIds": ["validation-a"],
  "upstreamRoot": "/<PINNED_UPSTREAM_ROOT>",
  "projectRoot": "/<PRIVATE_PROJECT_ROOT>",
  "venvRoot": "/<PRIVATE_PROJECT_ROOT>/.venv",
  "interpreterTarget": "/<APPROVED_INTERPRETER_ROOT>/<ACTUAL_EXECUTABLE>",
  "interpreterSha256": "<ACTUAL_64_HEX_SHA256>",
  "approvedInterpreterRoots": ["/<APPROVED_INTERPRETER_ROOT>"],
  "deviceUuid": "<ACTUAL_LOCAL_GPU_UUID>",
  "receiverNamespaceSha256": "<ACTUAL_64_HEX_NAMESPACE_DIGEST>",
  "nvidiaSmi": {
    "executable": "/<REVIEWED_BINARY_ROOT>/<NVIDIA_SMI_EXECUTABLE>",
    "sha256": "<ACTUAL_64_HEX_SHA256>"
  },
  "limits": {
    "cpu_seconds": 900,
    "address_space_mb": 16384,
    "file_size_bytes": 1073741824,
    "wall_seconds": 900,
    "disk_bytes": 3221225472,
    "output_bytes": 16777216
  },
  "microbatch": 1
}
```

配置文件应为私有 `0600`，父目录为 `0700`。所有配置路径是无 `..` 的绝对本地路径；
输入文件名是 basename，不能嵌入目录。分片数为 2–1024，标签和文件名不能重复，
验证集是非空真子集；训练/验证分片不能用相同内容 hash 冒充分离。
`microbatch` 必须为 1–128 且整除 128；固定后成为本地 baseline 的源码/配置身份，
后续同设备候选比较不能悄然更改。

预算同时满足：CPU 1–86400 秒，地址空间 32–1048576 MiB，文件上限 1 KiB–2 GiB，
外部 wall **301–86400 秒**，磁盘不超过 8 TiB 且
`disk_bytes >= 2 * file_size_bytes + output_bytes`；output 为 1 KiB 起、不超过文件上限及 64 MiB。
所有配置预算为正整数。地址空间/文件 rlimit、共享预算准入和 GPU 租约是不同层，
不是主机容量或显存配额承诺。原生方案和 Settings 仍可施加更紧的边界。

在同一已审查研究 venv 中运行下列单一入口；不要把 `<...>` 占位符直接传入 shell：

```sh
PYTHONDONTWRITEBYTECODE=1 SETUPTOOLS_USE_DISTUTILS=local \
  "$RESEARCH_VENV/bin/python" -B \
  "$FACTORY_CHECKOUT/scripts/run_research_baseline.py" \
  --config "$PRIVATE_CONFIG"
```

脚本的 `--config` 是唯一 CLI 输入，不存在自动安装、`--retry`、`--stage` 或 `--resume` 开关。
不要通过 checkout `PYTHONPATH`、抽取 coding-agent 凭据或新登录流程修补包准入失败。
本调用在进程内启动原生控制应用；不需要另起公网监听器。
受控开发身份与独立 reviewer **代码身份**用于既有发布/审批接口，不是独立人类审查或生产 IdP 证明。

## canonical 入口失败诊断

仍使用上面的唯一 `--config` 入口，没有新的诊断执行框架、自动重试或绕过校验开关。
失败仍返回 exit2，保留 `RESEARCH_BASELINE_STOPPED`；随后 runner 输出一行有界 JSON：

```json
{"errorCode":"VALIDATION_REJECTED","kind":"RESEARCH_BASELINE_DIAGNOSTIC","schema":1,"stage":"PREPARATION_ASSEMBLY"}
```

以上仅为格式示例，不是已知本地故障原因。`stage` 来自代码内固定枚举，区分配置读取/校验、
workspace、解释器身份、数据库配置、prepare 组装、lifespan 启动、发布、审批、提交、
输入清单、训练、评价及清理。`errorCode` 仅由可信异常类型分类，例如 `FILE_NOT_FOUND`、
`PERMISSION_DENIED`、`DATABASE_OPERATIONAL`、`VALIDATION_REJECTED` 或 `UNEXPECTED_ERROR`；
不读取或输出异常原文、参数、因果链、DSN、密码、私有路径、原请求或设备标识。

runner 在退出 lifespan 和处理清理前保存它最早观察到的失败。后续故障至多增加一组
`secondaryStage` / `secondaryErrorCode`，不会替换主诊断；组件内部已经包装的异常不被
反向解包，不能据此声称捕获了最深层根因。诊断不改变原清理权限、调度或回放规则。
原 STOPPED 记录的 `cleanupConfirmed:false` 保持不变，后来的空表观察不能回填原记录。

受控调用期间抑制常规 Python warning/stdout/stderr，避免 import warning 带出路径；
这是 Python 流重定向，不宣称拦截所有 C 扩展或直接文件描述符输出。只回传固定诊断字段，
不要转发完整原始日志、配置文件或命令中的真实路径。

本地复现最小回传：修复源码 commit、退出码、该 JSON 的固定字段，以及是否出现既有
`RESEARCH_BASELINE_EXISTING_INSPECT_ONLY` 标记。若已提交任务，另报各阶段是否已提交和
原任务清理证据的有限状态；不要上传原请求、凭据、文件内容或凭据哈希。

已有 workspace 仍只读 inspect，不会重跑失败批次。保留旧证据；若此前已证实没有提交
任何任务，后续使用已授权流程中的新 attempt/workspace，不能删除或重置旧 workspace
来制造“首次执行”。已被拒绝访问的 unused password 文件不属于诊断输入：不读、不散列、
不触碰，也不作为 `databaseUrlFile` 的替代；清理须另有明确许可。

## 三个阶段的持久结果

| 阶段 | 实际操作与成功条件 | 必须保留的关联 |
| --- | --- | --- |
| 1. Token-byte 准备 | 原 proposal → immutable plan → review → native task；generic bounded process 从安全 tokenizer JSON 导出 `token_bytes` I32。原进程 COMPLETED/exit0、正停止证明和 RECLAIMED 后才 import。 | 真正的 task/nativeRun/plan/lease/providerJob、独立 preparation manifest、tokenizer hash、原 artifact/reference。没有手写执行 ID。 |
| 2. 本地 baseline | 完整环境与输入 capture 后发布研究应用；原 native run 暂停，controller 仅对该暂停调用一次 `research_runtime.submit`。训练由固定 SDPA 本地适配运行，原租约正停止并释放设备后导入 checkpoint，再继续原 native run。 | 本地派生源码 pin、准备 artifact binding、数据/sample-set、环境/lock、设备、原 checkpoint producer binding。 |
| 3. 独立评价 | 创建独立 evaluator task/nativeRun/plan/lease/job，固定评价代码从阶段 2 的原 checkpoint artifact 读取，并核验原输入与评价 contract。完成后继续该 evaluator 原 native run。 | 与训练不同的执行身份、同一 checkpoint hash、固定 evaluator/source/input pins、有限结果与 stop/device release 证明。 |

准备阶段保持原 generic 限额：CPU 1 秒、地址空间 128 MiB、单文件 64 KiB、wall 5 秒；
另有私有 staging 存储 hold。它不训练、不创建 tokenizer，也不重用最终训练 manifest，
避免“token-byte hash 包含自身 manifest”的循环。

上游 **300 秒是训练窗口**。外部 wall 包含启动、环境复核、编译/预热、训练、checkpoint 导出等；
独立评价也使用自己的原租约和外部预算。不能把 300 秒当成整个三阶段执行时间，
也不能据本地 GPU 的结果给出 H100 MFU 或跨硬件相同分数承诺。

runner 在私有 workspace 中独占写入 `progress-*.json`、`environment/inventory.json`、
`environment/kernel.json`、`environment/interpreter-contract.json`、
`training-receipt.json` 和 `evaluation-receipt.json`；原 DB 与 managed storage 保留其余原始 custody。
这些文件含路径或运行关联，仅留在本地，不提交仓库或完整粘贴到公共报告。
最终 stdout 的 `RESEARCH_BASELINE_COMPLETED_PRIVATE_EVIDENCE` 仅表示控制流程结束；
controller 仍标记 `scientificConclusionVerified: false`，不能据此宣称候选已经改善。

## 失败、失 ACK 与只读核对

- 任一失败退出码为 2，公开输出有限错误 `RESEARCH_BASELINE_STOPPED`。
  保留已有 workspace、DB、progress、journal、artifact、clone receipt 和原 inode；不删目录重跑。
- instance ACK 丢失只按原 request receipt 读取 task 身份；不再次 POST instance 或 submit。
  停止路径先核对原 owner/task/plan/run，再在控制应用退出前请求取消并观察原租约；
  异步停止观察预算为 5 秒，同步 SQL/HTTP 使用各自超时。身份不匹配不取消其他任务。
  `cleanupConfirmed: false` 表示仍须核对，不能解读为已经释放设备。
- UNKNOWN、设备 busy、连接中断、timeout 或 stop proof 缺失保留原容量/custody。
  核对原 task/run/lease/job、正停止证明和 GPU release evidence；使用既有原上下文的
  inspect/cancel/reclaim，不通过新任务、改 requestId、删除 seal 或重建目录绕过未决运行。
- 对**已存在** workspace 再调用同一 CLI，只返回
  `RESEARCH_BASELINE_EXISTING_INSPECT_ONLY`，不执行三个阶段，也不自动检索或恢复任务。
  该提示本身不是一次完整 inspect 验收。操作者须从私有 progress/receipts 找回真实身份，
  用原控制面/可信维护接口作只读核对和必要的原任务停止。
- 首次目标执行前保留基线状态：`completedBaselines: 0`、`val_bpb: null`。
  只有真实三阶段证据齐全后才更新实际执行记录；科学解释、同设备重复性和后续候选比较
  仍需分别核验。当前没有自动候选接受指针变更或自动搜索循环。

实现锚点：
[assembly](../platform/agent_factory/research_bootstrap_assembly.py)、
[inventory](../platform/agent_factory/research_bootstrap_inventory.py)、
[inputs](../platform/agent_factory/research_bootstrap_inputs.py)、
[controller](../platform/agent_factory/research_bootstrap_controller.py)、
[preparation custody](../platform/agent_factory/research_preparation_store.py)。

### Read-only preparation validation (after PR45 diagnostic)

The target returned `PREPARATION_ASSEMBLY / VALIDATION_REJECTED` at exact
`58cb4fc01261d83d681e72cb522dbac965af47bc`, before any task submission.
This does not identify a specific invalid field. Controlled construction with
8191 mergeable tokens plus one special token (8192 total) succeeds; 8192 plus
one special (8193 total) fails the existing vocabulary bound. Neither result
establishes the private target's cause.

Run once using the same acknowledged private configuration and pinned environment:

```sh
<pinned-python> -B <source>/scripts/run_research_baseline.py --preflight --config <private-config>
```

This mode reads the configuration, tokenizer, fixed installed runtime sources,
and existing preparation directory metadata. It does not read `databaseUrlFile`,
construct a database/application/provider, create directories or progress files,
run an observer, submit a task, or execute training. Existing attempts remain
read-only. It emits one bounded-schema JSON report with fixed field/code/status
enums and public numeric bounds, never input values, paths, exception strings,
credential derivatives or tokenizer contents. Configuration fields and execution acknowledgments are checked independently;
a blocked acknowledgment does not suppress unrelated diagnostics. Malformed JSON
or unsafe tokenizer path fields leave only their dependent checks unperformed.
The canonical configuration validator is also checked without short-circuiting
the independent report. No acknowledgment is inferred from a preflight run.

Independent tokenizer checks are accumulated in one report. Invalid dependencies
are marked `NOT_CHECKED`; absent program/custody directories are `NOT_CREATED`.
`CHECKED_FIELDS_PASS` means only the reported static checks passed. Database and
application construction, source pin freshness at execution, admission and real
scientific execution remain unverified. A blocked report exits 2; checked fields
passing exits 0 even when explicit runtime-only checks remain `NOT_CHECKED`.
Do not treat this exit code as preparation or target acceptance.

The normal entry also reports fixed assembly substages: settings, initial
metadata database, driver, process spec, provider, target, application settings,
application creation, and preparation store. First failure survives assembly
cleanup errors. These diagnostics do not change validation, budgets, approvals,
execution or reclamation. Do not restart an old attempt or alter its historical
`cleanupConfirmed:false`; use any subsequent execution only under the existing
local attempt policy.
