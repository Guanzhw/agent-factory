# 私有开发控制面：存储确定后的最小执行计划

本阶段只交付安装计划和独立资源 probe，不安装目标依赖、不启动数据库或三阶段训练。
已有研究环境、共享 uv 缓存、硬链接和用户文件保持原状。空间不足或 CoW 不可用时停止，
不清理用户文件、不缩减完整 inventory，也不把硬链接改成“已隔离”。

## 能否复用云端

本任务实际云端 PostgreSQL 仅发布在**云端** `127.0.0.1:65432`。
目标机没有已建立的 Factory receiver、SSH 或数据库连接通道；目标的 loopback 不指向云端。
当前 DSN reader 还明确拒绝 remote host。故现在不能直接复用云端控制面而声称无需新访问通道。
本计划不建立 SSH、隧道、公网监听、持久远程凭据或新的 OAuth。

独立 control venv 可以用于准备工具、数据库连通性检查和非 ML 控制应用。
但现有 `run_research_baseline.py` 要求控制进程本身属于 `venvRoot`，解释器 target
匹配当前 Python，且 Factory 真正安装在同一研究 site-packages。driver/observer 再次
钉住该路径与运行文件。因此**两个独立 venv 不能直接拼成当前完整 baseline**。
`PYTHONPATH`、editable 安装、两边“版本相同”或相同 base Python 都不是通过条件。

本轮不增加跨 venv 执行协议。完整运行需存储方案落定后，在全新的私有 combined venv
中同时满足 Factory 和研究依赖，再重新做完整 inventory、启动和 interpreter admission。

## 1. 固定源码和工具事实

- 使用本阶段交付的完整精确 Git commit/归档，核对全部文件；不要只拼接几个新脚本。
- 原 local worker 记录既有 uv 的实际版本与已批准 Python 3.12 路径/身份；不自动升级或下载 Python。
- 只读确认 Docker daemon + 固定镜像，或 `initdb`/`pg_ctl`/`psql` 是否实际可用。
  “有 docker 命令”不等于 daemon 可用；本计划不偷偷安装 daemon 或创建系统服务。
- 存储预算包括完整独立环境、wheel/build 临时空间、编译 cache、checkpoint、PG 数据与 WAL，
  以及既有低水位余量。不能只算 wheel 压缩大小或 eager allocator 峰值。

## 2. 可独立准备的 control venv

以下变量均须由 local worker 填为经过检查的绝对私有路径；`TASK_ROOT` 是新任务目录，
`FACTORY_CHECKOUT` 是新完整源码目录，`UV_BIN` 与 `PY312` 是既有固定工具。
先确认目标目录不存在；目录使用 0700。不要将环境指向已有研究 venv。

```sh
set -eu
umask 077
test ! -e "$TASK_ROOT/control/.venv"
test ! -L "$TASK_ROOT/control/.venv"
env -u VIRTUAL_ENV -u PYTHONPATH -u OPENCODE_GO \
  UV_PROJECT_ENVIRONMENT="$TASK_ROOT/control/.venv" \
  UV_CACHE_DIR="$TASK_ROOT/uv-cache" \
  "$UV_BIN" --no-config sync --project "$FACTORY_CHECKOUT" \
  --python "$PY312" --no-python-downloads --locked --no-dev \
  --no-editable --link-mode copy --offline --dry-run
```

