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
this fixed probe CLI with public metadata arguments only. The report also
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

## Launch and uv boundaries

Run this probe only through an explicitly approved diagnostic launch. The
planned guardian integration must preserve the selected venv's logical argv0,
pin and verify the executable FD and interpreter/venv identities, review Python
startup inputs before effects, and supply `-B` plus a clean environment. This
script does not implement that launcher or independently follow interpreter
symlinks. The provider's launch integration and target evidence remain separate
acceptance work; do not infer support from this probe's existence.

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
