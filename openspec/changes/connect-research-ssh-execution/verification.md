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
