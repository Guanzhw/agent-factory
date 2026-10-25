# Native research text artifacts

> **Historical — application not installed.** This document records the retired Research/ORX application and earlier acceptance. Its routes, source paths, configuration and commands are not current core-only setup instructions. Original evidence, failures and UNKNOWN outcomes below are preserved; they do not certify the current revision. Source retirement does not authorize deleting old data, credentials, vault keys, artifacts or backups.

The selected platform OpenResearch session writes into its own chat worktree,
not the project's hub checkout. Previously Factory displayed the native reply
and tool output while its artifact list stayed empty, even when files existed.

After an acknowledged prompt is observed ended, open its task and select
**收集平台研究文本产物**. Factory uses the original ORX session worktree change
inventory and project file API; names in chat are never a file manifest. The
request pins the original command and current connection fingerprint. It must
be this owner's latest terminal prompt with no pending turn or unknown interrupt.
Old tasks cannot collect a later session's files, and collection sends no goal,
creates no research task and invokes no model.

The installed local platform reader selects only its own environment, project
and session. It opens every directory and file with `O_NOFOLLOW`, rejects
hardlinks and special files, bounds reads, and compares the same file identity
before/after reading. The bytes must match the complete, non-binary native file
response and its SHA-256; clone fallback, truncation and missing files are not
accepted. Hidden paths and native runtime configuration are excluded.

Captured bytes use existing `Store.artifact_write` and the owner-scoped
`/jobs/{task}/artifacts/{artifact}` download. The browser verifies the recorded
byte count and SHA-256 before offering a download. Concurrent repeated collection
reuses the same stored file version under the existing owner command lock;
changed content creates another immutable version within the existing task's
total output-byte budget. At most 16 artifacts can be collected for this task.
Default output budget remains 65536 bytes. Unsupported/incomplete or over-budget
files are reported separately, not represented by placeholder artifacts.

Provenance records the exact native project/session, Factory command, connection
pin, source path and content hash. This is a captured session worktree snapshot,
not exclusive attribution of each file to that prompt, an atomic multi-file
checkpoint, or verified scientific success. No native messages or reasoning
parts are copied into artifact files.

This first integration supports complete UTF-8 text files in the selected Linux
platform adapter. Binary files and remote/SSH adapters need their own reviewed
byte reader. An installed remote provider cannot become a local filesystem
reader by supplying paths or filenames. Existing captured artifacts remain
readable under their original task authorization after a connection is revoked.

Tests cover native path/query scope, complete content/hash, clone fallback,
credential echo, owner/revision checks, links/special files, bounded reads and
revocation. Required native PostgreSQL acceptance exercises actual Agno task
admission, general local fixture files, concurrent idempotent registration,
unknown custody rejection and protected byte/hash downloads. Keyless visual
checks are distinct from the separately authorized real-model regression.