缓存与空间齐备后，同一命令移除 `--dry-run` 才进行安装。离线缓存缺包或 build dependency
缺失时列出缺口，不隐式联网重试。`copy` 安装会真实占用空间，不是 CoW 的隐性 fallback。
`--no-editable` 使 Factory 进入目标 site-packages；仍须检查安装生成的启动文件和所有 link count。
这里沿用 Factory 原 `pyproject.toml`/`uv.lock`，不往已有研究环境增删包。
uv 的环境路径、同步与安装选项见[官方项目配置](https://docs.astral.sh/uv/concepts/projects/config/#project-environment-path)
和[CLI](https://docs.astral.sh/uv/reference/cli/#uv-sync)。以实际固定 uv 的 `sync --help` 为最终可用性检查。

完整 combined 环境还需要原研究环境的**逐包版本清单**，以及实际缺包/不匹配 diff；仅数量不够。
保留 Torch 2.9.1/cu128、已审查 setuptools82 startup profile，以及实际审查过的 tiktoken/pyarrow
版本。在新的私有 project 中解算 Factory 精确依赖与这些研究依赖，保存新的 lock/hash/diff，
再 `--locked --no-editable --link-mode copy` 安装。新 installed lock 与上游源码 lock 分开记录。
不能对旧研究 venv 直接 `uv sync`，不能把 Factory 原 lock 谎称为已包含 Torch 的 combined lock。

## 3. 任务专用 loopback PostgreSQL

若目标已具备 Docker daemon 和镜像，可使用仓库 CI 已固定的镜像：

```text
postgres:17.11@sha256:d74eeac9a635390a49bc21bd49fccd973de707e2a53a76ac49b552b8712ec46f
```

创建新的任务专用 container/database/role、私有 PGDATA 和只读 password-file。
只发布 `127.0.0.1:<空闲端口>:5432`；使用 SCRAM，不能设 `POSTGRES_HOST_AUTH_METHOD=trust`。
容器资源起始限制可用 CPU1、memory512MiB、pids128；这不是 PG 磁盘硬配额，WAL/数据增长另计。
镜像未缓存时先记录待下载依赖，不通过另一个 tag 或系统 PG 偷换固定环境。

若已有 native PostgreSQL17 工具，可在新私有目录执行：

```sh
"$PG_BIN/initdb" -D "$TASK_ROOT/pg-data" --username=factory_task \
  --auth-local=scram-sha-256 --auth-host=scram-sha-256 \
  --pwfile="$TASK_ROOT/pg-password"
"$PG_BIN/pg_ctl" -D "$TASK_ROOT/pg-data" \
  -l "$TASK_ROOT/pg-server.log" \
  -o "-h 127.0.0.1 -p $PG_PORT -k $TASK_ROOT/pg-socket" -w start
```

这要求路径无空白且 `pg-socket` 已创建为 0700；不使用系统 PGDATA。
密码由 local worker 在新私有文件中生成，文件0600、单链接，不经 argv、终端、Git或交接输出。
用 password-file/私有 pgpass 创建专用数据库；不复用生产或其他任务数据库。
原生命令与认证参数见 PostgreSQL17 [initdb](https://www.postgresql.org/docs/17/app-initdb.html)
及[pg_ctl](https://www.postgresql.org/docs/17/app-pg-ctl.html)。

若 Docker daemon 与 native 工具都不可用，工具安装仍是实质缺口：先确定目标发行版、现有包源、
权限和下载/磁盘预算，再选择私有安装方案。不要为了“有命令可跑”自动增添系统软件源、开放服务或虚构已安装版本。

## 4. 仅做连接与 schema 验证

DSN 保存为新私有0600单链接文件，使用字面 loopback、显式端口和专用 DB。
调用既有 `read_database_url`（它固定 `hostaddr` 与 connect timeout），不打印 DSN。
在新 control venv 内完成 `SELECT 1`、Factory schema 初始化和 development reviewer 权限检查后停止；
不要调用 `run_research_baseline.py`，不要创建 GPU lease 或实验结果。

既有 CLI 可以先校验配置，再进行有界、无任务的控制服务启动检查：

```sh
env -u OPENCODE_GO AGNO_TELEMETRY=false PYTHONDONTWRITEBYTECODE=1 \
  "$TASK_ROOT/control/.venv/bin/python" -I -B \
  "$FACTORY_CHECKOUT/scripts/bootstrap_research_control.py" \
  --database-url-file "$TASK_ROOT/database-url" \
  --workspace "$TASK_ROOT/new-control-check" --port "$CONTROL_PORT" \
  --ack-local-development --ack-dedicated-database --check-config
```

`CONFIG_VALID_NOT_CONNECTED` 只证明文件和配置格式，没有验证 PG 连接。
确认已具备 GNU `timeout` 后，可把同一命令的 `--check-config` 移除，并在 Python 命令前加
`timeout --signal=TERM --kill-after=5s 30s`。这仅允许新私有控制服务绑定 loopback；
从另一原 operator 终端验证已有 `/api/health` 路由后停止。该路由执行数据库 `SELECT 1`；
超时退出不算健康成功，必须记录实际 HTTP/数据库结果。已创建的 `new-control-check` 保留；
CLI 不复用或重置它。

此 CLI 本身不调用 `ensure_task_development_reviewer(state)`，health 成功不代表 reviewer
权限检查完成。可信 bootstrap 仍需在该专用开发数据库的原应用 state 上单独调用此 helper，
并验证返回 `task-dev-reviewer`；既有 runner 在材料发布前执行它。本轮不为这项检查提前启动
runner 或科研任务，尚未调用时须明确记为待验证。该 helper 是代码身份检查，不需要新用户
密码或 OAuth，也不是生产 IdP/独立人类审批验收。

完成上述小范围步骤不等于 combined 环境或训练已准入。资源 probe 的测量、真实空间与完整
环境准入，以及训练/独立评价总 wall 预算均齐备后，原 local worker 才执行既有三阶段入口。
当前 baseline 完成数仍为0，`val_bpb` 仍为null。
