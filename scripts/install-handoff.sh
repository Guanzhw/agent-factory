#!/usr/bin/env bash
# REVIEWED PROCEDURE, NOT AN AUTO-DISCOVERY SCRIPT.
# Run ONLY on the authorized target, with absolute task-owned paths filled below.
# Preserve every old env/config/attempt; never run this against the old env.
# Target commands/logs/receipts stay private. Never print/read an alternative password file.
set -euo pipefail
umask 077
: "${UV:?absolute reviewed uv 0.11.7 binary}"
: "${CONTROL_PYTHON:?reviewed control python for stdlib-only snapshot/wheel verification}"
: "${BASE_PYTHON:?original approved Python3.12.13 interpreterTarget}"
: "${OLD_PROJECT:?original combined projectRoot}"
: "${OLD_SITE:?original combined lib/python3.12/site-packages}"
: "${OLD_CONFIG:?original private config path, not DSN path}"
: "${NEW_ROOT:?fresh absent private task-owned installation root}"
: "${SOURCE:?exact PR47 source root verified against manifest}"
: "${MANIFEST:?original PR47 source-manifest.json}"
: "${VERIFIER:?reviewed verify_closure.py delivered alongside this file}"
: "${UV_CACHE_DIR:?authorized reusable dependency cache; no credential discovery}"
# REQUIRED REVIEW BEFORE RUNNING:
# 1. Confirm UV --version == uv 0.11.7, BASE_PYTHON is original approved target.
# 2. OLD_PROJECT pyproject+lock are the full combined project, not Factory-only lock.
# 3. Review copied pyproject: no workspace discovery/relative non-Factory path sources.
#    If present, preserve their exact approved referents in the NEW copy before uv;
#    stop for review of that concrete layout, not for an additional generic permission.
# 4. Pass the SAME extras/groups flags used by the accepted 95-package install as script arguments.
#    Default below is only correct when that install used default groups/extras.
# 5. Select --copy-mode full-copy on known non-CoW filesystems (including ext4 ENOTSUP).
#    Only clone mode requires an existing CoW receipt. Neither mode accepts hardlinks.
# 6. Review effective uv configuration: no unexpected user/parent uv.toml or UV_* overrides.
#    Preserve original reviewed project index/source settings (especially Torch). Do not blindly
#    add --no-config and thereby discard that provenance. Prefer an authorized cache on the
#    same proven filesystem. Fallback detection occurs AFTER copies may have happened; keep
#    the failed new root and provision full-copy worst-case space even though it is not accepted.
# 7. Resolve all variables explicitly; do not derive them by reading credentials.
COPY_MODE=clone
if [[ "${1-}" == --copy-mode ]]; then
  test "$#" -ge 2
  COPY_MODE="$2"
  shift 2
fi
case "$COPY_MODE" in
  clone) export UV_LINK_MODE=clone ;;
  full-copy) export UV_LINK_MODE=copy ;;
  *) printf '%s\n' 'INSTALL_COPY_MODE_INVALID' >&2; exit 2 ;;
esac
COPY_HELPER="${VERIFIER%/*}/copy_install_site.py"
test -f "$COPY_HELPER"
SYNC_SELECTION=("$@") # Original uv extras/groups only; do not override installation policy.
for arg in "${SYNC_SELECTION[@]}"; do
  case "$arg" in
    --link-mode*|--python*|--project*|--active|--directory*|--editable|--no-sources|--config-file*)
      printf '%s\n' 'INSTALL_SELECTION_OVERRIDE_REJECTED' >&2; exit 2 ;;
  esac
done
test ! -e "$NEW_ROOT"
mkdir -m 700 "$NEW_ROOT"
mkdir -m 700 "$NEW_ROOT/project" "$NEW_ROOT/evidence" "$NEW_ROOT/wheels"
export PYTHONDONTWRITEBYTECODE=1 SETUPTOOLS_USE_DISTUTILS=local AGNO_TELEMETRY=false
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV OPENCODE_GO FACTORY_TEST_DATABASE_URL UV_COMPILE_BYTECODE
NEW_PROJECT="$NEW_ROOT/project"
NEW_VENV="$NEW_ROOT/venv"
EVIDENCE="$NEW_ROOT/evidence"
# Before build/install, reserve two maximum admitted 8-GiB site trees (uv staging
# plus verified materialization), 2 GiB build scratch, and 2 GiB remaining headroom.
# Existing sealed environments are already reflected in the observed free space.
"$CONTROL_PYTHON" -I -B - "$NEW_ROOT" "$COPY_MODE" <<'PY_BUDGET'
import json, os, shutil, sys
from pathlib import Path
root, mode = Path(sys.argv[1]), sys.argv[2]
required = 20 * 1024**3 if mode == 'full-copy' else 12 * 1024**3
free = shutil.disk_usage(root).free
with (root/'evidence/disk-budget.json').open('x') as out:
    json.dump({'mode':mode,'availableBytes':free,'requiredBytes':required,
               'siteByteLimit':8*1024**3,'remainingHeadroomBytes':2*1024**3},out)
if free < required:
    print('INSTALL_DISK_BUDGET_BLOCKED',file=sys.stderr)
    raise SystemExit(2)
