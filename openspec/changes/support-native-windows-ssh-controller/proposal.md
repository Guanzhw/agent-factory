## Why
The deployment controller is native Windows Acetamido. Linux-only ssh-agent sockets and POSIX process assumptions currently prevent its supported remote Linux execution path. Real Stage A has validated per-call encrypted keys and authenticated ASKPASS IPC on system OpenSSH 9.5p2; Stage B authentication has a retained first failure and is not yet accepted.

## What changes
Add one Windows-specific credential/process carrier to existing SSH enrollment and pinned transports. Reuse the existing vault, scope guard, bounded ssh_exchange, remote Linux helper and original-operation journal. Preserve the Linux agent path. No WSL, new remote controller, global agent service, new credential grant or account/security setting.

## Impact
Core SSH identity/lease/process modules, both pinned process consumers and standalone packaging plus focused Windows tests. Production implementation follows independent design review and accepted mechanism evidence; this proposal is not a deployment or a claim of actual Windows-to-Linux/GPU acceptance.
