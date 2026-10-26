# Production Windows implementation evidence

当前安装结果见 [精确提交验收](verification-installed.md#current-result--2026-10-26)：`445a2ce` 的实际 Windows 两消费者、pin、取消、撤权与清理通过；下文为保留的实施阶段记录。最终 full 待运行，Windows→Linux 原操作恢复仍 BLOCKED。

Design 2e40205 independently approved before production code; Unicode child-cwd extension 4fb53b0 independently approved before use. Stage A and B mechanism results are in their separate change directories; neither replaces installed-product or Windows-to-Linux acceptance.

The credential/guard tests explicitly fake Windows OS calls. First run: 7/7 passed, 0.194s (`/tmp/af-windows-credentials-portable-first.log`), covering missing-client before secret access, expiry/revocation, one release, capacity, guard at release, concurrent close during initialization and cleanup-error slot release. After child-only cwd and cleanup/type-boundary edits, 7/7 passed, 0.101s (`/tmp/af-windows-credentials-portable-second.log`). No PG, real credential or remote host was used.

Initial targeted Linux Pyright reported 20 errors/8 Windows-source warnings, including pywin32 stubs that incorrectly type owned handles as int, overlapped ReadFile's buffer interface, Windows-only ctypes declarations and in-progress low-level API attributes. These are retained in `/tmp/af-windows-credentials-pyright-first.log`. Corrections use explicit owned HANDLEType casts at the actual public API boundary, integer native handle values for functions requiring them, AllocateReadBuffer for asynchronous reads, Buffer for its real buffer protocol, and explicit Windows platform guards for ctypes functions. No global type-check suppression. Full final Linux/Windows static checks remain coordinator-owned after all modules freeze.

Actual Windows installed-core carrier authentication, Unicode/long carrier directory, concurrency, cancel/revoke/close and final cross-machine Linux helper acceptance are NOT RUN here. The seven portable tests do not satisfy those gates.

## Independent cleanup review correction

Review of 9bf8977 found that unconfirmed cleanup discarded its active record and signalled completion, allowing later admission and a misleading successful manager close. The original seven-test result remains above; its cleanup-error expectation was wrong and is not evidence that failure containment worked. Spec 24f688d precedes the correction: retain failed carrier records, close the manager to admission, reject acquire before vault resolution, use SSHExchangeCleanupError with a fixed code, attempt every remaining original carrier after one kill failure, and do not retry known failed cleanup. Completion of a cleanup attempt is distinct from confirmed success. `cwd` now passes the string required by the frozen low-level API.

New targeted run: 9/9 passed, 0.106s, then two narrow implementation refinements retained/propagated close-time failures and prevented repeating failed kills. Frozen code: 9/9 passed, 0.054s (`/tmp/af-windows-credentials-cleanup-frozen.log`). Counterexamples require zero new secret resolution/spawn after cleanup failure, close reporting failure, and the second original carrier still receiving kill/wait when the first kill fails. Known failed cleanup is not automatically retried. Ruff and diff checks passed; targeted Linux Pyright is now 0 errors/8 missing-Windows-source warnings (exit 0). These are portable fake-OS checks, not Windows process cleanup proof.


## Installed helper creation failure and fixed local filename candidate

Actual exact `6bef62d` run `40246110498` (`/tmp/af-installed-core-numeric.json`) failed: installed helper present, support import exit 0, direct invalid-prompt exit 1; system SSH reported NOT_FOUND and CreateProcessW error 2, then broker PIPE_DEADLINE before identity or password transfer. Cleanup succeeded. This report and the first two installed failures are retained; it narrows the failure to SSH creating the helper without proving a particular encoding conversion.

Spec `5b838e1` received independent design PASS before implementation. The candidate copies the fixed installed helper bytes into the protected invocation directory, uses `SSH_ASKPASS=./askpass.exe` with the existing child cwd, and authenticates that exact copied image with the unchanged original SSH/interpreter chain. It does not rewrite the launcher, change system locale, relax identity or use an alternate credential path.

Portable scope tests: 9/9 passed in 0.102s, zero skips (`/tmp/af-windows-helper-relative-portable.log`). The normal-scope test now checks byte-identical helper contents, fixed relative environment value and the exact helper passed to the original identity checker, along with prior one-release and file-cleanup assertions. Ruff and diff checks passed; targeted Linux Pyright reports 0 errors and 8 existing missing Windows-source warnings (`/tmp/af-windows-helper-relative-pyright.log`). These fake-OS checks do not demonstrate launcher relocatability or Windows authentication. The actual installed Windows suite with Unicode-and-space parents remains pending; its original two-consumer/pin/cancellation/cleanup oracle is unchanged. Windows-to-Linux original-operation acceptance remains separately BLOCKED.


## Space-containing known-hosts option

Actual run `40246732528` at `e3934e9` failed with hostKeyRejected=true before authentication, no ASKPASS spawn error and no broker identity/transfer; both helper/carrier parents contained Unicode and spaces. Direct import/invalid-prompt checks still exited 0/1. Cleanup succeeded. The report `/tmp/af-installed-core-relative.json` is retained and does not establish that helper relocation worked.

Spec `500965d` independently passed before the single-option correction to `UserKnownHostsFile=known_hosts`. Official v9.5.0.0 readconf.c tokenizes the option's value as filename entries; [hostfile.c](https://github.com/PowerShell/openssh-portable/blob/v9.5.0.0/hostfile.c) load_hostkeys directly opens each supplied path, so the fixed filename uses the existing owned child cwd. Original host alias, strict checking, global-file exclusion and exact pin content are unchanged.

Targeted portable checks passed 9/9 in 0.073s, zero skips (`/tmp/af-windows-relative-knownhosts-portable.log`); Ruff and diff checks passed. The normal-scope assertion now checks the sole fixed known-hosts option, all three strict trust options and exact file line. This is fake-OS wiring evidence, not real host authentication. Both original actual Windows consumers and wrong-pin zero-release remain required; no timeout or acceptance assertion was relaxed.
