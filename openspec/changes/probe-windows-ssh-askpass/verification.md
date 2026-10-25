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

## Dependency repair verification

Spec `d57cf00` preceded the repair. The isolated `ssh-probe` group now pins bcrypt 5.0.0; existing locked package versions and runtime dependencies are unchanged. The first lock command could not write the default read-only cache; using a task-owned `/tmp` cache resolved the environment issue without modifying the shared environment.

Installed the hash-checked export of only this group into a separate `/tmp` target, then used the existing cryptography environment: encrypted OpenSSH serialization/round-trip passed, missing password rejected, wrong password rejected (three checks, no key output). `uv lock --check --offline` and `git diff --check` passed. This confirms the fixture encryption prerequisite only; Windows OpenSSH/ASKPASS mechanism is still unvalidated. The probe job must use `uv sync --frozen --group ssh-probe`; product adoption would separately require an explicit production dependency.

## Second Stage A Windows run: job-wrapper argument failure

[Run 40239375015](https://github.com/Guanzhw/agent-factory/actions/runs/40239375015), job 121307679066, [artifact 12616145848](https://github.com/Guanzhw/agent-factory/actions/runs/40239375015/artifacts/12616145848): bcrypt installation and encryption advanced, but no loader was invoked. Safe first result:

```json
{"candidateAccepted":false,"experimentCompleted":false,"cases":{"normal":{"errorType":"TypeError","fixtureComplete":false,"stage":"CREATE_PIPE_JOB","winerror":null}},"sshVersion":"OpenSSH_for_Windows_9.5p2","windowsVersion":[10,0,26100]}
```

A definite argument-contract bug exists in this exact stage: the probe calls `win32job.CreateJobObject(None, None)`, but pinned pywin32 b312 declares the name as ordinary `WCHAR *lpName` ([win32job.i](https://github.com/mhammond/pywin32/blob/b312/win32/src/win32job.i)), whose [SWIG mapping](https://github.com/mhammond/pywin32/blob/b312/SWIG/swig_lib/python/pywintypes.i#L143-L146) explicitly passes `FALSE` for None acceptance. [PyUnicode.cpp](https://github.com/mhammond/pywin32/blob/b312/win32/src/PyUnicode.cpp#L45-L52) raises TypeError for that argument. The retained CI result lacks a traceback and therefore does not independently identify the line; the invalid call is established by the pinned wrapper source. No speculative named-pipe/ACL change is justified.

The repair preserves Win32 NULL-name semantics through typed CreateJobObjectW and an owned pywin32 HANDLE; all job limits/assignment order remain unchanged. CREATE_PIPE and CREATE_JOB now have separate stages. Fixed probe-code locations (module basename, function, numeric line only) are retained without source lines or values. Linux exercised the real safe diagnostic path: expected import failure, empty stdout/stderr, fixed locations, no fixture path/key name in JSON; passed. Ruff, compile and diff checks passed. Actual Windows job creation remains for the reviewed third run; neither earlier failure is relabeled as a mechanism result.

## Third Stage A Windows run: actual helper reached, version/API mismatch

[Run 40239805493](https://github.com/Guanzhw/agent-factory/actions/runs/40239805493), job 121308977189, [artifact 12616061647](https://github.com/Guanzhw/agent-factory/actions/runs/40239805493/artifacts/12616061647), reached real OpenSSH/ASKPASS. Its safe normal-case failure was `AttributeError` at controller -> connect -> wait_io line 160 (`ACCEPT_HELPER`); the actual helper separately recorded `PROMPT_MISMATCH` at `EXACT_PROMPT`. No secret was released. This does not yet validate successful key loading.

Two precise source-backed defects were identified:
- The installed 9.5 family uses exactly `Enter passphrase: ` in [v9.5.0.0 ssh-keygen.c load_identity](https://github.com/PowerShell/openssh-portable/blob/v9.5.0.0/ssh-keygen.c#L293-L313). The probe incorrectly used the later upstream filename-bearing prompt. Correct this Stage A probe to the version-specific exact literal, not arbitrary prompt acceptance.
- Pinned [pywin32 b312 win32file.i](https://github.com/mhammond/pywin32/blob/b312/win32/src/win32file.i#L165-L167) exports CancelIo, not CancelIoEx. The line identified by safe diagnostics called the nonexistent latter attribute. All this probe's operations and timeout waits run on the same issuing thread, so CancelIo(handle) is the narrow documented cancellation operation; retain waiting for completion before releasing OVERLAPPED storage. [Microsoft CancelIo contract](https://learn.microsoft.com/en-us/windows/win32/fileio/cancelio).

Repair verification: Ruff, compile and diff checks passed. Four portable helper-boundary checks with explicitly stubbed Windows IPC confirmed that only the exact 9.5 literal reaches PIPE_OPEN; filename-bearing, arbitrary and confirmation prompts are rejected with empty stdout. These checks validate prompt gating only, not Windows authentication or cancellation. Actual corrected Windows execution remains pending independent review.
