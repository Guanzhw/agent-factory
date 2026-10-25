# Stage B verification

Design 4ccda03 independently approved with classification correction 80e11e5 before implementation. No Windows run yet.

Local checks: Ruff, compile and diff passed. The actual command `python -m af_askpass_probe --stage-b` on Linux returned exit 1 with safe stage B / BLOCKED / WINDOWS_REQUIRED JSON; it did not invoke SSH. Four checks exercised the real helper with explicitly stubbed Windows IPC: exact filename-bound ssh.exe prompt reached PIPE_OPEN, keygen prompt/wrong filename/confirmation were rejected, stdout stayed empty. These validate gating, not Windows authentication.

CLI: installed `af-windows-ssh-askpass-probe.exe --stage-b`. Exit 0 means all three cases accepted; 2 is a measured candidate failure after a usable fixture; 1 is incomplete or an explicitly identified missing prerequisite. JSON includes stage/status/experimentCompleted/candidateAccepted, versions, executable-presence booleans and per-case fixed stages, exit codes, nonceMatched, releases, hostPinRejected, repeatDenied, observed shape and cleanup. Never raw key/passphrase/prompt/path/stdout/stderr. The outer budget is 60 seconds, with a shared 45-second work deadline and bounded owned-job cleanup.

The wrong-pin assertion additionally requires the fixed OpenSSH host-verification rejection marker from a bounded private log; nonzero exit alone is insufficient. The repeat case tests a second IPC request while real SSH authentication runs, not server-induced prompting. A synthetic unencrypted server host key exists only in the protected owned fixture; the client private key remains encrypted. No production credential or global authorized_keys is accessed or modified.
