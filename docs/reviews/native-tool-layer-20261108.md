# Remaining native tool layers

This review starts from `4c083feb57f6532fe51f4c7f2d7a08325f3d48f0` and the installed Agno 3.1.0. Defaults alone do not justify retaining a Factory implementation. The comparisons below include configurable alternatives and actual temporary-file/process probes.

| Operation | Native option checked | Decision |
| --- | --- | --- |
| Read | `Workspace.read_file(start_line=1)` bypasses its full-file size/line checks. `CodingTools(max_lines=None, max_bytes=None)` fails during comparisons rather than disabling truncation. | Keep the small UTF-8 byte reader and opened-file handling. Native reads add line formatting and normalize newlines; the existing reader returns the actual text, including CRLF, from the selected file handle. A default size cap is not the reason for retaining it. |
| Edit | `Workspace.edit_file` already provides unique-match replacement; confirmation and prior-read requirements can be disabled. | Retain the native algorithm. Run it on a private temporary copy, then commit through the selected directory handle. Its fixed `.tmp` sibling must not touch unrelated user files. |
| Write | `Workspace.write_file(overwrite=False)` supplies the existing creation behavior. | Retain native content creation and commit without overwriting a concurrently created target. The private copy and same-filesystem atomic commit are needed for actual file integrity, not an additional user approval. |
| Exec | `Workspace.run_command/arun_command(timeout=None)` and `CodingTools(shell_timeout=None)` can disable the deadline at runtime, despite integer annotations. | Keep the existing async process helper. Actual native async cancellation leaves a child alive, and a nonzero Workspace command discards stdout. Factory retains both outputs and stops its owned process tree. No replacement deadline is introduced. |
| Search | Workspace's result count can be increased, but `search_content` still skips files over 500 KiB and extensions outside its implementation's text set. CodingTools grep has an internal 30-second timeout and output truncation. | Keep the existing literal search with complete matching lines and per-path errors. Those implementation differences cannot all be removed through the examined configuration. |

The pinned SDK implementation is in `agno/tools/workspace.py` (`read_file`, `write_file`, `edit_file`, `search_content`, `run_command`, `arun_command`) and `agno/tools/coding.py` (`__init__`, `_truncate_output`, `read_file`, `run_shell`, `grep`). Factory's corresponding entrypoints are `ResearchSessionTools._files`, `_edit`, `_run`, `_read_opened`, and `run_cli_process`. These are source/API observations for 3.1.0, not claims about future Agno releases.

## Removed duplication and corrected file behavior

`session_personal_tools.personal_tool_materials` had no caller, import, dynamic module reference or entrypoint. The active `runtime.selected_tools` path uses `personal.functions`. The dead material/requirement/connection assembler was deleted; its old same-name filtering was not a regression in the active MCP path.

The second Workspace path normalization was also deleted. It changed a real Linux file named `Ａ.txt` into `A.txt`, returning another file's content. The existing absolute/relative resolution, workspace association and opened-directory handling remain; ordinary names are not rewritten through Unicode compatibility normalization.

The native Workspace edit/write implementation uses a fixed sibling temporary name. Actual probes showed that an existing `note.txt.tmp` was overwritten, and a `.tmp` symlink changed an external temporary file before Factory reported an unknown result. Native editing now operates only on a private temporary copy. Its successful bytes are written to an exclusively created same-filesystem file through the held parent, then atomically committed. New-file creation does not overwrite a concurrent creator. Native rejection leaves the original untouched.

Independent review reproduced a race in the first fix: staging under a path derived from the original parent could follow a replacement directory. Moving to `/proc/self/fd` alone would not solve it because Workspace resolves its root back to a path. The final approach keeps native staging private and commits through the existing directory identity, without a Linux-specific `/proc` dependency.

## Verification scope

The focused regressions exercise original filename identity, CRLF input, unrelated `.tmp` files, external temporary-file links, concurrent creation, a parent renamed and replaced after native staging, existing command paths, search partial results and unknown outcomes. Baseline failures and final results are recorded in the PR. No Windows runtime was available for this review; its existing directory-handle branch was reviewed, not claimed as an actual Windows acceptance.

Live-provider results and final checks are recorded in the PR. Disposable fixtures use synthetic task content and the existing authorized OpenCode subscription. Credentials are not included in this report or repository. Controlled delivery/queue faults remain distinguished from naturally occurring provider outages.
