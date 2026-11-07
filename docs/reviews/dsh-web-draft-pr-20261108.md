# Draft PR materials

Title: Improve research chat visibility and fix Windows native file replacement

Proposed base: `feat/native-research-skills-20261107` at `bf8ad58d1b78fd0df66192f4c1455001beb7ffef`, keeping PR #178's changes in their own review.

Proposed head: `codex/dsh-skills-integration-20261108`. Original frontend commit `b552779` and its independent branch remain preserved.

## Change

Research chat follows the local DSH Web layout, folds execution details, and shows actual tool arguments, results, failures, silence, and connection state. The current question reaches the native Agent instead of a fixed plan instruction; SSH hooks persist paired events and long text streams retain tool history. Markdown tables render correctly.

Windows directory handles permit native Workspace child-file replacement while retaining ancestor rename denial. The regression fixture uses the production transport deadline and verifies successful lifespan shutdown. Agno 3.1.0 and PostgreSQL retain execution ownership.

## Verification

All 20 combined regressions pass on Windows with disposable PostgreSQL in 102.661 seconds, including native parent/child files, existing-file editing, exact Chinese-name download bytes, junction escape rejection, long-running Skills, unknown-call non-replay and continuation, both PID Stop paths, SSH disconnect events and lifespan shutdown. Frontend lint/types/build, Ruff, Pyright and whitespace checks pass. Independent review finds no source blocker.

The existing OpenCode Go subscription completes the exact SSH question with discovery and two read-only calls, both exit 0. A second real session creates, edits and reads a Chinese file. Desktop and narrow UI evidence is separate from scripted regressions. See [integration and evidence notes](dsh-web-integration-20261108.md).

## Not verified

Live Edge download acceptance stops after download waiting times out and Computer Use cannot reliably establish the native window URL, despite confirming the target tab. Combined real-provider and SSH acceptance remains pending that recovery. Both old and current guards permit empty-directory junction conversion via write-attributes access; they are not an OS sandbox. Windows TLS/RST and existing CSS/bundle warnings remain.

## Next step

Review the [combined integration evidence](dsh-skills-integration-20261108.md), restore reliable browser URL recognition, and complete the real-provider/SSH/file-delivery journey. Keep the PR draft pending that acceptance. Remote push and PR creation await explicit authorization; neither has been performed.
