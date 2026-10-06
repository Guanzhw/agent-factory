# Fixed eager-model memory preflight

`probe_research_model_memory.py` is an operator-authorized local diagnostic, not a
Factory training task. It reuses the unchanged source generator and SDPA runtime
from base `87f7227fae1d4a39ba85db6f68d96061f9f4de3a`. It does not install anything,
fetch a dataset, create task IDs, produce a checkpoint, or attest a scientific
result. The cloud validation for this deliverable uses only mocks and inert files;
no Torch, generated architecture, or GPU execution was performed there.

## Run in the already approved isolated uv project

Use the existing operator-selected WSL/Linux uv project and lockfile, without
changing that environment. The script uses POSIX no-follow file descriptors and
process groups; native Windows execution returns `SUPERVISOR_UNAVAILABLE`.

```sh
env -i HOME=/absolute/private-scratch TMPDIR=/absolute/private-scratch \
  PATH=/usr/bin:/bin UV_CACHE_DIR=/absolute/approved-existing-uv-cache \
  UV_PROJECT_ENVIRONMENT=/absolute/isolated-research-project/.venv \
  PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPYCACHEPREFIX=/absolute/private-scratch/pycache \
  CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /absolute/existing-uv run --project /absolute/isolated-research-project \
  --offline --no-sync python \
  /absolute/agent-factory/scripts/probe_research_model_memory.py \
  --source-root /absolute/pinned-autoresearch-source
```

Use actual already-approved absolute paths and an existing private mode-0700
scratch directory. The `env -i` boundary protects the initial uv/Python startup as
well as the child; the child alone cannot sanitize its parent startup. No global
uv upgrade or environment synchronization is part of this command.

The only public argument is `--source-root`. That directory must already contain
the six exact public upstream files `README.md`, `prepare.py`, `train.py`,
`program.md`, `pyproject.toml`, and `uv.lock`, pinned by `research_profile.py` to
upstream commit `228791fb499afffb54b46200aca536f79142f117`. The reader does not
follow source-file or parent-directory symlinks, accepts only bounded regular
single-link files, and verifies the captured bytes. Other files in the directory
are not read. No credential or arbitrary source-entry arguments are accepted.
The selected environment must already provide Torch 2.9.1 built for CUDA 12.8.
If supplied, `CUDA_VISIBLE_DEVICES` selects visibility; the child uses logical
`cuda:0`. This is not device isolation or a GPU reservation.

The supervisor starts exactly one fresh child using the current interpreter,
isolated Python startup, and a small explicit environment. It bounds wall time
at 120 seconds, then kills only its original process group and waits up to five
seconds. GPU driver/kernel stalls can outlast userspace termination; a timeout is
not a positive release proof. Output is one bounded JSON record, with no paths,
model output, token sequences, arbitrary exception text, or inherited secrets.
Temporary compiler/cache locations are task-private. On every exit, including
Ctrl-C/SystemExit, the supervisor attempts original-child termination before cache
cleanup and preserves the interruption. If the five-second wait cannot confirm
exit, the private cache is retained for operator cleanup after actual termination;
neither stopped state nor cleanup is claimed.
The probe invokes no compiler or dependency-install command itself. Child
`OMP_NUM_THREADS=2` and `MKL_NUM_THREADS=2` limit cooperating library thread pools;
they are not a hard CPU quota.

## Exact computation

The probe verifies the fixed Factory source closure before loading captured source
bytes, avoiding stale Factory `.pyc` files. It calls
`build_training_bundle(upstream, upstream, microbatch=1)` and executes only the
returned, hash-matched `trusted_architecture.py`; it never runs the generated
training, data, or evaluation entrypoint. The upstream source is parsed and
hashed, never imported as an arbitrary module. Existing notices and licenses in
`THIRD_PARTY_NOTICES.md` remain applicable.

The model is the fixed local-adapted baseline: sequence length 2048, vocabulary
8192, eight layers, four query and KV heads, embedding dimension 512, `SSSL`
windows, original logits softcap 15, and seed 42. Construction mirrors the
training entrypoint: meta-device construction, CUDA `to_empty`, then the original
`init_weights`. With BF16 autocast, one synthetic batch of size one performs one
forward loss and one backward pass. The probe checks finite loss and every
parameter gradient, synchronizes CUDA, and records allocator allocated/reserved
bytes and their peaks. More than 8 GiB observed allocator usage fails the probe;
this is an observed threshold, not an enforced bound on total GPU memory.

The exact generated architecture includes `torch.compile` decorators on optimizer
functions. Import registers those wrappers, but the probe never invokes those
functions, `optimizer.step`, or `torch.compile(model)`. It neither rewrites the
adapter nor monkeypatches compilation or validation. A future Torch behavior
change that makes these imports fail is a diagnostic failure, not a reason to
skip the gate.

## Interpretation and remaining training gates

A passing record establishes only that this single eager synthetic model/gradient
computation completed within this diagnostic's limits. It always reports
`factoryExecutionVerified: false`, `scientificConclusionVerified: false`, and
`compiledTrainingFitVerified: false`. It has no optimizer-state, compiled graph,
real-data consumption, tokenizer, checkpoint, evaluator, or task-custody proof.

Available GPU and disk capacity alone do not establish full training fit: allocator reports omit some CUDA/context memory, while
Inductor/Triton/compiler caches and checkpoint files need separate capacity.
There is no automatic retry, batch-size search, compilation fallback, or alternate
baseline launcher. An OOM, timeout, nonfinite value, unsupported version, or source
mismatch is a bounded failure code.

The actual baseline still requires the original managed task/plan/lease bindings,
reviewed environment startup and interpreter identity, real governed data and
safe tokenizer/token-byte artifacts, and a separately approved total wall/disk
budget. Its 300-second training counter excludes the first 11 warmup steps;
with microbatch one and the unchanged 524288-token total batch, each optimizer
step accumulates 256 microbatches. This diagnostic cannot approve or shortcut that
workflow.
