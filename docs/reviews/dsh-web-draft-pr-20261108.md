# Draft PR materials

Title: Improve research chat visibility and fix Windows native file replacement

Base: `main` at `15e192b24d03aba10c14983ee30461d24e554b95`

Head: `codex/dsh-chat-observability-windows-20261108`

## Change

Research chat follows the local DSH Web layout, folds execution details, and shows actual tool arguments, results, failures, silence, and connection state. The current question reaches the native Agent instead of a fixed plan instruction; SSH hooks persist paired events and long text streams retain tool history. Markdown tables render correctly.

Windows directory handles permit native Workspace child-file replacement while retaining ancestor rename denial. The regression fixture uses the production transport deadline and verifies successful lifespan shutdown. Agno 3.1.0 and PostgreSQL retain execution ownership.

## Verification

All seven minimal regressions pass on Windows with disposable PostgreSQL in 63.343 seconds, including native parent/child files, existing-file editing, exact Chinese-name download bytes, junction escape rejection, Stop, and lifespan shutdown. Frontend lint/types/build, Ruff, Pyright, and whitespace checks pass. Independent review finds no source blocker.

The existing OpenCode Go subscription completes the exact SSH question with discovery and two read-only calls, both exit 0. A second real session creates, edits and reads a Chinese file. Desktop and narrow UI evidence is separate from scripted regressions. See [integration and evidence notes](dsh-web-integration-20261108.md).

## Not verified

Live Edge download acceptance stops after download waiting times out and Computer Use cannot reliably establish the browser URL. In-place reparse mutation comparison is inconclusive. Windows TLS/RST and existing CSS/bundle warnings remain. Combined execution with cloud PR #178 has not run.

## Next step

Review the shared-file integration notes before combining with [Draft PR #178](https://github.com/Guanzhw/agent-factory/pull/178). Retain its native Skills and unknown-result changes alongside this branch's current-message, event, and Windows fixes. Keep the PR draft pending combined acceptance. Remote push and PR creation await authorization.
