# Read-only uv target diagnostics

`scripts/probe_research_uv.py` observes the Python process already running it.
It neither creates an environment nor launches another interpreter. It installs
nothing, uses no network or credentials, imports no research/ML packages, and
does not run generated source. Use only operator-selected **public metadata**
paths: output includes bounded interpreter/import paths and file identities, so
review it before publishing it. Never supply secret files as metadata inputs.

The exact CLI is:

```text
probe_research_uv.py [--expected-venv ABSOLUTE_DIRECTORY]
                    [--venv-config ABSOLUTE_PUBLIC_PYVENV_CFG]
                    [--project-lock ABSOLUTE_PUBLIC_UV_LOCK]
```

All options are observations, not execution authority. There is no `--config`,
shell command, arbitrary package name, installer, or alternate launch mode.
Without `--expected-venv`, the result explicitly includes
`EXPECTED_VENV_UNSPECIFIED`. Even with matching prefixes and no issues, the
status remains `DIAGNOSTIC_ONLY`. Exit 0 means a bounded report was emitted,
**not** that the environment or research launch passed acceptance. Exit 2 is a
sanitized observation failure. Unknown CLI arguments are rejected by argparse.

## What the report establishes

Schema 1 includes platform, implementation/version, `sys.executable`, prefix,
base prefix, exec prefix, base exec prefix, `sys.path`, selected startup flags,
and bytecode cache prefix. Paths are limited to 64 entries of 4096 characters.
`sys.orig_argv` is recorded with at most 32 strings of 4096 characters, so use
this fixed probe CLI with public metadata arguments only. The versioned uv
guardian adds its internal multiline `-c` bootstrap code to these arguments.
Newlines and other non-NUL control characters in argv are preserved using JSON
escaping, never printed as raw output lines; NUL is rejected. Path fields retain
their stricter no-control-character rule. The report also
includes `sys._base_executable` when it is a string and, on Linux, the passive
`/proc/self/exe` symlink target when readable. These expose logical invocation
versus executed binary differences for FD-launch diagnosis; they do not pin or
authenticate either executable. No environment dump or `/proc` command line is
read. Missing or unsupported binary-link observations are null.
The entire JSON output is capped at 128 KiB. Requested metadata files are
limited to 1 MiB. Regular-file hashes use no-follow/nonblocking opens and
before/after identity checks where supported. Symlinks are reported without
reading their targets; multi-link files are not hashed. Platforms without the
required safe-open flags report `READ_IDENTITY_UNSUPPORTED`. Parent directories
and the host remain operator-trusted; this is not the provider's pinned-root
custody verifier. `pyvenv.cfg` and `uv.lock` contents are never executed, parsed,
or included in output.

Fixed top-level names `agent_factory`, `torch`, `tiktoken`, and `pyarrow` use
private standard-library `FileFinder.find_spec` lookups with the standard
source/bytecode/extension loaders. Loaders are **not executed**. Global
`sys.meta_path` and custom path hooks are not consulted. All filesystem matches
are reported to expose shadow candidates. Zip/custom importers and actual
module imports are deliberately not reproduced; missing/namespace/shadow
results cannot establish import compatibility. Lexical path checks are clues,
not symlink resolution or executable provenance proof.

`startupSafetyVerified`, `packageImportVerified`, `fdLaunchVerified`,
`scientificExecutionVerified`, and `productionReady` are always false. In
particular, Python startup precedes this script: `-I` alone does not prevent
site `.pth` processing. An already-started process cannot retroactively prove
that startup code was harmless. `-S` avoids site startup but also changes the
observed environment on some Python versions; it is not a faithful substitute
for a reviewed production launch. A clean result cannot verify GPU execution,
Torch imports, numeric results, or the original upstream research protocol.

## Commands for the already authorized diagnostic

For Linux/WSL, set these variables to **existing, reviewed absolute paths**;
the values below are placeholders, not a selected target. `project` is the
installed target's own uv project, `venv` its existing isolated environment, and
`probe` the reviewed immutable copy of this script. The project's startup files
must already have been reviewed before normal Python startup is attempted.

```bash
project='/absolute/reviewed/existing/project'
venv='/absolute/reviewed/existing/venv'
probe='/absolute/reviewed/probe_research_uv.py'
test -d "$project" && test -d "$venv" && test -f "$venv/pyvenv.cfg" \
  && test -f "$project/pyproject.toml" && test -f "$project/uv.lock" \
  && test -f "$probe" || exit 2
UV_PROJECT_ENVIRONMENT="$venv" uv run --project "$project" --offline --no-sync python -B "$probe" --expected-venv "$venv" --venv-config "$venv/pyvenv.cfg" --project-lock "$project/uv.lock"
```

This command observes normal startup in the existing environment. It does not
sync/install or authorize downloading anything. Stop on a missing environment,
interpreter, project or dependency; do not switch to another environment or
remove `--offline`/`--no-sync`. Do not pass provider credentials or secret paths.
Normal startup may process the reviewed `.pth` files; this command is not a
`-S` startup-isolation test. The probe itself writes only bounded JSON to stdout.

The corresponding **direct FD diagnostic** is a trusted-launcher operation,
not another mode of the probe. The following is an exact Python API recipe for
the existing reviewed Factory launcher **after** the operator has supplied the
canonical contract and approved target hash. It is deliberately not a turnkey
command with invented identity pins. The launcher imports the existing reviewed
Factory `research_interpreter` helper, which does not import ML packages. The
shown variables are trusted launcher inputs, never model/request fields.

