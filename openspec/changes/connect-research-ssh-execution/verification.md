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

## Resource registration and PostgreSQL metadata

The coordinator ran `test_resource_target_registration`: 5 portable cases passed, 0 skips, 0.003s; Ruff passed. The first command incorrectly used the `platform/tests/...` module path, which resolved the standard-library `platform` module and failed collection; correcting PYTHONPATH/module invocation required no code changes. Independent review of `3f32a22` and host-key namespace change `9681874` passed. This proves registration contracts, not the actual SSH restorer, which was not yet implemented. Host keys are a conservative grouping key, not proof of unique physical GPU or scheduler identity.

After updating the stack to no-demo `d6c8f62`, the coordinator ran `PYTHONPATH=platform:platform/tests FACTORY_TEST_DATABASE_URL=<isolated loopback PG> python -m unittest test_ssh_execution_effect_postgres -v`: 3 passed, 0 skips, 0.891s, exit 0. Log `/tmp/ssh-resource-metadata-pg-first.log`. The fixture uses substitute execution runtime/provider to verify original metadata, old bounded receipts and unknown-effect refusal. No SSH or GPU is exercised. Existing application data was not touched.

## Original operation runtime and personal-connection construction

- `ssh_tool_factory` first 3 portable cases passed (0.009s): original FunctionCall/run, foreign context denial and no model-supplied command. The later explicit-profile/execute-capability form is covered by the current group.
- First runtime projection invocation exited 124 at its 20-second process bound before unittest output; the empty `/tmp/ssh-operation-projections-first.log` is retained. No runner remained. After the profile integration edits, a bounded diagnostic with an eight-second faulthandler timer completed 8/8 in 0.024s without producing a stack. This does not establish the cause of the first import delay.
- Current runtime/tool portable group: 10/10, zero skips, 0.026s, exit 0 (`/tmp/ssh-runtime-personal-binding.log`). Tests cover distinct operation/lease/remote IDs, negative terminal projections, original UNKNOWN with no archive, archive failure, foreign lease rejection, exact personal connection pin/capability and changed-profile/revocation denial. These use controlled ports, not an actual native run or remote process.
- The runtime reuses existing process custody/maintenance, and archives stopped negative as well as successful results before reclaim. Profile and target construction are implemented locally; actual integrated PG/native/sshd/restart evidence remains pending. No GPU enforcement or D01 result is claimed.

## Stopped-before-dispatch and maintenance release corrections

- Independent review found that a PREPARED original journal cancelled before launch has no stdout file. The archive now records `outputState=never_dispatched, output=null` only with exact original never-dispatched stop proof. Other missing output remains an error. A real local SQLite process journal (never launched) → provider cancellation → archival → reclaim case passed first run, 1/1 in 0.025s. Artifact storage is a controlled test port in this portable case; no SSH/native/PG claim (`/tmp/ssh-prepared-archive-first.log`).
- Source integration also found that existing maintenance discards reclaim's immediate response and re-inspects. The old SSH inspect returned COMPLETED after a durable release intent, preventing release. A targeted assertion reproduced this before the fix (1 failure, 0.010s, `/tmp/ssh-release-observation-first.log`). For this CPU provider only, inspect now confirms release from the original durable release intent plus positive original stop evidence; unknown acknowledgements without stop still hold. There is no extra remote allocator/deletion effect or GPU release inference.
- Runtime/provider/tool portable group after these fixes: 20/20, zero skips, 0.131s, exit 0 (`/tmp/ssh-runtime-review-fixes-portable.log`). The new PG original-operation cancel/claim/archive case is prepared but not yet run; it retains the actual existing maintenance and SQL claim path, with native authority explicitly stubbed.

- Serial PG follow-up on the new original-operation claim case passed first run: 1/1, zero skips, 0.565s, exit 0 (`/tmp/ssh-cancel-claim-postgres-first.log`). The existing `observe_lease` and actual SQL `_claim_effect` persisted OPERATION_CANCEL_REQUESTED, then the real never-launched journal was cancelled, archived into the real task artifact store and confirmed RECLAIMED with `capacityHeld=false`. Re-observation kept the original lease and single receipt artifact. Native authority remains an explicit fixture port; this is not native-queue/SSH acceptance. The isolated database cleanup completed and the serial slot was released. The existing Pydantic schema-shadow warning remains in the log.

## Public reclaim archival boundary

Independent review identified that the existing public resource reclaim endpoint could bypass the runtime's pre-release archive. The SSH provider now invokes its injected original-archive callback before **every** RECLAIMED return, including inspect after an earlier uncertain release intent. Missing callback or archive errors reject release; output retrieval cannot recursively invoke the callback. Current runtime/provider/tool portable group: 21/21, zero skips, 0.095s, exit 0 (`/tmp/ssh-release-archive-portable.log`). A targeted actual-PG public reclaim failure→held original intent→successful original archive/inspect test is prepared and awaiting the serial slot; this paragraph does not claim it passed.

- The serial actual-PG public-reclaim follow-up passed first run: 1/1, zero skips, 0.399s, exit 0 (`/tmp/ssh-public-reclaim-postgres-first.log`). With the real resource reclaim endpoint/service and original stopped journal, injected archive failure left `releaseAck=unknown`, `capacityHeld=true`, and zero artifacts. Restoring archival let the original inspect/maintenance persist the one receipt and release the same lease; repeated observation created no artifact or process. The native authority fixture port and no-SSH scope remain explicit. Database cleanup completed and the slot returned to the native integration author.

## Bounded source type checking

The first temporary Pyright config incorrectly used absolute include paths, which Pyright ignored; the process was bounded at 30 seconds (exit 124) and no checker process remained. Its output is retained in `/tmp/ssh-runtime-pyright-first.log`. Correct relative includes for only the operation runtime, provider and tool factory exposed ten typing errors: overly broad profile dataclass fields and unexpressed type narrowing after the existing contract guards (`/tmp/ssh-runtime-pyright-relative.log`). Explicit process dataclass types and narrowing fixed these without changing admission behavior. The corrected bounded run passed with **0 errors, 0 warnings** (`/tmp/ssh-runtime-pyright-fixed.log`). This is targeted type checking, not full-repository static acceptance.
