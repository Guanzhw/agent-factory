# Fixed SDPA compatibility diagnostic and baseline handoff

Preserve the original FA3 failure as a separate observation. The designated
target worker reported `no kernel image is available for execution on the device`
on sm120 after5.6 seconds, before tokenizer preparation, training or evaluation.
The SDPA adaptation is a different local baseline, not a repaired upstream score.

The baseline implementation was reviewed at PR37 commit
`6fd3646ff74a2ab8b7c625461a6f5738fef15079`. Its
`platform/agent_factory/research_training_adapter.py` and
`platform/agent_factory/research_torch_runtime.py` are unchanged in PR38
`63c0be99ee4da310492dbbed855bcc4badb6d453`. PR38 passed all ten push/PR CI jobs
and independent double terminal checks; these controlled checks do not establish
target GPU compatibility. Use the exact subsequent probe commit supplied by the
coordinator, never an unpinned branch head or a modified copy.

## Diagnostic scope

`scripts/probe_research_sdpa.py` is a standalone diagnostic for the already
installed, reviewed environment. It calls the actual `SDPAAdapter`, not a copied
attention implementation. It must not call tokenizer creation, source generation,
training, evaluation, `torch.compile`, a kernel loader, an installer or downloader.
The script's synthetic inputs do not consume the downloaded research dataset.

The fixed cases include six head-dimension8 analytic tests (self-only, full
causal, left2, GQA and the1024/1025 inclusive boundary), plus one length4,
head-dimension128 nonzero GQA test with an independent CPU FP32 softmax/gradient
reference. Analytic expectations are rounded to BF16 before the3e-5 comparison;
the nonzero test uses absolute forward tolerance0.005 and Q/K/V gradient
tolerance0.02. Shape metadata appears in each case. This does not test a full
length2048/head-dimension128 training workload or its memory capacity.

Before CUDA checks, the probe requires Torch2.9.1/CUDA12.8 and the actual imported
adapter source SHA256
`cd3c9e3edc1800f495fd0c3e4ed9bdef03b077d918883262e19f1fd192774dde`.
This detects an accidentally stale installed adapter under trusted startup; it
is not a hostile-import sandbox or the Factory interpreter-custody verifier.
The128 MiB observed tensor-allocation threshold is a stopping check after each
small case, not a hard CUDA context/reserved-memory limit. The JSON report retains
`factoryExecutionVerified=false` and `scientificConclusionVerified=false` even
when every compatibility case passes. Exit0 means those fixed cases passed;
exit1 is a diagnostic failure and exit2 rejects unknown CLI arguments.

