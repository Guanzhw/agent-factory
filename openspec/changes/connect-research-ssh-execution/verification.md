# Verification — implementation in progress

Base `375a8ea` includes the pending no-demo changes; protocol specs `6c8c64d`, `2cc3d3b`, `b3601ad`, `4c89cca` precede implementation. Strict OpenSpec validation and changed-file Ruff pass. This is not P5/D01 completion.

| Scope | Actual result | Evidence / boundary |
| --- | --- | --- |
| Helper protocol/filesystem | Initial 8 tests pass, 0.032s; original spec pin added, 9 pass, 0.021s | `/tmp/ssh-helper-portable-first.log`, `/tmp/ssh-helper-portable-pins.log`; mocked process adapter, no SSH. |
| Independent helper review | Found cancel-before-original-identity-check defect | Same-owner wrong task/request/spec could receive cancellation before rejection. |
| Regression before fix | 1 test, 3 failing subcases, 0.024s | `/tmp/ssh-helper-cancel-review-first.log`; actual SQLite custody, no process launch; cancellation called before identity rejection. |
| Fix `345a4e3` | 10 tests pass, 0.032s | `/tmp/ssh-helper-cancel-review-fixed.log`; inspect/check precedes cancel, wrong task/request/spec causes zero cancel calls and exact journal bytes unchanged. Independent re-review pending. |
| Provider first collection | 1 import error | `/tmp/ssh-provider-portable-first.log`; test used wrong class name, not a runtime result. |
| Provider `fa4d7e4` | 6 tests pass, 0.054s, exit 0 | `/tmp/ssh-provider-portable-fixed-import.log`; corrected test import to PersistentResourceService, fake exchange with real receipt validation. No real SSH/GPU evidence. |

Current source implements versioned requests, a finite remote helper over original BoundedProcessAdapter custody, and a Factory-side resource provider/SSH transport. Resource effect persistence `1cc1d0a` is integrated. The actual SSH transport, real process/helper restart, PG operation/runtime installation, full native child recovery, evidence read port and research consumer are **NOT RUN / incomplete**. CPU fixtures cannot prove GPU allocation or release; GPU-bearing leases are rejected by this initial provider. Target cluster facts and formal D01 remain BLOCKED.

No existing data was removed, no remote account was accessed, and no credentials or services were installed. Only lightweight local protocol/file/SQLite tests ran; PG and sshd require the coordinator's serial slot. First failures remain in their original logs. No timeout extension or repeat-until-green run was used.

## Transport cancellation review correction

- The first new transport fixture incorrectly patched the selector class shared by asyncio; its error/timeout remains in `/tmp/ssh-provider-cancel-first.log`. The corrected fixture gates only the transport's selector instance and uses real local pipes, without spawning SSH or training.
- Before the product fix, cancellation during the first writable wait and after the first 4096-byte fragment both transmitted the entire 4601-byte submit. Both negative assertions failed (1 test, 2 subcases, 0.028s): `/tmp/ssh-provider-cancel-prefixed-fixture.log`.
- The transport now calls the original freshness/cancellation callback immediately before each fragment and before normal EOF. The same gated cases now leave respectively zero and 4096 bytes, never a complete request. A fully sent or possibly delivered request still requires original-identity reconciliation and holds; this is not a guarantee that cancellation recalls already delivered work.
- Provider + helper portable group: 17/17 pass, 0 skips, 0.139s, exit 0; Ruff and diff checks pass. `/tmp/ssh-provider-cancel-fixed.log`. These are protocol/pipe and local journal tests, not SSH, GPU or production acceptance.
