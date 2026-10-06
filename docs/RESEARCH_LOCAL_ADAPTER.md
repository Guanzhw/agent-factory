# Operator-owned local research adapter

This adapter composes the existing immutable-plan, resource lease, original
process journal, checkpoint custody, and independent evaluator interfaces. It
adds no HTTP endpoint, queue, launch loop, dependency installer, or alternate
lifecycle. The offline tests do **not** execute upstream code, Torch, GPU kernels,
training, or scientific evaluation. Actual target execution remains blocked until
an operator supplies and verifies all external inputs and the target attestor.

## Identities before launch

Use `research_local_driver.derive_local_identities(upstream_files,
candidate_files, microbatch=8)` first. It calls the pinned offline source adapter
and measures the fixed execution-library files in the actual `agent_factory`
package. The result contains an independent upstream adaptation receipt and four
local identities, each with canonical `content` bytes, `sha256`, and `sizeBytes`:

- `baseline`: generated baseline training source, shared architecture/data source,
  and measured execution-library sources.
- `candidate`: corresponding candidate source and the same shared sources. It
  does not change the baseline identity merely by changing candidate parameters.
- `evaluatorCode`: generated evaluator, shared architecture/data, and the measured
  execution-library sources.
- `evaluatorConfiguration`: fixed adapter revision, microbatch, seed 42, sequence
  length 2048, evaluation budget 20,971,520 tokens, `val_bpb`, and no initial
  checkpoint.

Set the comparison manifest's `baselineSourceManifestSha256` to the **local**
baseline identity, and its evaluator `code`/`configuration` artifact identities
to these derived values. Choose the matching local variant identity for the
training or evaluator provider. Preserve the upstream receipt separately: this
adapted SDPA baseline is not the original upstream score protocol. The driver
rederives and checks these identities; caller-provided equivalent-looking hashes
are insufficient. This stage supports only `initialCheckpoint: null`.

## Bootstrap API

`build_local_driver(...)` returns a trusted callable for
`ResearchLocalProvider(program_verifier=driver,
source_fingerprint=driver.configuration_fingerprint, ...)`. Required operator
arguments are:

- Original pinned upstream/candidate byte maps, `entrypoint` selected from
  `train_baseline.py`, `train_candidate.py`, `evaluate.py`, and the manifest and
  matching `variant_sha256`.
- Precreated empty private `program_root` and `RootIdentity(device, inode)`.
- A separate precreated private `cache_root` and its root identity.
- An exact `ResearchProcessSpec`, including the independently pinned Python
  executable and its hash.
- `operator_config`: `inputRoot`, `inputRootIdentity`, `tokenizer`, `tokenBytes`,
  `dataset`, and `outputCheckpoint: null`. File shapes are the exact pure
  `research_torch_runtime.validate_runtime_configuration` contract. No pickle
  tokenizer, caller-selected argv, or model-supplied path is accepted.
- Three immutable `InputPin` values with `kind='environment'` and labels
  `environment-lockfile`, `environment-inventory`, `environment-kernel`, matching
  the manifest's environment byte identities.
- `plan_reader(plan_id, owner)`, normally the existing store's owned plan lookup.
  The driver checks `digest(plan) == record.binding.planHash` and uses the actual
  `plan.fingerprint`; these two hashes are not interchangeable.
- Synchronous `before_effect()`, rechecking current authority and storage custody.
  It must raise on denial. An asynchronous callback or `False` fails closed.
- A mandatory trusted `environment_verifier`, described below.
- For training, `reserve_output(binding)`. For evaluation, `evaluation_factory`
  instead; never both.

Each program root is single-use for one original allocation: dynamic task/lease/
provider IDs are sealed into it. Rechecking that same allocation is supported;
a new allocation or variant needs a separate empty root and a separately pinned
immutable target/spec configuration. Do not delete or recycle the old root to
make another task fit. This stage does not provide an automatically reusable
per-allocation target allocator.

All paths and callbacks belong to trusted operator bootstrap, not request bodies,
materials, models, or source-generated configuration. The provider's original
journal supplies owner, task, native run, plan, lease, and provider job IDs.

### Actual launch specification

The driver's `validate_spec(spec)` is mandatory at provider construction. It
requires exact equality with the statically pinned spec, with:

