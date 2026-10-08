# Released original custody and PR50 research continuation

This handoff continues the already-authorized research task. It neither starts
personal-agent roadmap work nor changes the scientific baseline, evaluator,
dataset, training budget or retry policy. No generic new permission gate is
introduced. Cloud validation uses synthetic fixtures; actual target results
must be recorded separately.

Execute the snippets in one reviewed Bash session with `set -euo pipefail` so
failed audits, derivation or preflight commands stop before subsequent actions:

```sh
set -euo pipefail
```

## Original task: verify completed release, do not repeat it

The target's read-only report now contains positive original lease/provider
`RECLAIMED`, `capacityHeld: false`, provider `released: true`, `allStopped: true`
and GPU `RELEASED` with `never-dispatched` proof. Mapping, binding hash and
database identity were reported PASS. `cancelAck` / `releaseAck` remain unknown.
Once the original release identity and proof validation passes, those transport ACKs
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
a database. For this reported **never-dispatched, already-released** case, use
the explicit minimal release mode below. PR52's default full historical-config
mode was too strong as a prerequisite to this narrower release question; it
remains available as optional forensic verification.

Keep three paths: `CUSTODY_EXPORT` (the original read-only DB export),
`ORIGINAL_SELECTION` (a new private JSON selection of original IDs), and
`ORIGINAL_JOURNAL` (the original `custody.sqlite`, not a copied replacement).
The selection contains only `schema: 1`, `taskId`, `ownerId`, `requestId`,
`leaseId`, and optionally `nativeRunId`. Obtain these from preserved bootstrap
progress and the exact original persisted mapping. The task request ID is not
the lease/controller request ID; preserve their distinction. Do not select a
latest task or invent configuration fields. The helper's module docstring lists
the DB export fields and normalized session contract; JSON bodies must be decoded.

```sh
"$CONTROL_PYTHON" -I -B "$TOOLS/scripts/audit_released_research_custody.py" \
  --released-never-dispatched "$CUSTODY_EXPORT" "$ORIGINAL_SELECTION" "$ORIGINAL_JOURNAL"
```

The original `af_tasks.plan_id` selects `af_plans.body/hash`. The helper recomputes
the canonical plan digest and checks it against the stored hash, task fingerprint
and original lease binding. That persisted original plan is the legitimate source;
a separately saved plan-hash file is not required. Original journal spec/identity
digests must match the persisted allocation's process pin. The actual original
journal/root physical identity must match the namespace committed in the original
binding. These are consistency checks across original persisted records, not a
claim that current metadata is independently retained history.

Run-config, driver seal, training and evaluation receipts are **not applicable**
when dispatch never occurred. Do not create placeholders. Historical driver,
source and observer configuration reconstruction is not required for this release
scope, and the result explicitly does not claim it was validated. The strict
three-positional-argument mode still requires independently preserved full pins
if that separate forensic question is pursued.

Exit zero / `RELEASED_CUSTODY_CONSISTENT`, with
`releaseIdentityConsistent: true` and scope `NEVER_DISPATCHED_RELEASE`, means the
original plan/native/mapping/journal/stop/compute/GPU chain passed. The result
keeps `identityConsistent: false`, `historicalConfigValidated: false`,
`descendantsChecked: false` and `newAttemptReady: false`: it authenticates neither
the exporter nor full historical configuration and does not prove queue closure.
Trusted original export provenance and freshness remain operator responsibilities.
Exit two / `UNKNOWN` identifies a finite failed `phase`; stop dependent launch,
retain the evidence and investigate that specific mismatch, without ACK replay.

This mode supports cooperative never-dispatched custody on the same boot with a
stable DELETE-mode journal and no WAL/SHM/recovery sidecars. A later reboot or
root move makes this profile inapplicable; it does not imply released capacity
became active. Missing actual stop/release/GPU evidence remains a blocker. A
changed host requires a separately reviewed proof from preserved original receipts
and current resource ownership, not fabricated history or weaker release checks.

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

Before any new application lifespan, complete the executable
[original queue/descendant read-only gate](RESEARCH_ORIGINAL_QUEUE_READ.md).
Use `scripts/research_original_queue_audit.sql` with exact original IDs and the
existing authorized read-only connection while old writers remain stopped.
Require JSON `PASS` / `NO_DESCENDANTS_OF_ORIGINAL_ROOT`, not merely exit zero or
related-pending count zero. This checks the fixed root-only profile and absence
of every first Factory/native descendant edge, including unresolved intents and
queued child payloads. Only then is deeper traversal legitimately not applicable.
Any edge or unsupported schema is UNKNOWN and requires a bounded graph-specific
read; do not restart the old service to perform it.

Release audit PASS plus queue PASS closes the old attempt's custody and runnable
work questions. Neither changes its failed outcome, resets unknown ACKs, or alone
certifies a new installation. Continue under the existing recovery authorization.

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
