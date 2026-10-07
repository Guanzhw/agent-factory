# PR47 package-data path repair

The target has completed the online install, full-copy and dependency check.
All95 versions and all135 original PR47 Factory files match. Inventory then
rejected valid setuptools data names: `script (dev).tmpl`,
`command/launcher manifest.xml`, and `_vendor/jaraco/text/Lorem ipsum.txt`.
This is a code defect, not evidence that the dependency installation is damaged.

The shared observer `_relative` now accepts printable literal POSIX names,
including spaces and parentheses. It still rejects empty/dot/parent components,
absolute paths, backslashes, colons, controls and surrogates. Names are never
trimmed, decoded or normalized. Descriptor nofollow, regular-file/single-link,
namespace, bounds and hash checks remain intact. Inventory, observer schema3
site files, package trees and interpreter coverage all reuse this policy.
Interpreter absolute paths already support these names. Manifest logical IDs,
Python module basenames and reviewed startup allowlists remain unchanged.

## Identity and scope

- Base runtime/source manifest remains PR47
  `6d6eb9f5fbd3ead921a82b1226edbe6f3d96c12f`.
- Exactly one of135 Factory payload files changes:
  `agent_factory/research_environment_observer.py`.
- Original file SHA256:
  `1ab79c9ea87decd576c27d3ab8ea67121bc61e4d55943f6d5af597d80e7d8a66`.
- Repaired file SHA256:
  `ee479cf871534572d62b292bdd616e7e657ddc2a93e1d2713e26af78c91bc587`.
- Repaired wheel built and checked offline in cloud:
  `70b31c682b7163f879393515c24b7aaeee60a931b4086fe31dc74df4ed13503c`.
- Repaired135-file payload-map SHA256:
  `ce13fca5eb0d14c634270058d424ca4f22b5ed7ddf22f2e478cc637018c41a58`.

The verifier requires explicit `--package-path-fix --base-wheel ORIGINAL_WHEEL`.
It verifies the original source manifest and original wheel, then accepts only
the pinned one-file replacement in the new wheel and installed payload. An
arbitrary replacement, missing original wheel or stale original installation
does not qualify. New evidence records both wheel hashes, base source head,
patch hashes and derived payload identity. The published delivery commit also
pins the repair tools. The unmodified combined lock describes base dependency
provenance; the explicit repair receipt describes the Factory-only overlay.
Do not claim that an unchanged base lock alone describes the repaired payload.

Only the original target worker performs this procedure, on the new task-owned
venv from the successful full-copy attempt, before any running consumer or
sealed contract uses it. Preserve the original sealed environment and every
prior attempt/evidence directory. Do not rerun sync, full-copy or resolve the
dependency set. Do not edit or remove the valid setuptools files.

Use the new `repair_factory_wheel.py` prepare/check helper around an explicit
offline, no-dependencies Factory-wheel reinstall. Prepare preserves the old
Factory tree and its dist-info, and records the complete non-Factory file map.
Check verifies the repaired Factory payload and unchanged non-Factory bytes.
Failure preserves evidence and stops; it does not authorize blind retries or
automatic rollback. Build only the small Factory wheel in a new output folder
from the reviewed delivery checkout; this does not rebuild the environment.

After repair check, run the updated verifier in a fresh evidence directory.
Never reuse the failed verifier's partially written diagnostic-config or
inventory paths. Only after installation closure PASS should the original
runner continue its already-authorized database preflight. No model call, GPU
execution or scientific acceptance is implied by this repair.

## Target continuation commands

Use the original approved absolute paths, without reading credentials. `SOURCE`
is the unchanged PR47 checkout, `TOOLS` the exact new delivery checkout,
`BASE_WHEEL` the retained original successful wheel, `NEW_VENV` the successful
task-owned full-copy venv, and `PROJECT` its combined project. `OLD_SITE` and
`OLD_CONFIG` still identify the original accepted95 snapshot/config.
`REPAIR_ROOT` must be a fresh private sibling of prior attempts; never place it
inside the venv/site. Preserve original reviewed uv configuration and use the
already-populated build cache. `UV` must be the already-approved resolved
regular executable path (no symlink components); system ownership is allowed.
No new package download is needed.

