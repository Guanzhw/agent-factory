# Canonical research compiler search path repair

## Completed local result — 2026-10-07 09:48 UTC

The local owner verified training and independent evaluation complete with
`val_bpb=1.6711944975804394`, both stage audits PASS and resource claims RELEASED.
See [first real local baseline acceptance](RESEARCH_BASELINE_ACCEPTANCE.md) for exact pins, timings, hashes and remaining boundaries.
The failure/UNKNOWN and launch-blocking statements below describe the earlier
handoff state; they are preserved, not the current status of the completed run.
This result requires no automatic rerun.

The target reports a real Torch/GPU launch on PR50, followed after approximately
207 seconds by an Inductor compiler failure before checkpoint/evaluation:
`collect2` could not find `ld`, although `/usr/bin/ld` exists. This is a failed
executed attempt, not a never-dispatched attempt and not scientific success.

The mechanism is reproduced without GPU: the same absolute `/usr/bin/gcc`
shared-library command fails without PATH and succeeds with `/usr/bin:/bin`.
Guardian deliberately starts from a fresh environment; the outer shell's PATH
is not inherited. The canonical runner omitted PATH, whereas the earlier
optimizer compile probe supplied one explicitly.

## Scope and identity

The fix is owned by `scripts/run_research_baseline.py:launch_environment` and
sets the literal trusted system search path `/usr/bin:/bin`. No arbitrary host
PATH, current directory, venv/bin, `/usr/local/bin`, CUDA bin directory, compiler
override or credentials are inherited. Guardian filtering and existing resource,
source, interpreter, namespace and custody controls remain unchanged. The launch
spec already permits PATH and fingerprints its value; this changes only a new
attempt's spec, never an old sealed record.

On the reproduced distro GCC, `cc1` and `collect2` resolve through GCC's versioned
installation directories; `as` and `ld` need the system tool search path. Do not
add compiler internals or guessed CUDA paths to PATH. A target that requires a
different toolchain must provide a concrete missing-tool result for separate
review. This fix does not establish that all Inductor, Triton or GPU compilation
will succeed on the target.

## Preserve and close the executed failed attempt

Keep its workspace, compiler error, logs, inventory, journal, plans and receipts.
Latest local read reports `FAILED` / exit 1, `stoppedProof: true`,
`capacityHeld: false`, final `STOPPED` / `cleanupConfirmed: true`; GPU ledger
release remains **UNKNOWN** and the complete receipt identity chain is unverified.
These are local reports, not cloud acceptance. The local executor is inspecting
that release chain read-only; a new canonical launch remains blocked on that
concrete resource proof, not on another generic permission request.

Use the local executor's original-identity cleanup/inspection to establish its
terminal native task and queue closure, stopped original guardian/child group,
positive compute reclamation and GPU release. Reuse already verified cleanup
observations while old writers remain stopped. Do not replay unknown ACKs or
rewrite the failure. Because this attempt actually dispatched, the PR53
`--released-never-dispatched` audit is **not applicable** to it. Missing checkpoint
or evaluation output is expected for this failure and is not a reason to invent
receipts. The fixed root-only queue SQL remains applicable only if its exact
profile conditions hold; it does not itself verify resource release.

## Source-only installation; keep accepted PR50 package installation

The installed Factory package payload remains exact PR50
`997013114a8c533c84078d174b220e541ea19f9a`. This repair changes the external runner
script only; do not reinstall packages, alter the accepted 95-version lock,
mutate the sealed site tree, or repoint the historical PR50 source checkout.
Keep the successful full-closure receipt and both earlier preflight results as
historical evidence. A new attempt still captures fresh inventory/contracts.

Set `FIX_COMMIT` to the full reviewed commit delivered with this handoff,
`REPOSITORY` to the existing trusted fetched repository, and `FIX_SOURCE` to a
fresh absent absolute source directory. Use one Bash session:

```sh
set -euo pipefail
umask 077
test ! -e "$FIX_SOURCE"
git -C "$REPOSITORY" fetch origin "$FIX_COMMIT"
git -C "$REPOSITORY" cat-file -e "$FIX_COMMIT^{commit}"
git -C "$REPOSITORY" worktree add --detach "$FIX_SOURCE" "$FIX_COMMIT"
test "$(git -C "$FIX_SOURCE" rev-parse HEAD)" = "$FIX_COMMIT"
test -z "$(git -C "$FIX_SOURCE" status --porcelain --untracked-files=all --ignored)"
# Factory payload and controller remain the exact accepted PR50 bytes.
git -C "$FIX_SOURCE" diff --exit-code \
  997013114a8c533c84078d174b220e541ea19f9a "$FIX_COMMIT" -- \
  platform/agent_factory scripts/bootstrap_research_control.py
```

Run the new entrypoint from this separate verified checkout with the already
accepted target interpreter. The historical PR50 source verifier remains pinned
to its original source; do not pass the changed runner checkout to it or claim
that it verifies the changed runner. Git's reviewed exact commit is the new
runner source pin. No package payload changed and no new wheel is required.

## Bounded target compiler check, no GPU