```python
argv = ('-B', absolute_entrypoint_path, '--config', absolute_run_config_path)
working_directory = str(program_root)
working_directory_identity = (program_device, program_inode)
```

`-B` prevents bytecode generation but, alone, does not stop Python from reading
existing compiled bytecode. The spec therefore also **requires**
`PYTHONPYCACHEPREFIX` equal to the sealed `program_root`. The exact sealed root
contains only the generated files, config, and seal, with no directories; the
absolute-path cache tree that Python would consult under this prefix is absent.
This keeps existing runtime-package `__pycache__` files out of the checked-source
execution path, and `-B` prevents creating a replacement cache tree. Missing or
changed prefixes, using the compiler cache root as this prefix, or adding a
directory to the sealed program root all fail validation. This is a fixed launch
contract, not a claim that ML execution was tested.

The environment contains explicit `HOME`, `TORCHINDUCTOR_CACHE_DIR`,
`TRITON_CACHE_DIR`, `CUDA_CACHE_PATH`, and `TMPDIR`, all equal to the separate
private cache root. If present, `HF_HOME` must use that same root. Retain the
`ResearchProcessSpec` offline flags (`HF_HUB_OFFLINE`, `HF_DATASETS_OFFLINE`,
`TRANSFORMERS_OFFLINE`, `PYTHONNOUSERSITE`, all `1`) and explicit operator GPU
visibility. The existing guardian constructs a clean environment; do not forward
provider keys or the parent environment. Program/cache roots may not contain
one another. Root identities are rechecked before launch. Resource and disk
limits, cache cleanup, executable verification, and original-process termination
remain owned by the existing provider and storage lifecycle.

### Trusted checkpoint callbacks

A training reservation callable has a stable `configuration_fingerprint` for
its storage policy. Wrap the existing store method rather than adding attributes
to a bound Python method:

```python
class OutputReservation:
    configuration_fingerprint = operator_storage_policy_sha256

    def __call__(self, binding):
        return checkpoint_store.reserve(binding, disk_bytes=limits.disk_bytes)
```

It returns `{root, basename, rootIdentity}` for that exact original binding.
Repeated verification may recheck the same idempotent reservation; it must never
allocate a new execution or lower a held reservation. Importing a completed
checkpoint is a separate existing `ResearchCheckpointStore` operation.

An evaluator's trusted `evaluation_factory` also has a stable
`configuration_fingerprint` for its original-artifact resolution policy; it is
pinned in the provider's static identity and rechecked on every hook. Its
`evaluation_factory(record, binding)` call returns exactly
`{checkpoint, evaluationContract}`. It uses the existing trusted artifact reader
for the original training checkpoint. The pure runtime validator cross-checks
artifact hash/size, all original training identities, current evaluator identities,
manifest, and variant. `outputCheckpoint` remains null during evaluation.
Safetensors format/content checks remain the existing checkpoint reader's duty;
staging only validates bounded exact bytes. No untrusted training stdout grants
a checkpoint or evaluator identity.

## Environment and runtime verification gate

`environment_verifier` must be a trusted callable with a stable 64-hex
`configuration_fingerprint`. Its request contains the exact manifest environment,
runtime-kernel and sample-set identities, that configuration fingerprint, the
actual launch spec, the actual installed package location, and measured hashes
of the fixed execution-library sources, the already validated `runtimeConfig`,
and the three `environmentPins` with their actual private file locations. It must
return exactly:

```text
schema: 1
status: VERIFIED
requestSha256: hash of the exact request using the repository canonical digest
observationSha256: hash of its actual target observations
```

A missing verifier, boolean result, mismatched request hash, or unavailable target
blocks launch. The concrete read-only observer verifies bounded bytes of the selected interpreter,
venv configuration, enumerated package inventory, fixed kernel/adapter files,
and declared shard/split identity. It must reject unenumerated import hooks or
unsupported layouts rather than claiming success. This is static file evidence,
not proof of actual Python import execution, loaded native libraries, CUDA/GPU
compatibility, token-stream consumption, or numerical results. Source-file hashes
alone do not establish those runtime facts. Merely hashing an operator inventory
file is insufficient even for static package verification: actual package files
and their closed inventory must also be checked.
Use a stable hash of checked identities for equivalent observations; a changed
observation invalidates the previously sealed descriptor. Unit tests use an
explicit synthetic observer and do not satisfy this production gate. This module supplies no hardware attestor and defaults no observer. The separate
read-only environment observer does not import Torch or run a subprocess. This
stage has not scanned a real ML environment; its tests use synthetic files. Host,
Python/stdlib loader behavior, and trusted operator policy remain explicit trust
boundaries.