```python
import os
from agent_factory.research_interpreter import open_interpreter, recheck_interpreter

# Supplied by reviewed operator setup; none is inferred with Path.resolve():
# contract: canonical capture_interpreter_contract(...) string
# target_sha256: independently approved executable-byte hash
# venv, project, probe: exact absolute paths from the normal diagnostic
# diagnostic_root: existing private directory with reviewed, empty cache prefix
logical = venv + '/bin/python'
fixed_args = [
    '--expected-venv', venv,
    '--venv-config', venv + '/pyvenv.cfg',
    '--project-lock', project + '/uv.lock',
]
cleanenv = {
    'HOME': diagnostic_root,
    'PYTHONNOUSERSITE': '1',
    'PYTHONPYCACHEPREFIX': diagnostic_root,
}
if os.execve not in os.supports_fd:
    raise SystemExit('FD_DIAGNOSTIC_UNSUPPORTED')
os.chdir(diagnostic_root)
fd = open_interpreter(contract, logical, target_sha256)
try:
    recheck_interpreter(contract, logical, target_sha256, fd)
    os.execve(fd, [logical, '-B', probe, *fixed_args], cleanenv)
finally:
    os.close(fd)  # reached only if exec did not replace this process
```

This replaces the disposable diagnostic launcher's process; it must not be run
inside the API server or another persistent service. Retain the existing trusted
launcher's time/output limits and original-process cleanup. Failed contract
validation, changed files or unsupported FD execution are stopping conditions;
there is no symlink-resolving fallback or unverified retry. The full identity
contract is required even when the logical interpreter is an ordinary uv link.

Compare normal and direct-FD JSON fields `runtime.origArgv`, `executable`,
`baseExecutable`, `executedBinaryLink`, `prefix`, `execPrefix`, `basePrefix`,
`baseExecPrefix`, `sysPath`, `flags`, `cachePrefix`, plus static package origins.
In particular, a successful `execve` syscall does not prove venv prefix
discovery succeeded. The direct diagnostic intentionally runs the probe rather
than the final guardian's `-c` prelude, so it can report a wrong prefix. The
final versioned guardian below rejects a wrong prefix before the intended
entrypoint instead. These observations are not interchangeable acceptance
claims. This documentation update did not execute either example.

## Launch and uv boundaries

This probe performs observation, without environment installation, upstream/ML
execution, or changes to host configuration. Separately authorized local setup
and resource use retain their existing scope; this document adds no permission
requirement or restriction to that other work. The
implemented `UvResearchProcessSpec` is a separate versioned opt-in contract;
regular `ResearchProcessSpec` remains unchanged. The probe itself does not
implement a launcher or independently follow interpreter symlinks.

Trusted operator bootstrap constructs the canonical interpreter contract with
`research_interpreter.capture_interpreter_contract`:

```python
contract = capture_interpreter_contract(
    executable=logical_venv_python, sha256=approved_target_sha256,
    project_root=project, venv_root=venv,
    approved_interpreter_roots=approved_roots,
    pyvenv_cfg=public_pyvenv_cfg, pyproject_toml=public_pyproject,
    uv_lock=installed_project_lock, package_inventory=public_inventory,
    package_files=exact_inventory_runtime_and_startup_files,
)
spec = UvResearchProcessSpec(
    executable=logical_venv_python, sha256=approved_target_sha256,
    argv=('-B', absolute_entrypoint, '--config', sealed_config),
    working_directory=program_root,
    working_directory_identity=program_root_device_inode,
    environment=reviewed_clean_environment,
    interpreter_contract=contract,
)
```

This is an operator API shape, not a ready-to-run target configuration. All
values must come from the existing trusted identity/storage/plan path; no
request or model may choose them. For this standalone probe, its own fixed CLI
arguments replace the illustrated research entrypoint's `--config` arguments.
The probe does not parse a research run configuration.

The contract captures an explicitly approved bounded interpreter symlink chain,
regular target bytes, root identities, startup namespaces and pinned project,
venv and package files. The guardian rechecks it immediately before original
FD execution and preserves logical argv0. Its fixed `-B -c UV_STARTUP_CODE`
prelude checks actual `sys.prefix`, `sys.exec_prefix`, logical executable,
user-site exclusion, no-bytecode/cache settings and bounded import-path shape
before calling the intended entrypoint. A failed check exits 126 with the
finite `RESEARCH_UV_STARTUP_UNVERIFIED` diagnostic. Accepting an executable FD
alone is not treated as proof of correct venv discovery.

Environment inventory schema 2 opts into `research-uv-interpreter-v1` with the
reviewed `uv01219-virtualenv-startup-v1` profile. Its exact `_virtualenv.py` and
`_virtualenv.pth` hashes are fixed in `research_environment_observer.UV_STARTUP_FILES`;
arbitrary `.pth` or customization code is not thereby authorized. The interpreter
contract is in the launch spec, outside inventory bytes, to avoid a hash cycle.
Its package pins include the exact inventory files, trusted execution-library
files and these two startup files. This is static file evidence, not proof of
successful package import or GPU compatibility.

Comparison manifest schema 2 keeps `environment.lockfileSha256` for the
installed adapted project's lock and `environment.upstreamLockfileSha256` for
the unchanged pinned upstream lock. They are not interchangeable. Target
startup compatibility and scientific execution remain unverified until their
separate actual acceptance evidence exists; this diagnostic module cannot
upgrade those claims.

For project maintenance, use the existing project through
`uv run --no-sync --offline`; do not activate or modify unrelated environments.
Future environment creation must use a new unique absolute
`UV_PROJECT_ENVIRONMENT` and its independently reviewed project/lock. Factory's
`uv.lock` is not the upstream scientific dependency lock. Preserve upstream's
lock and separately review any combined adaptation lock. `uv sync --frozen
--no-editable --link-mode copy` is an installation operation requiring its own
authorized target; package copy mode does not turn uv's interpreter symlink into
a regular executable. No environment creation or ML execution is demonstrated
by this stage's synthetic unit tests.
