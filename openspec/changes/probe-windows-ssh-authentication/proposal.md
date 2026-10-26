## Why
Stage A has passed with system OpenSSH 9.5p2 on Windows 10.0.26100, but key loading does not prove actual SSH authentication. Verify that narrow next boundary before implementing the production Windows credential carrier.

## What changes
Extend the existing test-only probe with a bounded Stage B using an already installed foreground system sshd, temporary synthetic host/client keys and the existing runner account. Preserve strict pinning, one-use authenticated ASKPASS IPC and job cleanup. No service installation, account/privilege changes, persistent credentials or product execution path.

## Impact
Only the probe package, its workflow and evidence. Existing Stage A evidence is retained. A missing executable or unavailable privilege is BLOCKED, never grounds for setup escalation or a simulated pass.