The driver also reads fixed sources directly from its own installed package,
using bounded descriptor-relative no-follow reads and before/after identity
checks. Caller-provided alternate runtime-source paths are not accepted. It
rechecks those hashes immediately around staging/verification. This covers the
adapter's execution libraries; it does not replace environment attestation of
Torch, tokenizer libraries, compiled dependencies, Python, GPU or kernel code.

## Dynamic sealing and proof

The static configuration fingerprint covers source adaptation, derived execution
identities, measured library source, operator input pins, the exact launch spec,
cache identity, and attestor/storage policy. It excludes future journal IDs.

The original provider prelaunch hook receives those IDs and creates a bounded
`run-config.json`. The driver validates its exact semantic relationship to the
manifest, derives input pins from the very paths/config being executed, reserves
the original output, and writes the five generated sources plus config into an
empty private root. A final `program.seal.json` pins the immutable descriptor,
including evaluator checkpoint artifact identity, evaluation-contract hash, and
environment-observation receipt hash. Partial or unknown staging is never adopted.
Existing sealed data is reverified against the exact reconstructed descriptor;
there is no launch retry or mutation of sealed source/config.

The callable returns exactly seven fields: `schema: 1`, `descriptorSha256`,
`sourceSha256` (the static configuration fingerprint), `manifestSha256`,
`variantSha256`, `checkpoint`, and `evaluationContractSha256`. The last two are
null for training. The existing provider adds lease/process identity and persists
this proof in its original allocation record. Neither this proof nor successful staging
means execution or scientific verification succeeded.

Private staging requires POSIX no-follow directory operations, owner-only `0700`
directories, `0600` regular files, and one link per file. Generated files are at
most 4 MiB each; runtime config is at most 1 MiB. Input files are at most 2 GiB each
and 16 GiB total. The caller retains its original custody/authority lock through
verification and actual launch. This is not a replacement filesystem sandbox.

## Windows and WSL: planned isolated uv project environments

**Environment templates only; this cloud adapter stage does not create or
synchronize a scientific environment, download interpreters, or execute ML/kernel
code.** Target execution belongs to the separately authorized local executor.
The commands below still require a reviewed project/lock pair and verified target
prerequisites. They do not establish that this research launch path is usable
with a uv-created environment.

