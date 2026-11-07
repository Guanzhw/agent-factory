# Research tool simplification — 2026-11-07

This review covers `applications/research/session_tools.py` , `session_commands.py` and their focused tests. It is one part of the interaction/runtime change, not evidence that the whole product has passed acceptance.

## Native capabilities and reference

The installed dependency is Agno 3.1.0. Its `agno/tools/workspace.py` provides `Workspace.edit_file` and `Workspace.write_file`. Research now calls these methods for exact edits and file creation. It does not maintain a second text replacement algorithm. The wrapper supplies the session directory, returns actual before/after hashes, and retains the original operation receipt. `allowed=['write', 'edit']`, `confirm=[]`, `exclude_patterns=[]` and `require_read_before_write=False` avoid introducing native confirmation or hidden-file exclusions.

Agno's text editor normalizes line endings through Python text IO. A CRLF file edited on POSIX becomes LF; hashes describe the actual resulting file. The native method has no newline-preservation option. No global monkeypatch or alternate editing engine was added.

Agno's `ShellTools.run_shell_command` uses blocking `subprocess.run`, returns the last 100 lines, and does not expose a process handle or preserve the structured exit status. `CodingTools.run_shell` adds a default 120-second timeout. Neither provides the existing owned-process-tree stop evidence. Research retains the existing command process adapter for that concrete gap. Native `Workspace.search_content` restricts extensions, file size and match count without continuation; it does not replace the complete literal search.