The adapter accepts BF16 BTHD tensors with equal sequence lengths. Its explicit
Boolean mask includes exactly `0 <= query_position - key_position <= left`,
so `left=0` is self-only and the left edge is inclusive. It transposes to BHTD,
uses zero dropout and `is_causal=False` because the explicit mask already applies
causality, and enables GQA only when query and KV head counts differ. This follows
the [PyTorch2.9 SDPA contract](https://docs.pytorch.org/docs/2.9/generated/torch.nn.functional.scaled_dot_product_attention.html):
Boolean True includes an element and GQA repeats KV heads into query-head groups.
Backend selection remains PyTorch's default; a successful diagnostic does not
identify or prove a particular fused kernel. No FA3 success is implied.

Run only in the existing target worker under its bounded process runner. Use the
existing ordinary uv/venv interpreter path, a60-second wall limit with a5-second
kill grace, bounded stdout/stderr capture, and the already selected GPU. Stop on
timeout, OOM, import failure, nonfinite results or a failed comparison. Do not
retry with larger inputs, change precision, force another backend or install a
source toolchain. Fixed tensor sizes bound the test's arithmetic, but CUDA context
and allocator overhead are not a hard total-memory guarantee.

The probe takes **no CLI arguments**. Select existing, reviewed absolute paths
and the already authorized device below. `factory` is a checkout of the exact
probe commit from the coordinator; `uv` is the existing uv0.11.7 binary, not a
new installation. `scratch` is an existing empty private diagnostic directory
outside the source and dataset. Use the target worker's existing output-limited
supervisor (at most128 KiB stdout and64 KiB stderr) around this command:

```bash
uv='/absolute/existing/uv'
project='/absolute/existing/research-project'
venv='/absolute/existing/research-venv'
factory='/absolute/reviewed/factory-checkout'
scratch='/absolute/existing/empty-private-diagnostic'
gpu='0'
test -x "$uv" && test -x "$venv/bin/python" && test -f "$project/uv.lock" \
  && test -f "$project/pyproject.toml" && test -d "$scratch" \
  && test -f "$factory/scripts/probe_research_sdpa.py" || exit 2
env -i PATH='/usr/bin:/bin' HOME="$scratch" TMPDIR="$scratch" \
  UV_PROJECT_ENVIRONMENT="$venv" PYTHONPATH="$factory/platform" \
  PYTHONNOUSERSITE=1 PYTHONPYCACHEPREFIX="$scratch" \
  HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  CUDA_VISIBLE_DEVICES="$gpu" CUDA_CACHE_PATH="$scratch" \
  TORCHINDUCTOR_CACHE_DIR="$scratch" TRITON_CACHE_DIR="$scratch" \
  OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 \
  timeout --signal=TERM --kill-after=5s 60s \
  "$uv" run --project "$project" --offline --no-sync \
  python -B "$factory/scripts/probe_research_sdpa.py"
```

The clean environment forwards no provider credentials. Do not remove the
offline/no-sync flags or use `-I` here, which would ignore the reviewed
`PYTHONPATH`. Existing normal Python startup may process the target's previously
reviewed startup files; this diagnostic does not retroactively verify startup.
`-B` and the empty cache prefix prevent stale source bytecode from standing in for
the reviewed Factory files. Retain the external runner's original-process cleanup
on timeout/failed output capture. No new local worker is needed.

## Existing minimal baseline API and parameter contract

The source generator is
`research_training_adapter.build_training_bundle(upstream_files, candidate_files,
microbatch=8)`. It parses verified source bytes and returns generated bytes plus
an offline provenance receipt; calling it does not execute the upstream program.
Its generated files are `trusted_architecture.py`, `trusted_data.py`,
`train_baseline.py`, `train_candidate.py` and `evaluate.py`. These names are
generated outputs, not ready-made runnable repository scripts.

The existing admitted launch contract is exactly:

```text
<approved interpreter> -B <absolute program root>/train_baseline.py --config <absolute program root>/run-config.json
```

This describes the existing driver/guardian contract; it is not an alternate
standalone training command. Stage and bind through
`research_local_driver.derive_local_identities(...)` and
`research_local_driver.build_local_driver(...)`, following
[the local adapter contract](RESEARCH_LOCAL_ADAPTER.md). The ordinary uv
compatibility diagnostic does not produce a Factory task receipt or authorize
bypassing that lifecycle for training.

The fixed model has8 layers,4 query/KV heads,512 embedding dimensions and the
`SSSL` window pattern. Sequence length is2048 and seed42. The training budget is
300 seconds; compilation/startup and evaluator time require separate wall budget.
Independent evaluation consumes20,971,520 tokens and reports `val_bpb` from the
fixed evaluator. A smaller smoke run is not this baseline's accepted metric.
The approved microbatch defaults to8, must be a positive divisor of128, and
applies equally to baseline and candidate. Total batch size must be divisible by
`microbatch * 2048`.

Only these eleven assignments can change: `TOTAL_BATCH_SIZE`, `EMBEDDING_LR`,
`UNEMBEDDING_LR`, `MATRIX_LR`, `SCALAR_LR`, `WEIGHT_DECAY`, `ADAM_BETAS`,
`WARMUP_RATIO`, `WARMDOWN_RATIO`, `FINAL_LR_FRAC`, `DEVICE_BATCH_SIZE`. Architecture,
optimizer bodies, data and evaluator code remain fixed. This is bounded parameter
search, not unrestricted architecture search.

The runtime config has exactly `schema`, `comparisonManifest`, `binding`,
`inputRoot`, `inputRootIdentity`, `tokenizer`, `tokenBytes`, `dataset`,
`outputCheckpoint`, `checkpoint`, `evaluationContract`. Training requires
`checkpoint` and `evaluationContract` null; evaluation requires
`outputCheckpoint` null and original training-checkpoint custody. Actual runtime
initialization requires Torch2.9.1/CUDA12.8, tiktoken and pyarrow, verified frozen
parquet shards/split, safe operator tokenizer JSON and an I32 token-bytes tensor.
Use `research_torch_runtime.prepare_tokenizer_export(trusted_encoding)` for the
safe payloads; do not load an upstream pickle or substitute another tokenizer.
The tokenizer's decoded UTF8 byte lengths and all immutable identities must
match. Downloaded files alone are not a completed tokenizer or training setup.

## uv0.11.7 target versus reviewed uv0.12.19 profile

PR38's explicit profile is `uv01219-virtualenv-startup-v1`; its observer requires
`uv=0.12.19` in `pyvenv.cfg` and exact reviewed `_virtualenv.py`/`_virtualenv.pth`
bytes, plus declared package/config/lock/interpreter identities and final prefix
checks. The reported target uv0.11.7 is not accepted by that profile, even if
some startup bytes happen to match. Review the actual target files and version
under a separate explicit profile change. Do not upgrade global uv, edit the cfg
version, relabel the profile or bypass the observer. Ordinary-path SDPA diagnostic
success does not close this Factory-launch gate.