Use `CONTROL_PYTHON` for the reviewed control interpreter and `PROBE_ROOT` for a
fresh absent private scratch directory outside every sealed installation and old
attempt. The command imports only the new runner's stdlib module definitions,
constructs its exact environment using a synthetic device selector, and compiles
small C/C++ shared libraries. It does not load those libraries, import Torch,
query a GPU, open the database or access credentials. Retain outputs privately.

```sh
"$CONTROL_PYTHON" -I -B - "$FIX_SOURCE" "$PROBE_ROOT" <<'PY'
import importlib.util, json, os, subprocess, sys
from pathlib import Path
source, root = map(Path, sys.argv[1:])
assert source.is_absolute() and root.is_absolute() and '..' not in root.parts
assert not root.exists() and not root.is_symlink()
os.umask(0o077)
root.mkdir(mode=0o700)
program, cache = root/'program', root/'cache'
program.mkdir(); cache.mkdir()
spec = importlib.util.spec_from_file_location('reviewed_runner', source/'scripts/run_research_baseline.py')
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
env = runner.launch_environment({'deviceUuid': 'synthetic-no-gpu'}, program, cache)
assert env['PATH'] == '/usr/bin:/bin'
results = []
for language, compiler, code in (
    ('c', '/usr/bin/gcc', 'int synthetic(void) { return 7; }\n'),
    ('c++', '/usr/bin/g++', 'extern "C" int synthetic(void) { return 7; }\n'),
):
    output = program/('probe-' + language.replace('+', 'p') + '.so')
    with (root/(output.stem + '.log')).open('xb') as log:
        completed = subprocess.run([compiler, '-shared', '-fPIC', '-x', language,
            '-', '-o', str(output)], input=code.encode(), cwd=program, env=env,
            stdout=log, stderr=subprocess.STDOUT, timeout=20, check=False)
    ok = completed.returncode == 0 and output.is_file() and output.stat().st_size > 0
    results.append({'language': language, 'passed': ok})
    if not ok:
        print(json.dumps({'status': 'COMPILER_CHECK_FAILED', 'results': results}))
        raise SystemExit(2)
print(json.dumps({'status': 'COMPILER_CHECK_PASS_NO_GPU', 'results': results}))
PY
```

A missing compiler, timeout or nonzero exit blocks dependent launch; inspect that
private log. This is a compatibility check, not a new trust mechanism for host
binaries and not a Torch/Inductor acceptance result. The host's `/usr/bin` and
`/bin` remain administrator-managed trusted directories under the existing local
cooperative execution model; do not point either at task-writable tool shims.

## Separate canonical attempt

Once the executed failed attempt is positively released and queue-closed, retain
the existing approved scientific inputs, evaluator, limits, model and database
configuration. Derive a new private config with a fresh absent workspace and new
request ID, using the [existing exclusive-create derivation](PR50_RELEASED_CUSTODY_HANDOFF.md#new-attempt-after-validated-release-and-installation-closure); never reuse
the old training directory or claim its checkpoint/evaluation completed.

Use the accepted installation's Python for both preflights, now through the fixed
runner. `RECOVERY_CONFIG` is the new private config; `ACCEPTED_PYTHON` is the
original accepted venv/bin/python. Do not add `-I` to the runner because its
reviewed sibling-import contract requires the scripts directory.

```sh
export PYTHONDONTWRITEBYTECODE=1 SETUPTOOLS_USE_DISTUTILS=local AGNO_TELEMETRY=false
"$ACCEPTED_PYTHON" -B "$FIX_SOURCE/scripts/run_research_baseline.py" \
  --preflight --config "$RECOVERY_CONFIG"
"$ACCEPTED_PYTHON" -B "$FIX_SOURCE/scripts/run_research_baseline.py" \
  --database-preflight --config "$RECOVERY_CONFIG"
"$ACCEPTED_PYTHON" -B "$FIX_SOURCE/scripts/run_research_baseline.py" \
  --config "$RECOVERY_CONFIG"
```

Require each exit code and fixed-enum preflight result before the next command.
The final command is the already-authorized local canonical attempt, once, with
no automatic retry. Normal fresh admission includes the new PATH in the sealed
launch spec. Record actual training/checkpoint, independent evaluation and final
compute/GPU release separately. Cloud compiler/guardian tests do not establish
baseline success. Preserve any new failure for bounded original-identity cleanup.

## Cloud validation evidence

The old no-PATH runner failed the real guardian compiler regression with child
exit 1 and `collect2: cannot find ld`; the fixed runner passed. Eleven runner
tests plus one bounded guardian compiler test pass, including exact environment
allowlist and hostile PATH/compiler-override filtering. Ruff passes and Pyright
reports zero errors. Eleven existing UV guardian and nine diagnostic regressions
also pass (32 targeted tests total). The exact inline C and C++ smoke above was also executed
successfully in private cloud scratch, without Torch or GPU. An independent
reviewer separately reproduced the old/fixed compiler behavior and found no
blocking implementation or handoff issue. Exact-head CI results are recorded in
the draft PR linked with the final delivered commit; no target result is implied.