```bash
set -euo pipefail
umask 077
test ! -e "$REPAIR_ROOT"
mkdir -m 700 "$REPAIR_ROOT"
mkdir -m 700 "$REPAIR_ROOT/evidence" "$REPAIR_ROOT/wheels"
EVIDENCE="$REPAIR_ROOT/evidence"
VERIFIER="$TOOLS/scripts/verify_closure.py"
REPAIR="$TOOLS/scripts/repair_factory_wheel.py"
export PYTHONDONTWRITEBYTECODE=1 SETUPTOOLS_USE_DISTUTILS=local AGNO_TELEMETRY=false
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV OPENCODE_GO FACTORY_TEST_DATABASE_URL UV_COMPILE_BYTECODE

timeout --signal=TERM --kill-after=5s 5m \
  "$UV" --cache-dir "$ORIGINAL_UV_CACHE" build --offline --wheel \
  --python "$BASE_PYTHON" --no-python-downloads \
  --out-dir "$REPAIR_ROOT/wheels" "$TOOLS" > "$EVIDENCE/build.log" 2>&1
WHEEL="$REPAIR_ROOT/wheels/department_agent_factory-0.2.0-py3-none-any.whl"

"$CONTROL_PYTHON" -I -B "$VERIFIER" snapshot \
  --old-site "$OLD_SITE" --evidence "$EVIDENCE"
"$CONTROL_PYTHON" -I -B "$VERIFIER" wheel --package-path-fix \
  --source "$SOURCE" --manifest "$MANIFEST" --base-wheel "$BASE_WHEEL" \
  --wheel "$WHEEL" --evidence "$EVIDENCE"
"$CONTROL_PYTHON" -I -B "$REPAIR" prepare \
  --venv "$NEW_VENV" --wheel "$WHEEL" --base-wheel "$BASE_WHEEL" \
  --source "$SOURCE" --manifest "$MANIFEST" --evidence "$EVIDENCE" --uv "$UV"

timeout --signal=TERM --kill-after=5s 5m \
  "$UV" --cache-dir "$ORIGINAL_UV_CACHE" pip install --offline --no-deps \
  --reinstall-package department-agent-factory --link-mode copy \
  --python "$NEW_VENV/bin/python" "$WHEEL" > "$EVIDENCE/factory-install.log" 2>&1

"$CONTROL_PYTHON" -I -B "$REPAIR" check \
  --venv "$NEW_VENV" --wheel "$WHEEL" --base-wheel "$BASE_WHEEL" \
  --source "$SOURCE" --manifest "$MANIFEST" --evidence "$EVIDENCE" --uv "$UV"
"$UV" pip check --python "$NEW_VENV/bin/python" > "$EVIDENCE/dependency-check.log" 2>&1
"$NEW_VENV/bin/python" -I -B "$VERIFIER" final --package-path-fix \
  --source "$SOURCE" --manifest "$MANIFEST" --base-wheel "$BASE_WHEEL" \
  --wheel "$WHEEL" --evidence "$EVIDENCE" --project "$PROJECT" \
  --venv "$NEW_VENV" --config "$OLD_CONFIG"
```

Only after `INSTALLATION_CLOSURE_PASS_NO_DATABASE_NO_EXECUTION`:

```bash
"$NEW_VENV/bin/python" -B "$SOURCE/scripts/run_research_baseline.py" \
  --database-preflight --config "$EVIDENCE/diagnostic-config.json"
```

Do not run `uv run`, `uv sync` or the whole installation script against the
repaired overlay: they can restore the old locked Factory wheel. Future normal
deployment should regenerate the combined lock for the accepted new Factory
artifact; this one-file repair is explicit diagnostic installation provenance.
