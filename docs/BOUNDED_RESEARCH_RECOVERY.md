# Bounded original-model research recovery

> **Historical — application not installed.** This document records the retired Research/ORX application and earlier acceptance. Its routes, source paths, configuration and commands are not current core-only setup instructions. Original evidence, failures and UNKNOWN outcomes below are preserved; they do not certify the current revision. Source retirement does not authorize deleting old data, credentials, vault keys, artifacts or backups.

The real acceptance at `6752f1a` configured the existing owner credential through
the encrypted vault, then submitted one normal browser research turn. Five
provider responses were confirmed. The final native step ended with `length`,
4095 reasoning tokens and one output token; no readable final text or requested
statistics files were produced. The original native chat was idle, unqueued and
completed, while Factory retained its active-request guard because earlier
`glob` errors made the projected result unsuccessful.

## Known-ended turns remain distinct from successful research

The existing acknowledged-turn matcher keeps its idle/queue, original history,
prompt hash, user-parent and sole active assistant-leaf checks. A completed
assistant with only terminal tool states (`completed` or `error`) can now release
the original turn guard. The unsuccessful result remains unsuccessful. Running
tools, unresolved native prompts, unknown acknowledgements, concurrent answers
and rewritten/truncated history remain blocked. Refresh observes the original
request; it never dispatches it again. A subsequent user action creates a new
message in the existing session.

## Explicit bounded thinking option

`thinkingMode: "disabled"` is an optional owner-model configuration value only for
`longcat-2.5-preview-free` at `https://opencode.ai/zen/go/v1`. The existing model
configuration API/service authenticates the caller and checks credential scope.
It persists the option in the immutable model revision. Both registered Agno
and native broker requests then send `thinking: {"type":"disabled"}`. The native
request body cannot override it. Other models reject this explicit mode.

Absent, null or `"default"` leaves the previous wire unchanged; default values
are omitted from stored metadata to preserve legacy request fingerprints.
Output remains 4096, the broker remains 64 calls, and no endpoint, credential,
permissions, retry or UNKNOWN-accounting change is introduced. This field is
available through the existing configuration API/Python service; no new UI
control or credential import endpoint is introduced here. Clear an old scoped
proxy grant before reconfiguring, then install a reviewed grant for the new
model revision, as required by the existing deployment rules.

The [official LongCat OpenCode guide](https://longcat.chat/platform/docs/open-code)
documents the thinking switch. The pinned OpenCode Go
[request-body preparation](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/console/app/src/routes/zen/util/requestBody.ts)
preserves the same-format body while replacing the provider model. This supports
the proposed wire shape; live gateway acceptance of the explicit option is
still to be verified in a new authorized turn, without trying guessed options.

## Exact native ripgrep dependency

OpenCode 1.18.35's
[binary loader](https://github.com/anomalyco/opencode/blob/v1.18.35/packages/core/src/ripgrep/binary.ts)
uses system `rg`, then its existing cache, then downloads ripgrep **15.1.0**.
The isolated runtime had no system/cache executable and logged an attempted
download while deliberately running with `NetworkMode=none`. The tool exposed
`ripgrep execution failed`; it retained no child exit code or detailed cause.
There was no `rg` executable process to inspect. The protected wrapper also
rejects the diagnostic CLI; do not invoke its underlying binary to bypass it.

Prewarm the existing owner cache with the exact official Linux-musl release,
verified against its published checksum, while keeping runtime networking off.
Acceptance downloaded the
[official asset](https://github.com/BurntSushi/ripgrep/releases/download/15.1.0/ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz)
and its checksum: archive SHA256
`1c9297be4a084eea7ecaedf93eb03d058d6faae29bbc57ecdaf5063921491599`.
The unpacked binary hash is
`ebeaf56f8a25e102e9419933423738b3a2a613a444fd749d695e15eba53f71f2`.
Its offline CSV glob exited zero with empty stderr. This repairs the existing
dependency rather than substituting another tool. Native glob still requires
verification after supported restoration of the original environment.

All original session data, actual response receipts and the encrypted database
remain retained. New source needs exact-head review/checks before live use;
the green `6752f1a` CI does not validate this change. PR80/82 remain unmerged.