Use one independently owned uv project and one new, unique **absolute**
`UV_PROJECT_ENVIRONMENT` path for each Windows or WSL project. Never point that
variable at an existing environment, the system interpreter prefix, another
project, or the current Factory environment. The variable redirects uv's project
environment; reusing an absolute environment path across projects can overwrite
its installed package set. See the [official project-environment documentation](https://docs.astral.sh/uv/concepts/projects/config/#project-environment-path).

Keep three lock identities distinct:

- This repository's `uv.lock` describes the Factory application and tests. It is
  not a scientific upstream dependency lock or proof of a CUDA environment.
- Preserve the pinned upstream `uv.lock` bytes and hash unchanged as upstream
  provenance. Do not replace it with the Factory lock or edit it in place.
- The adapted Factory-plus-scientific runtime requires its own reviewed uv
  project and compatible lock, interpreter/platform selection, package-source
  review, and recorded differences from upstream. Such a combined lock has not
  been supplied or validated by this documentation. `--frozen` does not resolve
  that missing compatibility review and does not itself prove a project/lock
  pair is current.

Local help was checked with **uv 0.12.19** on 2026-10-06: `uv sync --frozen` does
not update the lock, `--no-editable` disables editable installations, and
`--link-mode copy` copies installed package files from the global cache. Reuse the
normal uv cache; do not clear it, disable it, or mutate existing environments to
save space. Copy mode avoids sharing installed package files through cache
hardlinks. It does **not** mean the virtualenv interpreter itself is copied.
The [official CLI reference](https://docs.astral.sh/uv/reference/cli/#uv-sync)
describes these separate options.

A future WSL/Linux synchronization template, **not executed here**:

```sh
(
  set -eu
  research_project=/absolute/path/to/reviewed-adapter-project
  research_env=/absolute/path/to/new-unique-project-environment
  test -f "$research_project/pyproject.toml"
  test -f "$research_project/uv.lock"
  test ! -e "$research_env"
  test ! -L "$research_env"
  UV_PROJECT_ENVIRONMENT="$research_env" uv sync \
    --project "$research_project" --frozen --no-editable --link-mode copy \
    --no-python-downloads --offline
)
```

Choose an actual unique path before running the template; the placeholders are
not deployment defaults. `--offline` reuses only available cached packages;
missing artifacts or a missing compatible local interpreter must stop the
operation. Network/package acquisition must remain within the local executor's approved scope. For
WSL's private-directory contracts, use its Linux filesystem rather than assuming
a Windows-mounted directory has equivalent Unix ownership, inode, or link rules.

A future Windows PowerShell template, **not executed here**, with a separate
Windows project and environment:

```powershell
$researchProject = 'C:\absolute\path\to\reviewed-adapter-project'
$researchEnv = Join-Path 'C:\absolute\path\to\new-environments' ([guid]::NewGuid().ToString())
if (!(Test-Path -LiteralPath (Join-Path $researchProject 'pyproject.toml'))) { throw 'Missing reviewed project' }
if (!(Test-Path -LiteralPath (Join-Path $researchProject 'uv.lock'))) { throw 'Missing reviewed lock' }
if (Test-Path -LiteralPath $researchEnv) { throw 'Environment path already exists' }
$previousProjectEnvironment = $env:UV_PROJECT_ENVIRONMENT
try {
    $env:UV_PROJECT_ENVIRONMENT = $researchEnv
    uv sync --project $researchProject --frozen --no-editable --link-mode copy --no-python-downloads --offline
    if ($LASTEXITCODE -ne 0) { throw 'Isolated synchronization did not complete' }
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment
}
```

Do not use `--active`, `--system`, `--clear`, activation of an existing environment,
or an existing environment path. Do not fall back to a different installer or
modify another project if synchronization fails. Windows and WSL environments
are separate artifacts; neither their environments nor platform-specific wheels
are interchangeable. Native Windows environment preparation does not establish
support for this Linux/POSIX research provider.

**Versioned uv support:** the original regular-interpreter profile still
requires a non-symlink `<venv>/bin/python`. The explicit `UvResearchProcessSpec`
and environment inventory schema2 now support declared bounded interpreter
links, a pinned final FD, complete listed package identities and startup
namespace checks. See [the uv launch contract and target probe](RESEARCH_UV_LAUNCH.md).
This does not globally permit symlinks or establish target compatibility.
uv-created POSIX environments ordinarily use interpreter symlinks; the checked
`uv venv --help` exposes no `--copies` option. `--link-mode copy` controls package
installation and does not solve that interpreter/FD-exec/venv-discovery mismatch.
Virtualenv startup hooks must satisfy the observer’s closed startup-file policy;
schema2 permits only the independently reviewed exact uv startup-file profile.
`--no-editable` alone does not prove that compatibility.
Do not invent `uv venv --copies`, copy an interpreter manually into an existing
environment, or describe the templates above as an accepted execution recipe.
The new guardian preserves logical venv argv0 while executing the verified FD,
then checks actual prefix/import-path layout before entering the research script.
The cloud and target have reported different earlier FD startup results; target
probe evidence and actual authorized acceptance remain necessary. Controlled
tests do not establish that the current target project can execute research.

## Acceptance boundaries

The process limit is the outer wall bound for each original training or evaluator
lease. It is not an aggregate campaign deadline. The source's 300-second training
accumulator skips its first 11 iterations and stops at a complete step boundary;
preparation, compilation, export and evaluation are measured separately. This
adapter does not certify equivalence to the upstream reported score.

Keep original-upstream and adapted-local baseline evidence separate. The fixed
local profile adds SDPA attention, approved microbatch, safe tokenizer/token-byte
exports, tensor-only checkpoint output and an independent evaluator. Those are
explicit scope changes beyond the upstream rule permitting only `train.py` edits.
Candidate mutation is narrower: only the eleven validated hyperparameter
assignments are accepted, and the approved microbatch overrides the corresponding
source value in both generated training scripts. Arbitrary architecture, loader,
evaluator or kernel changes require a separately versioned profile.
