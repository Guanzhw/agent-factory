# Production Windows implementation evidence

Design 2e40205 independently approved before production code; Unicode child-cwd extension 4fb53b0 independently approved before use. Stage A and B mechanism results are in their separate change directories; neither replaces installed-product or Windows-to-Linux acceptance.

The credential/guard tests explicitly fake Windows OS calls. First run: 7/7 passed, 0.194s (`/tmp/af-windows-credentials-portable-first.log`), covering missing-client before secret access, expiry/revocation, one release, capacity, guard at release, concurrent close during initialization and cleanup-error slot release. After child-only cwd and cleanup/type-boundary edits, 7/7 passed, 0.101s (`/tmp/af-windows-credentials-portable-second.log`). No PG, real credential or remote host was used.

Initial targeted Linux Pyright reported 20 errors/8 Windows-source warnings, including pywin32 stubs that incorrectly type owned handles as int, overlapped ReadFile's buffer interface, Windows-only ctypes declarations and in-progress low-level API attributes. These are retained in `/tmp/af-windows-credentials-pyright-first.log`. Corrections use explicit owned HANDLEType casts at the actual public API boundary, integer native handle values for functions requiring them, AllocateReadBuffer for asynchronous reads, Buffer for its real buffer protocol, and explicit Windows platform guards for ctypes functions. No global type-check suppression. Full final Linux/Windows static checks remain coordinator-owned after all modules freeze.

Actual Windows installed-core carrier authentication, Unicode/long carrier directory, concurrency, cancel/revoke/close and final cross-machine Linux helper acceptance are NOT RUN here. The seven portable tests do not satisfy those gates.