Codex comparisons are pinned to [`0ed34eb9ceddc759e283f0d657be9339afc6b25a`](https://github.com/openai/codex/tree/0ed34eb9ceddc759e283f0d657be9339afc6b25a):

- [`unified_exec/mod.rs`](https://github.com/openai/codex/blob/0ed34eb9ceddc759e283f0d657be9339afc6b25a/codex-rs/core/src/unified_exec/mod.rs) defaults returned output to 10,000 tokens. Its 1 MiB buffered-output bound is not an operation-failure condition.
- [`utils/string/src/truncate.rs`](https://github.com/openai/codex/blob/0ed34eb9ceddc759e283f0d657be9339afc6b25a/codex-rs/utils/string/src/truncate.rs) approximates four UTF-8 bytes per token and preserves a prefix/suffix at UTF-8 boundaries. The truncation marker is outside the retained-text budget.
- [`tools/handlers/unified_exec.rs`](https://github.com/openai/codex/blob/0ed34eb9ceddc759e283f0d657be9339afc6b25a/codex-rs/core/src/tools/handlers/unified_exec.rs) defaults yield to 10 seconds and has an optional timeout. Yield is not a command deadline.

## Changes and effects

| Previous project restriction | Current behavior |
| --- | --- |
| Edit replacement limited to 12,000 characters and 12,000 UTF-8 bytes | No project edit-size ceiling; Agno performs the edit. |
| Search stopped at 30 matches, 200 entries or depth 8; each line shortened to 200 characters | Traverses the selected directory and returns all matching lines with full text. Binary files are skipped. |
| Path/query/message schema lengths; command limited to 32 arguments of 2,000 characters each | Removed arbitrary schema maxima. Types and required values still describe valid calls. |
| Relative-only paths and lexical rejection of `..`/links | Absolute paths, resolved `..`, and internal symlinks work when the resolved target belongs to the session directory. Other session directories remain distinct. |
| New file required a separate parent-directory command | Native write creates missing parent directories. |
| Host command tool disabled by default | Enabled by default when a workspace is configured; an explicit deployment disable remains respected. |
| Executable had to be a basename on absolute-only configured PATH | Defaults inherit the actual service PATH (empty falls back to OS defaults). Relative PATH entries resolve from the command working directory; absolute and working-directory-relative executable paths also work. Windows default PATH syntax no longer prevents startup. |
| All calls within one run serialized | Only duplicate calls with the same original call ID wait for each other. Independent commands can overlap. |
| Large command output killed/rejected work or left an unknown outcome | Command completes; default 10,000-token preview and full stdout/stderr files are returned. `max_output_tokens` selects the preview size. |
| Implicit command deadline/output defaults | Absent values remain absent; cancellation still targets the owned process tree. |

The shared core argument validator also had a 65,536-byte JSON ceiling, which blocked long Unicode edits after local schema limits were removed. The core change removes that ceiling; the regression exercises the complete Agno Function path rather than calling the editor directly.

Session-directory selection, original-call deduplication, ambiguous-effect recovery and stop evidence remain functional correctness requirements. An acknowledged failed edit does not pretend success; an edit that changed the file but lost its acknowledgement remains unknown and is not replayed. This is not a new approval flow.

## Evidence and remaining differences

Executed on Linux with actual temporary files/processes and synthetic authorization/provider fixtures:

```sh
PYTHONPATH=platform:deployment:platform/tests:applications:applications/tests \
  .venv/bin/python -m unittest test_research_session_tools -q
.venv/bin/ruff check applications/research/session_tools.py applications/tests/test_research_session_tools.py
.venv/bin/pyright applications/research/session_tools.py
```

The focused suite ran 46 tests successfully, with six native Windows cases skipped. Static checks passed. Coverage includes deep/late search matches, long Unicode edits and arguments, native Workspace writes, large-output retrieval, concurrent commands in one run, duplicate-call execution exactly once, command failure/correction, unknown effects, and real POSIX parent/child cancellation. This does not establish native Windows execution or a live-model acceptance.

Commands now use an Agno native child Workflow (`research-command`) with the existing durable queue, delegation record, original effect receipt and process adapter. `research_run` defaults to a 10-second yield and returns `processId` / `childTaskId` when still queued or running. `research_read_process` reads that original child and its actual output files; `research_wait_child` releases the parent's execution worker. Short commands still return their final result directly. Explicit yield values clamp to 250–30,000 ms; Windows initial execution uses the 10-second floor in the pinned Codex `unified_exec/mod.rs`. A nonzero exit is reported as failed, and cancellation requires stop evidence.

The focused command recovery suite passes nine tests: receipt replay without re-execution, unknown original preservation, expanded output retrieval, session identity, nonzero exit, cancellation evidence, and admission/completion snapshots changing during a process read. The reader refreshes the child binding after observation, then reads its current ticket and final receipt; it does not turn a stale in-flight receipt into a false unknown outcome. Real PostgreSQL/Agno tests with a scripted provider passed completion and actual process stop (two tests, 56.021 seconds), and two root tasks occupying both workers completed through native child waits (one test, 26.932 seconds). A fourth real queue scenario verified that a parent which completes before its command does not silently kill the child or expose an idle session; the original command completes afterward (29.198 seconds). These tests use real subprocesses and the actual queue; the model responses are synthetic. Logs: `/tmp/research-command-native5.log`, `/tmp/research-command-two-roots.log`, `/tmp/research-command-early-parent2.log`. The process suite passed 31 tests with six native Windows skips, including a 2 MB output whose complete sink is preserved while aggregate captured stdout/stderr remains at most 1 MiB (`/tmp/research-process-buffer.log`). A subsequent 601-second probe exposed an existing lifecycle group-status error before command completion; the core observer correction and final long-duration rerun are tracked in the main acceptance report. Do not treat the earlier short tests as long-duration acceptance.

A real mobile stop exercise exposed a separate first-yield race: the child process had a confirmed cancellation receipt, but the parent's dispatch effect was still unacknowledged. The dispatcher now persists the original child handle as soon as durable creation returns, before waiting for output. This receipt explicitly says `stopped: false`; only the existing child-process evidence can establish stop. A PostgreSQL test requests stop after actual process output during a 30-second initial yield and reaches a stopped session with the child cancellation receipt (29.558 seconds, `/tmp/research-command-initial-stop.log`). A duplicate original `research_run` call also returned the same handle and kept one child/process receipt (34.559 seconds, `/tmp/research-command-native-duplicate.log`). Mobile visual revalidation is tracked separately.

This provides yielding and continuation within the current turn. It is not an interactive PTY or `write_stdin`, nor a cross-turn process handoff. The native parent remains waiting until its children finish. A restarted reader uses original durable facts and never launches a replacement for unknown execution. Full output is saved through a streaming disk sink. Research commands retain at most 1 MiB across stdout/stderr in process memory; reaching that retention size does not fail or kill the command. Subsequent reads seek to a bounded head/tail preview in the full files rather than loading the whole output. This is separate from the 10,000-token default returned preview. Native Windows process behavior and live-model acceptance remain separate validation requirements.
