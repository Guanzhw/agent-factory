# PR47 installation closure handoff

This delivery publishes the previously reviewed installation helpers so another
machine can obtain them from Git. It does not introduce a new runtime diagnostic,
change the application, or claim target installation/database/training acceptance.

## Two separate checkouts

The **tool delivery commit** is the commit containing this document,
`scripts/install-handoff.sh`, `scripts/verify_closure.py`,
`scripts/copy_install_site.py`, and
`docs/evidence/pr47-source-manifest.json`. Pin that reviewed commit when obtaining
these files. It is not the runtime source to build.

The **runtime source commit** remains exactly
`6d6eb9f5fbd3ead921a82b1226edbe6f3d96c12f` from
[Draft PR47](https://github.com/Guanzhw/agent-factory/pull/47).
Create a separate detached checkout at that commit, for example from a fetched
local repository using `git worktree add --detach "$SOURCE" 6d6eb9f5fbd3ead921a82b1226edbe6f3d96c12f`.
`SOURCE` must be a new absolute directory chosen by the operator. Keep its
585 tracked files unchanged. Do not point `SOURCE` at the newer tool checkout.

The public manifest is included byte-for-byte; its SHA256 is
`2cf5e58120ec707d24cf5014cd869f370c856ee4c495b5bc4befe123cd09bb24`.
It contains only repository-relative public filenames, sizes and hashes. No
cross-machine private download path or prebuilt wheel is required: the target
builds its own wheel from the pinned runtime source.

## Inputs and execution

Read the script's review prerequisites before execution. Export these variables
in the authorized target's local shell; values and output artifacts stay private:

| Variable | Required value |
|---|---|
| `UV` | Reviewed absolute uv **0.11.7** executable |
| `CONTROL_PYTHON` | Reviewed Python for standard-library snapshot/wheel checks |
| `BASE_PYTHON` | Original approved Python **3.12.13** interpreter target |
| `OLD_PROJECT` | Original complete combined project, with pyproject and uv.lock |
| `OLD_SITE` | Original combined environment's site-packages directory |
| `OLD_CONFIG` | Original private configuration file; not a DSN/password file |
| `NEW_ROOT` | New, absent absolute task-owned installation directory; existing private parent |
| `SOURCE` | Separate exact PR47 runtime checkout described above |
| `MANIFEST` | Tool checkout's `docs/evidence/pr47-source-manifest.json` |
| `VERIFIER` | Tool checkout's `scripts/verify_closure.py` |
| `UV_CACHE_DIR` | Existing authorized dependency cache, preferably on the proven destination filesystem |

Run the shell script from the tool checkout:

```sh
bash scripts/install-handoff.sh --copy-mode full-copy
```

The known ext4 target reports `FICLONE` / `ENOTSUP` and has sufficient space
for independent copies: use **full-copy**, with no CoW probe or receipt required.
The optional `--copy-mode clone` retains the previous CoW path; omitting the flag
keeps clone for compatibility. Neither mode silently falls back or accepts
shared hardlinks. `copy_install_site.py` must remain beside `verify_closure.py`
in the same pinned tool checkout.

If the accepted original 95-package installation selected explicit groups or
extras, pass those **same** `uv sync` selection flags as arguments, for example
`bash scripts/install-handoff.sh --copy-mode full-copy --no-dev` only when
`--no-dev` was actually used.
Do not edit either checkout just to set paths or flags.

Review effective uv configuration and preserve the original approved package
indexes/source provenance. Inspect local/workspace path dependencies before
copying the two project files: relative non-Factory paths may require a reviewed
layout for the new project. Do not replace the combined lock with Factory's lock,
discard required Torch index settings, or install a bare Factory environment.
`--no-install-project` assumes the combined project itself was not an installed
distribution in the original 95-package set; if it was, review that original
installation selection before running this procedure.

The script uses normal isolated PEP517 wheel construction, verifies the public
source/manifest/wheel, captures the original 95 package names and versions,
derives a new combined lock selecting the new wheel, and installs into a fresh
venv. It uses offline cached packages; a cache miss stops the attempt. Obtain the
identified public artifact through the existing authorized package channel
before a new preserved attempt. No model or subscription call is involved.

Before build/install, full-copy requires at least **20 GiB currently free** on
the new root's filesystem: two maximum admitted 8-GiB site trees, 2 GiB build
scratch, and 2 GiB remaining headroom. The observed byte budget is written to
private evidence. Clone uses a 12-GiB conservative installation budget and still
requires a proven CoW destination; reported fallback stops the attempt. These
budgets do not waive the runtime's separate 32768-file / 65536-entry / 1-GiB-file /
8-GiB-site limits. Available disk space is measured, never inferred from an older
free-space report.

Full-copy keeps uv's initial installation in a new task-owned staging directory,
then materializes the complete site back at its original logical venv location.
It does not relocate the venv or copy an old environment. Each file uses an
exclusive same-directory temporary file, streamed SHA256/size validation, fsync,
atomic rename and readback; source identity and the complete namespace are
rechecked. Source symlinks, special files, shared hardlinks, insufficient space
and changing content fail closed. Owner execute permission is preserved on new
copies; no shared/cache/source inode is chmodded. Final files must be independent
single-link files. The helper never uses `FICLONE` or `os.link`.

On failure, cleanup removes only newly created destination entries whose inode
identities still match this copy attempt. Replaced or unknown entries are left
held; old files are never cleaned up. New source staging and failure evidence
remain private for inspection. The retained staging tree also counts toward the
budget on success. Do not delete or reuse an old attempt to make room. This is an
operator-owned private installation procedure, not isolation against concurrent
malicious writes by the same OS account; do not run competing writers.

The same package version `0.2.0` does not prove source identity.

## Acceptance and next action

The verifier checks all 135 runtime package files against the exact source and
wheel, all 95 installed distribution names/versions against the original set,
entrypoint Factory imports and symbols, installed import origins, and the shared
policy contract. It rejects editable installation and stale package payloads. The final check
still requires exact uv 0.11.7 / Python 3.12.13 and the previously reviewed
`uv0117-setuptools82-local-v1` startup profile. These known target versions, all
95 package versions, original extras/groups, root-project installation selection,
local source referents and original package indexes must remain consistent;
copy mode changes filesystem materialization only.
It then revalidates a derived configuration and builds fresh full-site inventory,
kernel and interpreter-contract evidence under `NEW_ROOT/evidence`.
`installation-identity.json` binds the derived project/lock, wheel and evidence.
These files contain private paths and must not be published.

Only `INSTALLATION_CLOSURE_PASS_NO_DATABASE_NO_EXECUTION` completes this
installation check. Any nonzero exit means stop and preserve evidence; do not
continue just because a partial derived config or inventory file exists.
The helper does not open `databaseUrlFile`, construct an application, enter
lifespan, import Torch, query a GPU, or submit work. It does not inspect any
alternative credential file. Its inventory is not runtime admission approval;
future canonical execution captures its own evidence in a fresh workspace.

After installation closure passes, run the existing PR47 read-only database
preflight with the newly installed interpreter and derived config:

```sh
"$NEW_ROOT/venv/bin/python" -B "$SOURCE/scripts/run_research_baseline.py" \
  --database-preflight --config "$NEW_ROOT/evidence/diagnostic-config.json"
```

Only that existing runner uses the original authorized configured DSN for normal
authentication. Do not substitute another password file or print/hash credentials.
Return only the runtime commit, closure PASS/BLOCKED, version/source equality
booleans, inventory/capture status, database-preflight exit code and its fixed-enum
report. Database policy compatibility, actual execution and scientific results
remain separate acceptance gates. No automatic migration or training follows.
