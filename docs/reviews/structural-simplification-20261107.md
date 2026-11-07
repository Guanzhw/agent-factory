# Structural simplification — 2026-11-07

## Result and counting method

Repository source is **19,174 physical lines in 134 files**, down from the previously recorded 50,658 lines. The target is strictly below 25,000. This removes 31,484 source lines (62.1%). The counts include comments and blank lines, source scripts and archived executable code. They exclude dependencies, documentation, configuration, lockfiles and generated runtime artifacts, using the same scope as the earlier count. Files were deleted and native capabilities reused; source was not compressed or moved outside the count.

| Directory | Physical source lines |
| --- | ---: |
| Platform | 10,978 |
| Research application | 3,953 |
| Frontend | 4,037 |
| Deployment | 189 |
| Shared and root source | 17 |
| Total | 19,174 |

The complete per-file manifest is preserved with the local delivery artifacts. Recount tracked plus nonignored untracked existing source files, using suffixes `.py .ts .tsx .js .jsx .mjs .cjs .css .html .sql .ps1 .sh .bat .cmd`. Deleted paths are not counted.

## Structural deletions

- Chat now submits its goal, context and model connection directly to Agno. Delete material/application creation and publication, composition proposals, reviews, capability manifests and the corresponding execution gates.
- Delete platform fee commitments, local budget scopes, allocations, inherited lifetime ceilings and per-round settlements. Personal models use their provider account directly.
- Delete the custom Workflow custody/control framework and old fixed research run/history/delivery/setup paths. Projects and curated records remain optional tools in chat.
- Delete the added command-child Workflow, background handle API and special UI projection. The existing command helper has no default task deadline and keeps actual full output files.
- Delete the prepared remote-handoff protocol, authority callbacks, leases, process guardian, cgroup/rlimit budgets and interpreter inventory. SSH uses OpenSSH and the existing process helper. The unused remote wrapper was also removed rather than retaining another adapter.
- Delete the Go development/campaign model cluster and unused broker. Keep the real owner model, protocol continuation codec and native streaming. Remove custom proxy grants and use HTTPX environment proxy/TLS behavior.
- Replace custom MCP transport/monitoring with the official MCP SDK and Agno discovery. Keep the thin error-result handling needed by the installed SDK behavior.
- Delete generic manual Factory panels, their API/types/navigation, global polling, deployment manifests, storage administration and unused diagnostic/architecture scripts.
- Delete default command environment clearing and fake home directories. Commands inherit the normal environment; a selected CLI home credential still gets its actual configuration location.
- Delete repeated resource-save consent and SSH host-key confirmation. New SSH connections use OpenSSH known_hosts/accept-new; saved old pins remain readable.
- Replace the long safety/receipt-oriented research prompt with a short autonomous task instruction. Normal pending requests no longer display recovery warnings or internal IDs.

Historical database rows, credentials and user files are not dropped or purged. Manual governance, scheduling, lease and legacy HTTP interfaces are retired; their old clients and examples are deleted. Historical design documents are marked accordingly.

## Existing autonomous-session constraints

Remove Factory tool-call/turn/delegation lifetime budgets, project operation deadlines, the 12K-character context projection and extra model-output/HTTP-body caps. Existing input submission limits use the pinned Codex reference's 1,048,576-character scope rather than per-field 2,000-character limits. Known model windows use native Agno compression/summary handling; unknown capacities are not guessed. Tool previews use the existing approximately 10,000-token default while full output remains available. A preview limit is not a failure of the operation.

Codex is the fixed open-source reference `0ed34eb9ceddc759e283f0d657be9339afc6b25a`, not a claim about hosted deployment limits. No PTY, background-command protocol or other absent feature was added just because Codex has it. SDK, provider and OS boundaries are not described as nonexistent.

## Actual use and static evidence

The entire old test suite and test-only dependencies remain deleted. No replacement suite was written or run. CI runs lint, types and build only; green CI cannot certify runtime behavior.

A local TLS service was started from the simplified code with an independent PostgreSQL database and an ordinary local account. Browser login, model saving, returning to chat, draft retention through Settings and refresh/recovery were exercised directly. Desktop and mobile screenshots were inspected. Long child instructions were subsequently collapsed into expandable details.

The real external model `deepseek-v4.1-flash` completed a repository-independent Python sampling study: **744.438 seconds**, 22 parent tool results, one independently queued child completed and returned its findings, parent continuation integrated corrections, and the conversation ended `idle/completed`. It produced executable experiment code, results and Markdown reports. A command actually waited 35 seconds and exited 0. A **52,198-byte** material was generated, read and searched. This was a working-tree run before the final CLI-environment, SSH and error-presentation edits; the final source has static verification, while a subsequent model call returned 429. This establishes the observed real task, not arbitrary scientific correctness, a 601-second command, or every provider protocol.

