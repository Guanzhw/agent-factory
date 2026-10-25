# Stage A candidate status

Spec `c4c37ad`, independently narrowed by `294ce2f`, preceded implementation. This package is test-only; no product credentials or client path changed.

## Static/package checks

- Ruff and Python compile: passed on Linux.
- Hatchling wheel build with existing environment: passed; wheel is only the `af_askpass_probe` package and its two entry points.
- Non-Windows invocation: safe `WINDOWS_REQUIRED`, `experimentCompleted=false`, exit 1.
- Actual Windows Stage A: NOT RUN. Independent exact implementation review is required before first CI execution.
- Stage B SSH authentication, Linux helper and Acetamido machine acceptance: NOT RUN.

Install the fixture without new dependencies (the frozen Windows project already includes pywin32 and cryptography):

```
uv pip install --python .venv/Scripts/python.exe --no-deps --no-build-isolation ./scripts/windows_ssh_askpass_probe
.venv/Scripts/af-windows-ssh-askpass-probe.exe
```

Cases are normal key loading, a foreign process, repeated request on the same authorized pipe, a connected but stalled helper, and hard termination after a real helper acknowledges receipt of the passphrase. On first failed case, later cases are not run; their absence is not a pass. Exit 2 denotes an observed rejected candidate; exit 1 denotes incomplete instrumentation/prerequisites. The safe JSON and first failure must be retained.

The encrypted key is created using a current-SID protected DACL before bytes are written. The actual fixed helper chain and job teardown still require Windows evidence. The job's suspended-create/assign/resume path is a test implementation, not a claim that it already integrates with the separate asyncio transport. No all-platform process framework, global agent service, real server access or credential grant is introduced.

Before first Windows execution, helper diagnostics were narrowed to a fixed fixture-local `helper-status.json`: fixed stage/code, exception class and numeric Win32 error only. Prompt mismatch is explicit, but the actual prompt/path/secret is never recorded. Controller failures include this safe record. Linux exercised the real helper import-failure path: exit 1, empty stdout/stderr, exact safe `IMPORT_WINDOWS`/`ModuleNotFoundError` record; passed. Ruff/compile/diff passed. This does not execute or validate Windows IPC.

## First Stage A Windows run: fixture dependency failure

[Run 40238734369](https://github.com/Guanzhw/agent-factory/actions/runs/40238734369), job 121305765659, [artifact 12616285205](https://github.com/Guanzhw/agent-factory/actions/runs/40238734369/artifacts/12616285205), failed before OpenSSH invocation:

```json
{"candidateAccepted":false,"experimentCompleted":false,"cases":{"normal":{"errorType":"UnsupportedAlgorithm","fixtureComplete":false,"stage":"ENCRYPT_KEY","winerror":null}},"sshVersion":"OpenSSH_for_Windows_9.5p2","windowsVersion":[10,0,26100]}
```

Root cause verified against installed cryptography source and a local synthetic serialization reproduction: OpenSSH encrypted private-key serialization calls `bcrypt.kdf`; the optional import is absent and cryptography's stub raises `UnsupportedAlgorithm("Need bcrypt module")`. The installed distribution's metadata declares `bcrypt>=3.1.5` under the `ssh` extra. The frozen project had no bcrypt package. This is not an OpenSSH/ASKPASS candidate rejection. No plaintext fallback or mechanism retry was made.
