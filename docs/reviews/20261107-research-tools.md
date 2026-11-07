# Research tool simplification — 2026-11-07

This review covers `applications/research/session_tools.py` and its focused tests. It is one part of the interaction/runtime change, not evidence that the whole product has passed acceptance.

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

Research commands run as ordinary async Agno tools and await the original subprocess result. The additional `research-command` Workflow, process-handle API, yield parameter and dedicated tests have been removed. They were newly introduced to mirror Codex features the project did not previously need. There is no replacement scheduler or detached task. `research_run` has no default total deadline and retains actual process-tree cancellation and complete output files.

After this deletion, the research tool, deployment composition and collaboration suites passed 68 tests (seven platform/database skips), recorded in `/tmp/research-no-command-layer.log`. Earlier background-command tests and screenshots describe the removed implementation and are not current acceptance evidence. Final real-browser and long-command checks must use the ordinary tool path.
