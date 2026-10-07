# karpathy/autoresearch integration milestone

The new [goal-driven ORX session checkpoint](AUTORESEARCH_SESSION.md) separates
autonomous research from the existing controlled baseline/candidate execution.
Real model-driven end-to-end acceptance remains outstanding.

Latest outcome, 2026-10-07: [first real local baseline acceptance](RESEARCH_BASELINE_ACCEPTANCE.md) records completed
local training, checkpoint, independent fixed evaluation and released custody.
The earlier stage's readiness/no-live-execution statements below are historical;
its fixtures do not become live evidence. Production, real candidate comparison
and broader target-host acceptance remain separate.

Status: **contract and host-readiness assessment only**, 2026-10-06. No training, dependency installation, dataset download, GPU allocation, or live Factory training acceptance is established by this document. Factory integration was inspected at `7509e26`; the existing controlled comparison and ORX toy remain separate profiles with unchanged pins.

## Selected upstream and provenance

The selected project is [karpathy/autoresearch at 228791fb499afffb54b46200aca536f79142f117](https://github.com/karpathy/autoresearch/tree/228791fb499afffb54b46200aca536f79142f117). It is not modded-nanogpt, a multi-H100 speedrun, or a Windows/TinyStories fork. Its score is validation bits per byte (`val_bpb`, lower is better), not another project's loss threshold.

The coordinator downloaded public source files into `/workspace/scratch/autoresearch-20261006`; this audit read those files statically and did not execute or import them. The pinned README says “MIT”, but the coordinator's raw `LICENSE` request returned 404. **The complete applicable license/copyright notice remains unresolved before vendoring or execution.** README attribution alone must not be presented as a verified complete notice. Dataset and kernel provenance/licensing require separate records.

SHA-256 of the inspected source bytes:

| File | SHA-256 |
| --- | --- |
| README.md | `3958fd4195ac2f98ed35c4eaa4f3028a335165ee24945e96426c408d25793a41` |
| prepare.py | `4f2ba9cbb8ba8c4a3d35be405a913e2f3be3af9aea103ed52ef7b2a662058150` |
| train.py | `2954175f4ac42ad65164aef40910ef953789abcd05a5cc886ac9ba5a00814414` |
| program.md | `86cf987a5c381e46eefe0d0a82765223fd766d8d7acdc2afacfbbce15ecacece` |
| pyproject.toml | `675c150a9e0769f0e39a43eb7d836934266fa348d6e2403521f1ff99f9b9f1af` |
| uv.lock | `03174c5cce6387418c5b6cc9bbe8f71ad0ae1e1d6fedeaecae5cdcf7321da0a3` |

These hashes identify the downloaded bytes, not a completed dependency/data supply-chain validation. Raw source URLs have the form `https://raw.githubusercontent.com/karpathy/autoresearch/228791fb499afffb54b46200aca536f79142f117/<file>`.

## Experiment contract

- Freeze `prepare.py`, its evaluation implementation, tokenizer/data artifacts, `pyproject.toml`, and `uv.lock`. The permitted candidate source change is `train.py`; `program.md` remains human-controlled instructions, not authority to disable Factory permissions or run indefinitely.
- `prepare.py:30` fixes sequence length 2048, training budget 300 seconds, and evaluation budget `40 * 524288` tokens. `prepare.py:344` defines the byte-normalized evaluation. Keep these unchanged for this selected comparison contract.
- Upstream `train.py:450` defaults to device batch size 128. A reviewed local microbatch adaptation in `train.py` may establish a runnable RTX 5070 baseline. Preserve the original bytes and exact adaptation diff; then freeze that local baseline before candidate comparison. A changed dataset, tokenizer, sequence length, or evaluation budget creates a different protocol and cannot silently replace this one.
- The 300 seconds cover the source's accumulated training-step timing, **not total job time**. The implementation excludes initial steps from that accumulator, stops at a step boundary, and evaluates afterward (`train.py:578`, `:603`, `:613`). Measure preparation, startup/compilation, warmup, training, evaluation, and total wall time separately. The outer lease deadline needs a separately approved bound; setting it to 300 seconds would truncate valid work.
- Compare baseline and candidate on the same device, frozen data/tokenizer/evaluator, environment, and timing protocol. Record seed and actual hardware/software identity. A local result is not an H100-comparable ranking.
- `train.py` uses an H100-specific FLOPS denominator for its MFU output. Preserve raw output as provenance if collected, but do not display that number as measured RTX 5070 utilization or validated H100 performance.
- Candidate-written stdout is insufficient scientific proof. A trusted independent evaluation path must verify the trained artifact, frozen evaluator/data, finite score, and execution identity. The evaluator must not gain its authority from editable `train.py`; an unchanged file hash alone does not prevent candidate code from bypassing or altering evaluation at runtime. Checkpoint/export and trusted loading contracts remain to be implemented.

## Reported host readiness

The following are coordinator-reported local observations, not measurements performed by this document's author. Availability is transient and must be rechecked before admission.

| Item | Reported observation | Interpretation |
| --- | --- | --- |
| GPU | RTX 5070, SM 120; 12227 MiB total, approximately 10440 MiB free | Single-GPU candidate host; no successful torch/kernel/training probe yet |
| Host | Windows 11, i5-14600KF, 32 GiB RAM, approximately 10.4 GiB free | Host RAM headroom is limited; not the deployment capacity target |
| NVIDIA stack | Driver 616.64, reported CUDA UMD 13.4; nvcc 13/13.1 | Does not establish PyTorch CUDA-wheel, Triton, or Flash Attention compatibility |
| Python | Windows Python 3.11–3.14; torch/triton/flash_attn not installed | Training environment is not ready |
| WSL | Stopped; inspection pending | Do not assume a working Linux CUDA environment or delegated cgroup support |
| Storage | C: approximately 11.5 GiB free; D: approximately 9.95 GiB free; VHD approximately 187 GiB on D: | VHD size is not free space; data, wheels, compile caches and checkpoints need a measured space budget |

Upstream pins torch 2.9.1 through the cu128 index. `train.py:21` selects a downloadable kernel through `kernels.get_kernel`; non-Hopper devices use `kernels-community/flash-attn3`. The source also uses `torch.compile`. Neither installed nvcc versions nor NVIDIA driver visibility proves that this exact combination supports SM 120 on the selected OS. Resolve the execution environment and exact kernel revision/cache provenance before a compatibility probe. No dependency installation, additional download, security change or deployment is authorized by this assessment itself.

## Reuse and remaining code

| Boundary | Existing reusable implementation | Remaining integration |
| --- | --- | --- |
| Native remote attachment | `resources.py:65`, `:272`; `remote_handoff.py:161` validates immutable manifests and approved material versions | Use an already authorized receiver and owner mapping; attachment does not require a machine provisioner. Target readiness is still unverified. A2A attachment remains non-dispatching. |
| Original effect custody | `process_provider.py:102`, `:160`, `:208`; `process_runtime.py:219` bind task/plan/native run/request/lease and retain UNKNOWN without replay | Preserve these invariants for long training, cancellation, restart and lost ACK. Do not turn a poll timeout into a new training run. |
| Capacity | `resources.py:36`, `:379`; `process_provider.py:111` account CPU/memory/disk/time | No GPU device/VRAM/ownership admission contract exists. Add explicit device identity and concurrency policy, distinguishing accounting from actual enforcement. CPU cgroups do not enforce GPU quotas. |
| Runtime limits | `process_enforcement.py:35` limits CPU to 2 seconds, AS to 128 MiB, files to 64 KiB and wall time to 5 seconds; `process_runtime.py:250` observes for 7 seconds; `main.py:230` sets native queue timeout to 60 seconds | Implement a separately governed training runtime/limits contract and long-running observation. Do not globally relax the existing bounded fixture. |
| Host enforcement | `delegated_cgroup_fs.py:21`, `:72` support CPU, memory/swap and pids controls | Verify available target enforcement without adding privileges/security settings. GPU isolation, VRAM limits and aggregate disk quota are not supplied by this backend. |
| Experiment pins | `comparison_fixture.py:93`, `comparison_workflow.py:33` demonstrate fixed input/evaluator/change manifests and exact spec validation | Add a distinct real autoresearch profile for source, adapted baseline, data shards, tokenizer, environment/kernel and evaluation pins. Current synthetic score validation cannot validate autoresearch. |
| Artifact custody | `store.py:448` bounds writes; `remote_handoff.py:1263` verifies remote artifact hashes/length; storage governance retains manifests | Define bounded checkpoint, log and metric manifests and verified independent evaluation; do not fit arbitrary training checkpoints into the toy output allowance. |

## Milestones and acceptance gates

1. **Current: contract-only milestone.** Implemented `research_profile.py` pins and verifies supplied upstream bytes; `research_candidate.py` binds actual bounded file bytes and permits only `train.py` changes; `research_assessment.py` gives advisory keep/rollback recommendations from strict observations. All receipts explicitly leave execution and scientific verification false. Observation comparison identity is an opaque caller assertion: the future trusted runtime must derive and verify it from complete device/data/tokenizer/evaluator/kernel/timing identities before acting. No runtime registration, accepted-candidate pointer mutation or git rollback exists in this phase. Selected repository/revision, static hashes, upstream protocol, local baseline policy and reported readiness are documented. License notice, WSL/OS suitability, kernel support, capacity and native training remain unresolved. This is not live/code-complete integration.
2. **Readiness and immutable inputs.** Resolve notices; inspect the selected existing host; establish approved disk/RAM/GPU and total-time budgets; pin environment/kernel and data/tokenizer provenance. Installation, data preparation and execution require the applicable authorization and must not be inferred from this document.
3. **Offline implementation and failure acceptance.** Add the distinct training contract, GPU admission, immutable baseline/candidate manifests and trusted evaluation interface. Test cross-owner denial, drift, lost ACK, cancellation, restart, UNKNOWN retention and positive stop proof with controlled fixtures. Reuse native Agno/Factory lifecycle and existing transport rather than adding another scheduler.
4. **Bounded local baseline.** After readiness and authorization, validate the exact device/environment, then run one reviewed microbatch-adapted baseline. Record separate timings and resource peaks; freeze its code and all non-candidate inputs. A failed/OOM/timed-out run remains failure or inconclusive, never score zero/success.
5. **Native baseline/candidate acceptance.** Run under reviewed immutable plans and original GPU lease identities; independently evaluate both on identical frozen inputs; retain artifacts and validated score provenance. Prove cancellation/stop/reclaim and restart recovery on the real target before calling GPU integration complete. No autonomous overnight loop or additional paid resource is implied.

The existing remote process tests (`test_remote_process_runtime_postgres.py`) provide lifecycle regression patterns, not GPU validation. No model subscription usage, credential creation, paid compute, deployment, dependency installation, training or changes to ORX pins were performed for this documentation milestone.
