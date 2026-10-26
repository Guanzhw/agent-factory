# Installed Windows core: current result and retained failures
## Current result — 2026-10-26

精确提交 `445a2ce89ab2fe38d8269d3f1f6a17bed9a81024` 的
[Windows run 40247109502](https://github.com/Guanzhw/agent-factory/actions/runs/40247109502)
三组均成功；portable-pipes 为 60/60，零跳过，3.838s。
已实际读取 [installed artifact 12619048198](https://github.com/Guanzhw/agent-factory/actions/runs/40247109502/artifacts/12619048198)：

| 安装后检查 | 实际结果 |
| --- | --- |
| 两个消费者 | PASS；nonce 匹配，两次成功释放；原 broker 身份、READY 和 receipt 检查均完成 |
| 错误 host pin | PASS；零凭据释放，原 SSH 退出 255 |
| 原请求取消 | PASS；一个原客户端，确认收到原请求 |
| 过期与撤权 | PASS；零新客户端、零凭据解析 |
| 路径与来源 | 独立 core 0.2.0、isolated Python；实际 helper/carrier 父目录均有 Unicode 和空格 |
| 清理 | 原客户端/helper/server 停止，broker 无残留线程，fixture 与 fresh environment 删除 |

同 SHA 的 [fast 40247109535](https://github.com/Guanzhw/agent-factory/actions/runs/40247109535) 成功。
这关闭所测系统 OpenSSH 与 uv 安装路径的 helper 创建及 known_hosts 故障，不宣称任意 installer/launcher 兼容。下面四次失败仍是 FAIL。
最终 full 尚未运行。Windows→Linux 原 submit/recovery/cancel 仍为 BLOCKED（未提供授权 Linux endpoint）；
受控 Windows ForceCommand 不是真实 Linux helper。真实模型/GPU/生产 IdP/Acetamido 部署均未验收。

## Historical failures and acceptance design

These are actual Windows installed-wheel runs, not the earlier probe. All three failed before any consumer case completed. The safe reports were retrieved by the coordinator from these runs; no older rejected artifact access was retried. The recorded failures remain FAIL, not BLOCKED or a successful authentication claim.

| Run / tested commit | Observed result | What it establishes |
| --- | --- | --- |
| [40244764651](https://github.com/Guanzhw/agent-factory/actions/runs/40244764651), `f8d59fbf4662d7824cfb338058d6b35e48d7da19` | FAIL at `PRODUCTION_CONSUMERS`, `RemoteConnectionError`, no completed cases | Fresh standalone core 0.2.0 and installed helper provenance, isolated Python, foreground sshd configuration exit 0 and readiness passed. Error class alone does not locate authentication or command failure. |
| [40245602983](https://github.com/Guanzhw/agent-factory/actions/runs/40245602983), `880474f210fbb5ee917da3c90fcab604bb70d9fd` | FAIL at `NORMAL_PROBE`; acquisition/process creation/resume complete; broker connect times out with `PIPE_DEADLINE`; SSH exits 255 | No identity-check or transfer entry. Permission-denied and the broad ASKPASS log marker are present; no authentication/remote-command marker. The broad marker alone does not identify an executable-path or Unicode cause. |
| [40246110498](https://github.com/Guanzhw/agent-factory/actions/runs/40246110498), `6bef62d54229da12dc5ba812ee5e3a898bb7985d` | FAIL at `NORMAL_PROBE`, same pre-connect boundary; fixed `posix_spawnp` observation `NOT_FOUND`, Windows spawn error `2` | Installed helper file exists, isolated support-module import exits 0, direct invalid-prompt helper exits 1. This distinguishes the SSH-to-helper creation boundary from a missing installed module/helper. No identity/transfer call occurs. It does not by itself prove the proposed encoding explanation or exclude all other launch-path causes. |

All three report `fixtureReady=true`, `cases={}`, `ownedFixtureRemoved=true` and `freshEnvironmentRemoved=true`. The last two also report no remaining broker thread after cleanup. This confirms the observed fixture cleanup, not successful normal/cancel/revoke consumer acceptance. Windows-to-Linux original-operation recovery remains separately BLOCKED because no authorized Linux endpoint was supplied.

Local evidence supplied by the coordinator: `/tmp/af-installed-core-first.json`, `/tmp/af-installed-core-diagnostic.json`, `/tmp/af-installed-core-numeric.json`. Diagnostic-only changes were spec-first and independently reviewed. Their Linux parser smoke/Ruff results do not substitute for Windows authentication. Private SSH logs were bounded to fixed metadata; raw logs and credentials are not delivery artifacts. Added verbose logging can affect timing, so the instrumented runs are not claimed to be timing-equivalent to the first run.

## Post-repair acceptance required at the failed checkpoint

After the separately reviewed production fix, run the same installed-wheel acceptance once on its exact commit. Do not repeat the unchanged failed product to obtain a green result. Retain all existing normal probe and transport nonce checks, wrong-pin zero-release and original SSH exit checks, actual provider cancellation with received original request, expiry/revocation before resolution, original client/helper-handle completion and owned cleanup. Preflight success is not a replacement for either consumer.

Use one fresh environment parent containing both the existing repeated Unicode component and a literal space. Use that same owned parent for TEMP/TMP and carrier creation. Assert/report the actual installed helper path and actual carrier parent each exercise Unicode and spaces; checking only the requested parent would miss a system short-path substitution. Keep the existing long-path exposure rather than shortening paths or choosing an ASCII alias. This combines relevant path properties in the current case instead of multiplying the full matrix. If the production design deliberately uses a safe executable token with a separate Unicode path channel, assert the original installed helper/carrier provenance and actual successful broker identity/release; do not mislabel that as an unchanged absolute ASKPASS argument.

The controlled ForceCommand remains a Windows protocol endpoint, not the actual Linux helper. New runtime outcomes must establish broker connection, original identity validation, successful credential release and both consumer responses before claiming this installed path works. If launch succeeds but a later boundary fails, preserve the new first failure and diagnose that boundary without weakening its oracle. No new credentials, services, accounts, GPU/model calls or deployment exposure are part of this check.

## First relative-launcher candidate run: earlier host-key failure

[Run 40246732528](https://github.com/Guanzhw/agent-factory/actions/runs/40246732528), candidate `e3934e9`, remains **FAIL**, with no completed cases. Safe report `/tmp/af-installed-core-relative.json` confirms both actual installed-helper parent and carrier parent contain Unicode and spaces, fresh isolated core provenance, support import exit 0 and direct invalid-prompt helper exit 1. Foreground fixture startup succeeds.

At `NORMAL_PROBE`, acquisition, original SSH creation and resume complete; SSH exits 255. The bounded log now positively records host-key rejection, with no authentication, permission-denied, ASKPASS or remote-command marker. Broker connection times out before identity/transfer. Owned fixture/fresh environment removal succeeds and no broker thread remains after cleanup.

This run fails at an earlier prerequisite than the previous ASKPASS spawn failure. It provides no successful execution evidence for the copied launcher and does **not** establish that the ASKPASS defect is repaired. The new space-containing known-hosts option and its SSH internal parsing are under separate source review; the observed host-key rejection alone does not prove that explanation. The runner, original host-pin oracle and complete consumer cases remain unchanged pending the separately reviewed product correction. No extra rerun was performed by this evidence task.
