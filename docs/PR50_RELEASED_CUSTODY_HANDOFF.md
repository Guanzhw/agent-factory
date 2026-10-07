# Released original custody and PR50 research continuation

This handoff continues the already-authorized research task. It neither starts
personal-agent roadmap work nor changes the scientific baseline, evaluator,
dataset, training budget or retry policy. No generic new permission gate is
introduced. Cloud validation uses synthetic fixtures; actual target results
must be recorded separately.

## Original task: verify completed release, do not repeat it

The target's read-only report now contains positive original lease/provider
`RECLAIMED`, `capacityHeld: false`, provider `released: true`, `allStopped: true`
and GPU `RELEASED` with `never-dispatched` proof. Mapping, binding hash and
database identity were reported PASS. `cancelAck` / `releaseAck` remain unknown.
Once full original identity and proof validation passes, those transport ACKs
do not require replay, reset or another release. Preserve all historical states.

The original service object is unavailable. Do not call `create_app`, enter an
application lifespan, initialize schemas or reconstruct an executor simply to
read evidence. In particular, `ProcessResourceProvider.inspect()` is **not** a
read-only substitute: its implementation persists a refreshed allocation record.
The existing release mutation path is unnecessary for an already-released lease.

Read the original records using the local worker's existing authorized read-only
database connection in one consistent read-only transaction. Select exact
original IDs, never the latest task or a same-name replacement. Export only the
bounded non-credential fields required by `audit_released_research_custody.py`
to a new private evidence file. The helper does not open a DSN or authenticate to
a database. Original configured provider pins must come from the preserved
pre-attempt configuration/receipts, independently of the records being checked;
copying hashes out of the same allocation is not independent validation.

The helper reads the original SQLite custody journal with a read-only connection
and verifies the never-dispatched receipt, physical journal identities, original
configuration, plan, task/native-envelope and GPU proof chain without starting
a service. Its finite result describes consistency of the supplied original
evidence; the authorized operator remains responsible for export provenance and
freshness. Do not replace absent original inputs with freshly captured values.
An UNKNOWN result identifies an evidence gap, not an instruction to rerun work.

Keep three original local paths: `CUSTODY_EXPORT` (the new read-only DB export),
`ORIGINAL_PINS` (independently retained original non-credential configuration
represented in the helper's JSON contract), and `ORIGINAL_JOURNAL` (the original
`custody.sqlite`, not a copied replacement). The exact required export keys are
documented at the top of the delivered helper; DB JSON bodies must be decoded
objects. Preserve original task-request and lease-request IDs separately.

```sh
"$CONTROL_PYTHON" -I -B "$TOOLS/scripts/audit_released_research_custody.py" \
  "$CUSTODY_EXPORT" "$ORIGINAL_PINS" "$ORIGINAL_JOURNAL"
```

Exit zero with `RELEASED_CUSTODY_CONSISTENT` means the supplied original chain
passed consistency checks. It does not authenticate the exporter or mark the
next attempt ready; those limitations are explicit result fields. Exit two /
`UNKNOWN` means stop the dependent launch and locate missing/mismatched evidence.
The helper supports only the reported cooperative, never-dispatched,
already-released case, on the same boot, with a stable DELETE-mode journal and
no WAL/SHM/recovery sidecars. It does not rewrite storage holds or ACKs.

## Preserve the three new bytecode files as historical evidence

The reported additions are:

- `__pycache__/_virtualenv.cpython-312.pyc`
- `_distutils_hack/__pycache__/__init__.cpython-312.pyc`
- `agent_factory/__pycache__/process_enforcement.cpython-312.pyc`

They are reported regular non-symlink files absent from both original sealed
manifests, with modification times after both capture receipts. Their actual
writer remains unknown. Do not delete them, amend the old inventory, or assign
their provenance from timestamps alone. PR50's guardian `-I -B` fix removes a
concrete write path; it does not establish which process wrote these files.

## Separate source and tool delivery

The runtime source is exactly PR50 commit
`997013114a8c533c84078d174b220e541ea19f9a`. Obtain it in a separate detached
checkout. The tools and this document come from the reviewed handoff commit;
do not confuse that tool revision with the runtime source pin.

Keep historical `verify_closure.py`, `install-handoff.sh` and the PR49 one-file
repair mode unchanged. They deliberately do not admit this multi-file runtime
update. Use the separate PR50 verifier, manifest and installation script.

Set `TOOLS` to the pinned handoff checkout. Set `SOURCE` to a separate new
absolute directory and create the runtime checkout from the fetched repository:

```sh
git worktree add --detach "$SOURCE" 997013114a8c533c84078d174b220e541ea19f9a
```

