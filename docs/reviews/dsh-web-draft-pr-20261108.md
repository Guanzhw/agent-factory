# Draft PR #179

Title: Improve research chat visibility and fix Windows native file replacement

Published review: [Draft PR #179](https://github.com/Guanzhw/agent-factory/pull/179).

Base: `feat/native-research-skills-20261107` at `93119b30ac8f3a8f43881c6cef277ba71518779b`. Head: `codex/dsh-skills-integration-20261108`. Original frontend commit `b552779` and its independent branch remain preserved.

## Change

Research chat follows the local DSH Web message hierarchy, folds execution details, and shows actual tool arguments, readable results, failures, silence and connection state. Messages and code have clipboard controls; code supports wrapping and empty fences. A growing model-labeled composer keeps Stop nearby, and return-to-bottom restores following after reading history. The current question reaches the native Agent; native hooks persist paired tool events and long text streams retain tool history.

Windows directory handles permit native Workspace child-file replacement while retaining ancestor rename denial. The regression fixture uses the production transport deadline and verifies successful lifespan shutdown. Agno 3.1.0 and PostgreSQL retain execution ownership.

## Verification

All 20 combined regressions pass on Windows with disposable PostgreSQL in 102.661 seconds, including native parent/child files, existing-file editing, exact Chinese-name download bytes, junction escape rejection, long-running Skills, unknown-call non-replay and continuation, both PID Stop paths, SSH disconnect events and lifespan shutdown. Frontend lint/types/build, Ruff, Pyright and whitespace checks pass. Independent review finds no source blocker.

That earlier complete run applies to integrated base `0997f8e`. The latest #178 file-list contract `{files, errors}` is integrated with its matching component. The final complete suite passes 21 cases in 113.536 seconds using default Windows encoding, including real ACL partial-list failures, accessible byte-exact downloads, recovery, copy/wrap/empty-code controls, growing composition, retained-fragment scrolling, narrow Stop visibility and native Skills read events.

The existing subscription completes a combined task with native SSH exit 0 and a 34-byte Chinese file create/edit/read cycle in 20 seconds. Actual Edge verifies code copying and narrow input/layout; refresh retains the completed turn. Earlier exact-question SSH acceptance and the 40-byte file session remain separate evidence. See [combined notes](dsh-skills-integration-20261108.md).

That live run also exposes missing native Skills read events. Native Function hooks now save original read arguments/results while keeping script command records unique. The focused native journey passes in 74.608 seconds, and a real provider follow-up completes in 12 seconds with two visible instruction/reference calls and full returned documents. Independent review finds no source blocker.

The follow-up SSH review finds and corrects pre-dispatch failures mislabeled unknown. The seven-case native boundary journey passes in 52.293 seconds; the final full Windows suite passes 22 cases in 124.087 seconds. Native typed argument errors and confirmed rejection are failed, while cancellation, dispatched loss and later cleanup errors remain unknown. Frontend checks, Ruff and Pyright pass. Independent final review finds no remaining issue.

## Not verified

Real Edge delivery is verified after manual Save: 34 bytes match the session source and SHA-256; the temporary file disappears. The earlier event timeout and browser-control limitations remain historical evidence. Both old and current directory guards permit empty-directory junction conversion via write-attributes access; they do not provide OS isolation. Windows TLS/RST and existing CSS/bundle warnings remain.

## Next step

Hand the corrected stack and exact-head CI to cloud Codex for governance and merging. Preserve #178's ancestry before retargeting #179 to main, and verify the resulting merge and checks. Local work does not perform the merge. See [combined integration evidence](dsh-skills-integration-20261108.md).
