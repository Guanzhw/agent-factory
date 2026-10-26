## Why
The deployment controller is native Windows Acetamido. Linux-only ssh-agent sockets and POSIX process assumptions currently prevent its supported remote Linux execution path. Real Stage A has validated per-call encrypted keys and authenticated ASKPASS IPC on system OpenSSH 9.5p2; Stage B actual system SSH authentication now passes on isolated probe head 8848b53, with both earlier command failures retained.

## What changes
Add one Windows-specific credential/process carrier to existing SSH enrollment and pinned transports. Reuse the existing vault, scope guard, bounded ssh_exchange, remote Linux helper and original-operation journal. Preserve the Linux agent path. No WSL, new remote controller, global agent service, new credential grant or account/security setting.

## Impact
Core SSH identity/lease/process modules, both pinned process consumers and standalone packaging plus focused Windows tests. Production implementation follows independent design review and accepted mechanism evidence; this proposal is not a deployment or a claim of actual Windows-to-Linux/GPU acceptance.

## 2026-10-26 audit corrections
整改基线为 `94c59e5954f5acacb039a73fa3332381fd542fe2`：修正认证 broker 提前消耗独立六秒预算、仅密文残留就关闭共享 manager，以及两平台固定 SSH 参数分叉。顺带修复早于 PR104、由 PR137 新训练消费者继承的 POSIX 空格路径解析缺陷；不把它记成 PR138 引入。候选认证探针改按需运行，实际 installed-core 和原安全断言继续默认执行。沿用系统 OpenSSH、现有 vault、原任务与取消路径，不换协议库或新增恢复框架。旧失败和旧版本 PASS 保持原归属，整改尚未验收。