A subsequent command-stop scenario was blocked before command dispatch by upstream **HTTP 429**. There was no process PID to stop; this does not establish the latest stop behavior. No model request was silently replayed. The failure path now exposes the upstream HTTP status rather than only a generic task failure.

Python Ruff passed. Pyright reported zero errors and six source-resolution warnings for Windows-only imports on Linux. Frontend lint, TypeScript and production build passed. The dependency lock check passed. Independent source review checked assembly, model ownership, child waiting and cancellation paths; it found and fixed a lost `fresh` reservation value when recovering an interrupted child creation.

## Remaining verification

Real Windows/SSH execution, a 601-second command on this revision, artifact downloads and the command-stop scenario remain unverified. Full browser acceptance should use the final build and the final server revision. The initial PR's older test results and screenshots do not substitute for that work. PR #177 stays Draft and unmerged.

Ponytail is installed through its upstream-documented repository-skill fallback. The global cloud Codex plugin directory is read-only; automatic lifecycle hooks are not installed.

## Follow-up: CLI recovery, SSH discovery and file delivery

This follow-up changes only three concrete gaps found after `b4a8af2`:

- Both personal CLI adapters return the observed exit code, stdout and stderr for a completed nonzero command. Invalid JSON after a completed command also falls back to the real output. These results no longer become UNKNOWN and halt the conversation. Successful structured responses retain their existing shape; uncertain dispatch/cancellation is unchanged.
- `ssh_servers` exposes the existing owner-visible server list to the Agent. Native SSH tool names are reserved before personal tools are assembled, avoiding duplicate names. No user-supplied internal reference is required for discovery.
- Chat shows current session files with direct downloads, including command-created files and files from previous sessions. Downloads reuse the existing owner/session lookup and file opening code, stream binary bytes, and retain UTF-8 filenames. Directory read failures are reported explicitly. These are current workspace files, not immutable artifact snapshots.

Actual use on Linux/PostgreSQL with the configured DeepSeek model completed session `a5629ed4-0bf2-4712-91e1-86c8dff2c01c`: the configured personal CLI returned exit 7 with both diagnostic streams, the Agent continued to its successful call, discovered the configured SSH server itself, and wrote `结果.txt`. The ordinary browser downloaded that 1,969-byte file. A previous real research session's 52,198-byte `material.txt` also downloaded with an identical SHA-256. Anonymous listing returned 401; a parent-directory download returned 404. The separately registered CLI adapter was manually invoked with actual subprocesses: exit 7 and exit 0 with non-JSON stdout both retained their output.

SSH discovery passed, but remote execution did not: OpenSSH returned 255 because this environment's `/etc/ssh/ssh_config.d/20-systemd-ssh-proxy.conf` resolves to a file owned by `nobody:nogroup`. No system ownership was changed and no remote success is claimed. The Agent recorded this failure and still completed the local result file.

Independent code review found and resolved tool-name collision and silent directory-read errors. Ruff passed; Pyright reported zero errors and the existing six Windows-only import warnings. Frontend lint, types and build passed, with existing CSS syntax and bundle-size warnings. No test suite was restored or run. Windows execution remains unverified. Manual evidence and screenshots are outside the repository in `/workspace/agent-factory-cleanup/`.

Current source count is **19,264 physical lines in 135 source files**, using the same extensions as the original count; the follow-up adds 90 net source lines. PR #177 remains Draft and unmerged.

## Minimal regression suite, explicitly requested afterwards

The user subsequently authorized minimal feature-based regression tests using Ponytail. The repository's installed Ponytail skill was read; neither the repository/environment catalogs nor the retained upstream skill package contained a separate testing skill. No unavailable plugin hooks are claimed.

Added one 264-line file with two browser journeys, without restoring the deleted suite or changing production behavior. The first uses actual login, Settings model configuration, PostgreSQL/Agno execution, personal CLI failure and recovery, SSH discovery, native file editing/download, child execution/continuation, draft preservation, refresh and mobile layout. The second confirms a live command PID before Stop and its absence afterwards. Downloads compare raw bytes, and refresh must not generate new model requests. Each run creates and drops its own random database and uses explicitly isolated temporary tool storage.

Only the model HTTP endpoint is scripted (Chat Completions SSE); browser, API, database, queue and tools are real. This establishes deterministic integration behavior, not real-model intelligence or external-provider compatibility. Remote SSH execution, MCP, Responses, Windows and long-duration runs are not covered by these two cases.

Final local run: **2 tests passed in 25.505 seconds**. Ruff, Pyright, frontend lint/types/build and lock consistency also passed, with the previously recorded Windows import and CSS/bundle warnings. Independent review findings were addressed. CI now runs the same journeys against PostgreSQL 17 and Chromium. Current source: **19,528 physical lines across 136 files**, including the new tests. PR remains Draft and unmerged.