Use the reviewed local values for `UV`, `CONTROL_PYTHON`, `BASE_PYTHON`,
`OLD_PROJECT`, `OLD_SITE`, `OLD_CONFIG`, `NEW_ROOT` and `UV_CACHE_DIR`, with the
same meaning and package/index review prerequisites as the
[original installation handoff](PR47_INSTALL_HANDOFF.md#inputs-and-execution).
The new source, verifier and manifest replace their old counterparts explicitly:

```sh
export SOURCE
export MANIFEST="$TOOLS/docs/evidence/pr50-source-manifest.json"
export VERIFIER="$TOOLS/scripts/verify_pr50_closure.py"
bash "$TOOLS/scripts/install-pr50-handoff.sh" --copy-mode full-copy
```

If original installation used explicit extras/groups, append exactly those
selection flags. The new helper admits full-copy only, needs 20 GiB free on the
new-root filesystem and stops on any failure. Only
`INSTALLATION_CLOSURE_PASS_NO_DATABASE_NO_EXECUTION` is closure PASS. The
installation procedure does not read database credentials, query a GPU or start
an application. Keep all installation logs and evidence private.

Use a fresh absent installation root, the original approved combined project
and exact dependency versions/index provenance, reviewed uv 0.11.7 and Python
3.12.13, and independent full copies on the known non-CoW filesystem. Do not
copy the old site tree or install over it. Keep every old workspace, claim,
config, inventory, journal and failure artifact. Offline package-cache misses
are concrete artifact blockers, not a reason to alter dependency versions.

All inspection Python processes use explicit `-I -B` where supported; `-I`
ignores `PYTHONDONTWRITEBYTECODE`, so that environment variable alone is not a
sufficient guarantee. The canonical script requires its sibling script imports
and uses explicit `-B`; do not add `-I` to it without changing that import contract.
Set `PYTHONDONTWRITEBYTECODE=1` as defense in depth and leave bytecode compilation
disabled. Fresh full inventory must include every installed namespace entry;
there is no pyc-ignore rule or post-capture cleanup exemption.

## New attempt after validated release and installation closure

After audit and installation closure PASS, use the new interpreter and exact
PR50 runner for its existing `--preflight` and `--database-preflight` modes.
Database preflight uses the existing authorized credential configuration only;
do not print or export it, provision a new database, reset schemas or change
identity/policy merely because the old database is no longer empty.

```sh
export PYTHONDONTWRITEBYTECODE=1 SETUPTOOLS_USE_DISTUTILS=local AGNO_TELEMETRY=false
"$NEW_ROOT/venv/bin/python" -B "$SOURCE/scripts/run_research_baseline.py" \
  --preflight --config "$NEW_ROOT/evidence/diagnostic-config.json"
"$NEW_ROOT/venv/bin/python" -B "$SOURCE/scripts/run_research_baseline.py" \
  --database-preflight --config "$NEW_ROOT/evidence/diagnostic-config.json"
```

Check each exit code and fixed-enum result before continuing; do not run the next
command after a failed preflight. The old `31 tables empty` observation applied
only before the old attempt and is not a requirement to erase its records now.

Prepare a separate private canonical configuration from the verified derived
installation configuration: replace only the workspace with a fresh absent
task-owned path and request ID with a new recovery-attempt identity. Retain the
approved input/data/evaluator/model/limits and existing database configuration.
This new attempt follows a validated released old attempt; it is not an ACK
replay or substitution for the old task. Do not use the diagnostic workspace
for canonical execution, and do not run `--assembly-only` against the intended
canonical workspace because that mode creates its own retained workspace.

Set `RECOVERY_CONFIG` to a new private file, `RECOVERY_WORKSPACE` to an absent
absolute task-owned directory and `RECOVERY_REQUEST_ID` to a new identifier of
8–40 allowed letters, digits or `_.:-`. Use this local-only derivation; it never
opens `databaseUrlFile`:

```sh
"$CONTROL_PYTHON" -I -B - "$NEW_ROOT/evidence/diagnostic-config.json" \
  "$RECOVERY_CONFIG" "$RECOVERY_WORKSPACE" "$RECOVERY_REQUEST_ID" <<'PY'
import json, os, re, sys
from pathlib import Path
source, output, workspace = map(Path, sys.argv[1:4])
request = sys.argv[4]
assert workspace.is_absolute() and '..' not in workspace.parts
assert not workspace.exists() and not workspace.is_symlink()
assert re.fullmatch(r'[A-Za-z0-9_.:-]{8,40}', request)
value = json.loads(source.read_bytes())
assert value['workspace'] != str(workspace) and value['requestId'] != request
value.update(workspace=str(workspace), requestId=request)
os.umask(0o077)
with output.open('x') as stream:
    json.dump(value, stream, sort_keys=True)
PY
"$NEW_ROOT/venv/bin/python" -B "$SOURCE/scripts/run_research_baseline.py" \
  --preflight --config "$RECOVERY_CONFIG"
"$NEW_ROOT/venv/bin/python" -B "$SOURCE/scripts/run_research_baseline.py" \
  --config "$RECOVERY_CONFIG"
```

Run the final command only after the preceding checks passed; no loop or automatic
retry wraps it. Paths, identifiers and config contents remain private. Existing
input acknowledgements are preserved; the user has already authorized recovery.

Run the canonical command once, retry zero. Its normal preparation and runtime
capture produce new inventory/contracts under the new attempt; installation
closure evidence is not reused as runtime admission. `PROCESS_SUBMITTED` remains
an allocation acknowledgement, not spawn proof. Record actual guardian/child and
training configuration evidence, training completion/checkpoint and independent
evaluation, then positive final compute/GPU release. The previous attempt did
not reach Torch, 300-second training or evaluation; this continuation must prove
those stages independently. Scientific quality is separate from process success.

On any new failure, retain the new attempt and use its original identity and
normal bounded cleanup. Do not automatically launch a second attempt or loosen
namespace, source, budget, authorization or release checks.