PY_BUDGET
"$UV" --version > "$EVIDENCE/uv-version.txt"
"$CONTROL_PYTHON" -I -B -c 'import pathlib,re,sys; sys.exit(0 if re.fullmatch(r"uv 0\.11\.7(?: \([^\n]*\))?\n?",pathlib.Path(sys.argv[1]).read_text()) else 2)' "$EVIDENCE/uv-version.txt"
"$UV" add --help > "$EVIDENCE/uv-add-help.txt"
"$UV" sync --help > "$EVIDENCE/uv-sync-help.txt"
# Stop before build if actual reviewed binary lacks required flags.
"$CONTROL_PYTHON" -I -B -c 'from pathlib import Path; import sys; p=Path(sys.argv[1]); assert all(x in (p/"uv-add-help.txt").read_text() for x in ("--constraints","--no-sync")); assert all(x in (p/"uv-sync-help.txt").read_text() for x in ("--no-editable","--no-install-project","--link-mode"))' "$EVIDENCE"
"$CONTROL_PYTHON" -I -B "$VERIFIER" snapshot --old-site "$OLD_SITE" --evidence "$EVIDENCE"
# Ordinary copies of TWO reviewed project files, never copying/reusing the sealed venv.
cp --reflink=never -- "$OLD_PROJECT/pyproject.toml" "$NEW_PROJECT/pyproject.toml"
cp --reflink=never -- "$OLD_PROJECT/uv.lock" "$NEW_PROJECT/uv.lock"
chmod 600 "$NEW_PROJECT/pyproject.toml" "$NEW_PROJECT/uv.lock"
# Build wheel normally through PEP517; hatchling==1.29.0 is pinned in exact source.
# Build dependencies are isolated from the runtime. No model/network API requests.
# Offline cache miss is BLOCKED; obtain the named public build/package artifact
# through the normal authorized package channel before a new preserved attempt.
"$UV" build --offline --wheel --python "$BASE_PYTHON" --no-python-downloads \
  --out-dir "$NEW_ROOT/wheels" "$SOURCE" > "$EVIDENCE/build.log" 2>&1
WHEEL="$NEW_ROOT/wheels/department_agent_factory-0.2.0-py3-none-any.whl"
"$CONTROL_PYTHON" -I -B "$VERIFIER" wheel --source "$SOURCE" --manifest "$MANIFEST" \
  --wheel "$WHEEL" --evidence "$EVIDENCE"
"$UV" venv --offline --python "$BASE_PYTHON" --no-python-downloads "$NEW_VENV" \
  > "$EVIDENCE/venv.log" 2>&1
export UV_PROJECT_ENVIRONMENT="$NEW_VENV"
# uv rewrites ONLY the new project's Factory requirement/source to this exact local wheel.
# It creates a DERIVED combined lock. Same version number is insufficient: wheel bytes are pinned.
"$UV" add --project "$NEW_PROJECT" --offline --no-sync --python "$NEW_VENV/bin/python" \
  --no-python-downloads --constraints "$EVIDENCE/constraints.txt" "$WHEEL" \
  > "$EVIDENCE/lock.log" 2>&1
"$UV" sync --project "$NEW_PROJECT" --offline --frozen --no-editable --no-install-project \
  --python "$NEW_VENV/bin/python" --no-python-downloads --link-mode "$UV_LINK_MODE" "${SYNC_SELECTION[@]}" \
  > "$EVIDENCE/sync.log" 2>&1
if [[ "$COPY_MODE" == clone ]]; then
  "$CONTROL_PYTHON" -I -B -c 'from pathlib import Path; import re,sys; sys.exit(2 if re.search(r"fall(?:ing)? back|fallback|full.copy",Path(sys.argv[1]).read_text(),re.I) else 0)' "$EVIDENCE/sync.log"
else
  # Both trees belong exclusively to this new attempt. Preserve the logical venv
  # prefix: move only site-packages to staging, then materialize it back in place.
  # Never run this move on OLD_SITE. No interpreter/package startup during copy.
  "$CONTROL_PYTHON" -I -B - "$NEW_ROOT" <<'PY_STAGE'
import os, stat, sys
from pathlib import Path
root = Path(sys.argv[1])
site = root/'venv/lib/python3.12/site-packages'
staging = root/'installed-site-staging'
info = site.lstat()
if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or staging.exists():
    print('INSTALL_SITE_STAGE_BLOCKED',file=sys.stderr)
    raise SystemExit(2)
os.chmod(site.parent,0o700)  # Fresh attempt only; never chmod a cached/source file.
os.rename(site,staging)
PY_STAGE
  "$CONTROL_PYTHON" -I -B "$COPY_HELPER" --source-root "$NEW_ROOT/installed-site-staging" \
    --destination-root "$NEW_VENV/lib/python3.12/site-packages" --receipt "$EVIDENCE/full-copy-receipt.json"
fi
"$UV" pip check --python "$NEW_VENV/bin/python" > "$EVIDENCE/dependency-check.log" 2>&1
# Direct interpreter, NEVER uv run (which could resync). No source PYTHONPATH.
# Final verifies exact installed payload, all95versions, all direct entrypoint imports/symbols,
# policy contract, startup/full-site inventory, and a newly captured interpreter contract.
# Reads OLD_CONFIG ONLY; never follows databaseUrlFile. Writes fresh diagnostic-config.json.
"$NEW_VENV/bin/python" -I -B "$VERIFIER" final --source "$SOURCE" --manifest "$MANIFEST" \
  --wheel "$WHEEL" --evidence "$EVIDENCE" --project "$NEW_PROJECT" --venv "$NEW_VENV" --config "$OLD_CONFIG"
# Stop at successful closure for operator receipt review. Next command after closure PASS:
# "$NEW_VENV/bin/python" -B "$SOURCE/scripts/run_research_baseline.py" \
#   --database-preflight --config "$EVIDENCE/diagnostic-config.json"
# Only this existing runner may then read the original authorized DSN for normal authentication.
# Do NOT launch bootstrap_research_control/create_app/assembly/train to repair installation.
# New inventory is installation evidence, not a reusable runtime admission receipt. Later original
# canonical execution captures its own evidence again under a fresh, separately named workspace.
