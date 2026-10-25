# Owned process verification

The first actual Windows isolated run at `3d71479`, [run 40242604328 / job 121317437862](https://github.com/Guanzhw/agent-factory/actions/runs/40242604328/job/121317437862), executed 58 tests in 5.805s: 57 passed and one errored. Eight of the nine new owned-process tests passed, including unrelated inheritable-handle exclusion, concurrent stdio isolation and Job cleanup. This was not a passing job.

The remaining error was in `test_spawn_failure_does_not_leak_parent_handles`: `win32process.GetProcessHandleCount` does not exist. The fixture now calls the [documented Kernel32 GetProcessHandleCount](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesshandlecount) with HANDLE / DWORD pointer / BOOL types. It retains the exact before/after equality assertion over three failed spawns.

The independently approved child-only cwd extension (design `4fb53b0`) is implemented by passing `cwd` directly into CreateProcessW. Its additional actual-Windows test creates a Unicode directory longer than 100 UTF-8 bytes, reads the relative `identity` file in the child, verifies the child's real cwd and verifies the parent cwd is unchanged. This test does not prove OpenSSH authentication or the full credential carrier.

Local verification: Ruff and diff whitespace check passed. Targeted Pyright under both Linux and Windows platform selections reports zero errors and six missing native-module-source warnings on this Linux machine. Platform-dependent ctypes/msvcrt access is isolated in narrow typed functions; the constructor's ownership fields remain visible to static analysis without disabling checks. Linux unittest collection reports ten explicit Windows skips, not Windows execution. Actual Windows rerun of the repaired fixture and new cwd test is pending the coordinator's isolated CI run.

## Strict leak failure and next distinguishing experiment

Actual Windows rerun at `954e12e`, [run 40243161425 / job 121319091800](https://github.com/Guanzhw/agent-factory/actions/runs/40243161425/job/121319091800), ran 59 tests in 3.613s: 58 passed and one failed. The Unicode child-cwd test passed. The unchanged strict failed-spawn handle assertion observed 251 versus 244 (+7). This remains an unresolved failure, not an accepted cache allowance.

The next experiment retains the original initial/final equality and three failed constructors, adding only diagnostic counts before/after each call and around the real error-construction and cleanup functions. A separate fresh Python child, started only after capturing the original final count, constructs `ctypes.WinError(2)` three times without importing or creating WindowsSSHProcess, recording its own counts. The original measurement is not warmed up, garbage-collected or rebased. This distinguishes persistent growth per failed spawn, growth during error formatting, and incomplete cleanup; a one-time delta alone does not prove harmless caching. The separate control has a fixed ten-second limit and fixed tiny JSON output.

Python documents WinError as formatting a Windows error through FormatError; Microsoft documents system message-resource lookup in FormatMessageW. Neither promises a particular process handle-count delta. Any attribution must come from actual measurements, and a product fix must subsequently pass the original strict gate.
