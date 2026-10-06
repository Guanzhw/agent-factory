# 原适配器 optimizer / compile 有界资源诊断

此诊断用于目标机实际测量编译、optimizer 状态分配和短 forward/backward 的资源开销。
它不创建 Factory 实验、checkpoint 或科研分数，不替代完整环境准入，也不证明 baseline 完成。
云端只执行 mock/stdlib 测试；实际目标测量尚未运行。

## 固定工作量

`scripts/probe_research_optimizer_compile.py` 校验精确 Factory 源码闭包与既有六个上游
源码文件，调用原 `build_training_bundle(..., microbatch=1)` 生成架构与 optimizer。
不执行上游训练入口，不加载任意 adapter，也不从既有 `.pyc` 拼装闭包。

固定 seed42、B1、T2048、vocab8192、8层、4 heads/4 KV heads、embd512、SSSL。
使用原 GPT/SDPA/MuonAdamW 与 `torch.compile(model, dynamic=False)`，执行两轮各一次
forward/backward 和 optimizer update，随后两次 eager/no-grad evaluation forward。
每轮 loss 除以256，但仅有**一个** microbatch；这不是原训练的一次完整梯度累积。
学习率与 optimizer 初始参数保留原适配器设定，不以简化 optimizer 代替编译开销。

首次 forward/backward/optimizer 阶段可能触发 lazy compilation；compile registration 时间
本身不能代表编译总时间。JSON 中的阶段 started/completed、elapsed、allocator 与 CPU/RSS
指标用于区分停在哪个阶段。失败记录不包含原始 traceback、私有路径或输入数据。

## 运行条件与命令

等待用户选定存储后，由原 local worker 核实新私有目录与余量，使用既有已审查的
Torch2.9.1/CUDA12.8 Python 环境和已批准 GPU UUID；不要在云端执行。
使用本阶段交付的完整源码树、已校验上游六文件目录，不零散混用旧脚本。
三个路径变量必须为绝对路径，`PROBE_ROOT` 须为新建0700目录，不得复用上次 attempt。

```sh
env -u OPENCODE_GO "$RESEARCH_PYTHON" -I -B \
  "$FACTORY_CHECKOUT/scripts/probe_research_optimizer_compile.py" \
  --source-root "$UPSTREAM_SOURCE_ROOT" \
  --scratch-root "$PROBE_ROOT" --device "$APPROVED_GPU_UUID"
```

正常完成监督后，结果写入该目录的 `result.json`；早期参数/目录拒绝或文件写入失败时，
可能只有命令的结构化输出，不能假定结果文件存在。创建 `attempt.json` 后不允许复跑同一路径。
目录及结果保持私有。失败、超时或费用/资源事实不明时停止，不自动重试、增大预算或换设备。
此脚本不安装包、不下载模型/数据、不访问 provider；worker 使用固定清洁环境。

## 限额的实际含义

| 项目 | 初始限制与范围 |
|---|---|
| 执行 wall | 300秒采样监督阈值；停止确认另有两个至多5秒的等待窗口 |
| CPU | 每进程 RLIMIT_CPU300秒；原进程组 CPU 另做采样，非 aggregate 硬配额 |
| 编译并行 | 1线程 / 1 build job |
| 单文件 | RLIMIT_FSIZE256MiB |
| cache | 采样总逻辑字节1GiB、目录深度/entry 限制；不是文件系统硬配额 |
| 输出 | 32KiB，有限阶段与结构化指标 |
| GPU | PyTorch allocator 观察阈值8GiB；不是设备总显存硬上限 |

采样可能漏掉短时峰值，写入可在两次采样之间越过阈值；文件系统扫描本身不受硬 wall 限制。
`workElapsedSeconds` 记录监督阶段，`elapsedSeconds` 另包含停止确认，不包含后续 cache
删除与结果 fsync。需在启动前保留真实磁盘与内存余量，
不能用这些观察值承诺系统总资源绝不会超出。编译子进程也必须停止；主进程退出不构成停止证明。
只有原进程组与被接管子进程都确认消失后才删除 owned cache。无法确认时保留私有 scratch，
标记停止未确认并拒绝成功；交回原 operator，不据此自动清理目录。

## 如何判断下一步

原完整 B1 warmup 为2816个 microbatch 加11次 optimizer update，且发生在训练计时预算前。
完整独立评价为10240次 B1 forward，另有真实输入、checkpoint 与控制面的开销。
两轮短诊断只能给出资源可行性与耗时的初步下界；缓存命中、编译 shape、热状态和真实数据
都会影响后续执行。不能线性外推后宣称完整 warmup/evaluation 已获足够预算。

先审阅实际阶段结果与剩余空间，再制定完整 warmup、训练、独立评价各自 wall 预算。
若300秒内只有部分阶段，保留部分证据，不默认调高额度继续。控制依赖/数据库另见
[控制环境计划](RESEARCH_CONTROL_ENVIRONMENT_PLAN.md)。当前真实 baseline 完成数0，`val_bpb: null`。
