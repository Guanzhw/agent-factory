# Independent review — bounded pipe and existing consumers

Reviewer: `assistant_messages`, independent of these implementation authors.

| Exact scope | Conclusion / correction |
|---|---|
| Base `d3ec92fd448ad6e4a4efdb633c01df84dc0c50ba` → module `8189be1b920a445fd1cacaa22ddde7a333f980d0` (implementation `1392939`) | Full module diff PASS. |
| Consumer integration `31b5502` | Initially BLOCKED: async freshness guards could be discarded; cancellation cleanup failures could be swallowed. This was not approved. |
| Correction `48025fc`, four regressions `a4c0aec`, reviewed through `88118b2b09e2826ca20cbb759102b599434a3e3c` | Independent re-review PASS: reject async guards and retain cleanup failure. |
| PR137 fixture spec `175` / code `ec01`, applied here as `48998cb` / `fff64a1` | Independent review PASS for explicit remote POSIX fixture paths and Linux-only helper collection boundary. Not a new Windows execution PASS. |

Commit sources: [module](https://github.com/Guanzhw/agent-factory/commit/8189be1b920a445fd1cacaa22ddde7a333f980d0), [consumer review head](https://github.com/Guanzhw/agent-factory/commit/88118b2b09e2826ca20cbb759102b599434a3e3c).

These reviews cover the bounded exchange and its existing consumers, not Windows credential custody or complete Windows SSH support. Current Windows validation is incomplete; the first runner failure and corrected fixture scope are preserved in verification.md.

## Subsequent platform evidence (not a new source-review claim)

Exact `dc1fead` portable Windows job [121308976958](https://github.com/Guanzhw/agent-factory/actions/runs/40239805493/job/121308976958)
passed 49/49, zero skips, 2.905s. Three explicitly selected portable classes exclude
the actual Linux helper; its Linux 16/16 result is separate. This closes the
bounded-pipe Windows runtime check, not the failing ASKPASS job or overall Windows
SSH acceptance. The old d3 full Windows failure includes concrete WinError10038
from selectors on a pipe; see verification.md for the retained first evidence.


## Final PR137 cumulative and incremental review

Reviewer: `assistant_messages`, independent of the bounded-exchange and consumer implementation authors. These are the prior read-only review conclusions, recorded without another test run.

- **Cumulative PASS:** main `e7987e75ac4659cff9f1d7fee63150d68583941d` → `1448bb9c82732764f8964edd2abd3784ce15d49a`. The base is an ancestor. The `platform`, `deployment` and `applications` trees (including their tests) are byte-identical to reviewed integration `13b9431248a199b937eca88945350cab899e78a3`. Dependencies, lockfile and workflows are unchanged from this main base; no ASKPASS candidate is included. The backport contains the reviewed module, consumers, four regression checks, explicit POSIX replacement and Linux-helper fixture boundary. Simplicity remains one synchronous I/O owner, with no additional executor, I/O thread, retry loop or recovery controller.
- The earlier consumer blockers remain part of the review history: a discarded awaitable freshness result and hidden cleanup error were rejected at `31b5502`, then corrected at `48025fc`. Tests at `a4c0aec` cover direct async-guard rejection before spawn, the original cleanup exception, repeated cancellation waiting for the same worker, and cleanup failure taking precedence over cancellation. The cumulative PASS includes those corrections; it does not retroactively approve the rejected version.
- **Incremental PASS:** `1448bb9c82732764f8964edd2abd3784ce15d49a` → final code head **`860e46090dc98f6b2160da4cbc3b7d9de17aa775`**, with specification clarification `2900609` preceding implementation. The real Linux loopback check exposed a nonzero SSH exit now surfacing as `CalledProcessError` instead of the original `ValueError`. The narrow transport mapping restores `SSH_PROCESS_PROTOCOL_INVALID` and retains the cause; it does not catch cleanup errors, cancellation, timeout or other OS errors, retry dispatch, or accept the wrong host pin. The original assertions were retained. The recorded corrected helper result is 1/1 passed, zero skips, 9.512s; the initial failure remains in verification.md.

At this recording, [full CI 40241711220](https://github.com/Guanzhw/agent-factory/actions/runs/40241711220) is still running on exact code head `860e46090dc98f6b2160da4cbc3b7d9de17aa775`. These source-review PASS conclusions do not assert that full CI has passed. Earlier d3 full results are not final-head acceptance. The Windows 49-case pipe result remains distinct from ASKPASS/credential custody and complete Windows SSH acceptance.
