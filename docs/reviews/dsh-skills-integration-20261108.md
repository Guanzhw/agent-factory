# Local chat and Skills integration

The independent branch `codex/dsh-skills-integration-20261108` combines the local chat and Windows fixes with native research Skills from [Draft PR #178](https://github.com/Guanzhw/agent-factory/pull/178). The original branches and commits remain intact.

| Source | Preserved commit |
| --- | --- |
| Local chat and Windows files | `b5527799a82aed77a6caec59da00577e5a66dd7d` |
| PR #178, native Skills and unknown-result continuation | `bf8ad58d1b78fd0df66192f4c1455001beb7ffef` |
| Latest PR #178, partial-file-list contract | `93119b30ac8f3a8f43881c6cef277ba71518779b` |
| Common base | `15e192b24d03aba10c14983ee30461d24e554b95` |

The initial integration uses a two-parent merge. Only `docs/DEVELOPMENT_CHECKS.md` has a textual conflict. Its resolution keeps both coverage lists and distinguishes historical checks from combined validation. A later merge retains the latest cloud head. The original frontend branch remains intact. The joint branch is published as [Draft PR #179](https://github.com/Guanzhw/agent-factory/pull/179), based on the cloud feature branch. Main is unchanged.

## Shared behavior retained

| File | Combined behavior |
| --- | --- |
| `applications/research/session_tools.py` | Normalized event arguments, native Windows child-file replacement and ancestor rename denial, individual unknown-call non-replay, and independent tool continuation. |
| `applications/research/sessions.py` | Current instruction as the native goal, native end observation, later independent turns, and preserved unknown effects and Stop handling. |
| `platform/agent_factory/runtime.py` | SSH pre/post events and native Skills tool-name reservation. A returned SSH result with `stopped=False` remains unknown and retains its output. |
| `platform/agent_factory/personal_tool_execution.py` | Event arguments, original call identity, non-replay, and independent continuation after unknown output. |
| `tests/test_chat_journey.py` | Both branches' journeys, native Windows PID checks, platform line endings, explicit UTF-8 reads, and an SSH disconnect receipt through the actual native queue/model loop. |
| `docs/DEVELOPMENT_CHECKS.md` | Both coverage lists, separately scoped acceptance records, and actual Windows limitations. |

Native Agno Skills installation, bundled methods, nested references, script execution, ordinary research records and standalone analysis are retained. The current-question change in `NativeBridge.submit`, event retention and all frontend changes remain intact.

## Independent review and corrections

A fresh reviewer reads both source heads and the merged code. Review finds two issues: the cloud skill test assumes LF stderr on Windows, and the local SSH post-hook marks an exit-255 result with unconfirmed process custody completed. The fixture now uses `os.linesep`; the hook keeps the result unknown. The native queue journey checks the unknown event, code, output and visible warning. No further source blocker is found.

The first combined Windows run executes 20 cases in 103.195 seconds. Nineteen pass. The remaining case reads a native UTF-8 file using Windows' default GBK codec. Its assertion now specifies UTF-8. The failed run is preserved outside the repository.

The corrected full run passes all 20 cases in 102.661 seconds, including the 31-second external skill, original-call non-replay and independent follow-up, parent/child file generation and exact download bytes, both actual-PID Stop cases, SSH disconnect presentation, and successful lifespan shutdown. Frontend lint, types and build, Ruff, Pyright and whitespace checks pass. Existing CSS/bundle and Windows TLS/RST warnings remain; successful bounded shutdown does not prove normal closure of every socket. These checks use a scripted provider, not a combined real-provider acceptance.

The existing local HTTPS preview is restarted with the combined code while retaining its PostgreSQL data and configuration. Its `/api/health` returns `ok: true` and `runtime: Agno 3.1.0`. Health is startup evidence; later provider evidence is recorded below.

The latest cloud head adds partial file-list errors. Its matching component is retained. A native Windows ACL denies directory listing while accessible files remain downloadable; restoring access and refreshing recovers the listing. The normal-encoding full suite, including these cases and the chat-detail follow-up, passes 21 cases in 112.939 seconds. Frontend lint/types/build, Ruff and Pyright pass. See [the actual-source chat comparison](chat-detail-fidelity-20261108.md) for the user-visible changes and retained failed attempts.

## Combined live acceptance

The current subscription model completes one combined task in 20 seconds. Native receipts confirm one read-only SSH invocation with exit 0 and the three requested outputs. File receipts confirm creation, replacement and reading of a Chinese-named file with the expected two lines and 34 native-platform bytes. Actual Edge checks verify code copying and narrow composition without document overflow; refresh retains the original completed turn.

That run exposes a missing process record for native skill instruction reads: installed Agno adds its skill Functions outside the selected-tools SSH hooks. The correction attaches native pre/post hooks to those Functions, retaining original arguments and complete native instruction/reference/script-source results. Script execution keeps its existing command records without duplicates. Hook classification uses the same installed Pydantic boolean conversion as the entrypoint, including accepted `execute='false'` reads. Native error results remain failed; cancellation without a result remains unknown.

The new assertions reproduce all three missing read pairs before the fix. The corrected native Skills journey passes in 74.608 seconds with default Windows encoding, including exact read pairs, three unique script executions, native returned errors, missing required arguments and explicitly injected cancellation. One intermediate attempt uses a terminal session snapshot for events appended directly by a fixture; the test now reads the owning persistent event store for those boundary-only checks. That failed attempt remains preserved. A fresh independent source review finds no remaining blocker. Valid-script preparation exceptions before command dispatch retain their existing native path and are outside this resource-read correction.

After restarting the preview with the fix, a real subscription-provider follow-up completes in 12 seconds. Its two visible calls load the bundled instructions and the listed reference. Expanded tool results contain the actual full documents; no remote command, script or file mutation is requested in this follow-up. Refresh preserves two turns with the original five-call SSH/file turn and the new two-call Skills turn. `chat-details-20261108/12-factory-skills-final.png` records the resulting UI.

The final post-hook full suite passes all 21 cases in 113.536 seconds with default Windows encoding. Frontend lint/types/build, Ruff, Pyright and whitespace checks pass. Counted executable/source extensions, including the checked-in SVG asset, total 23,803 physical lines in 142 files, below the 25,000-line limit. The isolated test cluster is stopped after validation; the retained local preview and its PostgreSQL remain running.

## Native reparse evidence

An isolated native Windows test copies a valid mount-point buffer using `FSCTL_GET_REPARSE_POINT`, then uses `FSCTL_SET_REPARSE_POINT` with a zero-length output buffer. It verifies the junction while the guard remains open and reads an unchanged synthetic target sentinel through it.

| Guard | Generic write | Write attributes only | Write data only |
| --- | --- | --- | --- |
| No guard | Junction creation succeeds | Succeeds | Succeeds |
| Original: generic read, share read | Open fails with 32 | **Junction creation succeeds** | Open fails with 32 |
| Current: generic read, share read and write | Succeeds | **Junction creation succeeds** | Succeeds |

Both guards therefore permit in-place junction conversion of an empty directory through `FILE_WRITE_ATTRIBUTES`. Reverting write sharing restores the native file failure and does not remove that route. The current guard passes native Chinese-name creation and editing and blocks ancestor rename with error 32. All synthetic junctions are individually unlinked; the external target retains its single unchanged sentinel. Path validation and sharing flags do not isolate the service from another process with the same OS permissions.

The sandbox baseline fails with access denied. An initial native harness uses an invalid nonzero output buffer and fails with error 87. The corrected native invocation exits 0. Those failed reports remain preserved alongside the successful report in the external evidence directory.

## Real Edge delivery blocker

The browser inventory and bound tab both confirm the existing HTTPS Factory file-acceptance session. Its actual provider result shows one turn, three native file calls, the expected two lines, and a 40-byte Chinese-named file. The link is an ordinary same-origin anchor with a `download` attribute. A diagnostic click yields no matching download request in the captured tab network events; this observation alone does not establish what the browser's download manager did.

A fresh tab is opened at that exact session URL, brought to the front, and checked again. The next native-window access is refused because Computer Use cannot reliably determine the current browser URL on Windows. Browser actions stop immediately. Download-event and helper timeouts from the previous attempt remain failures. No successful real Edge download is claimed.

The later supported Edge tab verifies the exact current combined session URL and clicks its ordinary 34-byte file link while waiting for a download event. The click succeeds, but the event times out after 15 seconds. No native-window workaround or browser security setting is used. Real-provider, SSH and file operations are confirmed separately; real Edge download-manager delivery remains unverified.

Minimum recovery condition: a supported browser download returns a saved path for byte/hash verification. Alternatively, the user can download that exact file manually and supply its saved path. Repeating a tab-level click without a new delivery signal does not establish success.

## Reviewable publication

Draft PR #179 uses `feat/native-research-skills-20261107` as its base and `codex/dsh-skills-integration-20261108` as its head. This keeps #178's changes in their own review while exposing the frontend, Windows and integration corrections as a separate diff. The cloud head is checked before publication. Both PRs remain draft; no automatic merge or force push is performed.

Private logs and synthetic reports stay under `D:/WorkSpace/agent-factory-local/design-evidence/`. They are not source artifacts.
