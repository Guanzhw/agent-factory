## Why
Native Windows is a deployment target, but the current controller uses POSIX agent sockets and pipe polling. Before implementing a Windows credential path, test whether the installed system OpenSSH key loader can read a creation-time protected, delete-on-close private key. Upstream source predicts a sharing incompatibility; a negative result is useful evidence, not permission to weaken protection.

## What Changes
- Add a standalone Windows-only synthetic-key probe, without product integration or network access.
- Test actual system ssh-keygen key loading and normal/forced keeper-process cleanup.
- Report safe structured results distinguishing rejected candidate from broken experiment.

## Impact
Test tooling and documentation only. No agent service, persistent credential, system configuration, dependency, or SSH connection changes.
