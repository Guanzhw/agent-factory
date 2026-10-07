# One candidate and original-invocation recovery

This external operator harness follows the accepted baseline in
[baseline acceptance](RESEARCH_BASELINE_ACCEPTANCE.md). It does not modify the
installed scientific runtime, retrain the baseline, resume a training checkpoint,
promote code, or run an optimization campaign. The real candidate/GPU lane still
requires the original local owner and retained private evidence.

## Installation boundary

Use a separate checkout of this PR's exact reviewed commit. Keep the accepted
PR50 site-packages installation and the baseline source, workspace, inputs,
interpreter, device and approved limits unchanged. Do not reinstall the Factory
wheel or set `PYTHONPATH` to this checkout's `platform` during the target run:
installed source inventory is part of comparison identity. The new scripts import
the installed APIs and each other from this checkout's `scripts` directory.

The baseline runner remains unchanged. The baseline compiler PATH correction is
still required; see [its handoff](RESEARCH_TOOLCHAIN_PATH_HANDOFF.md).

## Private configuration

Create one owner-only, mode0600 JSON file under a real private directory. It has
exactly these fields; all file and workspace paths are absolute, without symlinks.
Do not commit the configuration, snapshots, logs, database URL or generated files.

| Field | Required value |
|---|---|
| `schema` | integer `1` |
| `ackCandidate` | boolean `true`, explicit authorization for this single invocation |
| `baselineConfigFile` | Original successful baseline configuration, unchanged |
| `baselineEvaluationReceiptFile` | Original successful `evaluation-receipt.json` |
| `baselineRunConfigFile` | Original **training** `run-config.json` |
| `candidateTrainFile` | Reviewed replacement bytes for upstream `train.py` only |
| `candidateSha256` | SHA256 of those actual replacement bytes |
| `workspace` | Fresh private candidate workspace, different from baseline |
| `requestId` | New 8–40 character identifier using letters, digits, `_ . : -` |
| `totalSeconds` | Locally approved integer shared orchestration deadline, 1–86400 |

Resource limits are read from the retained baseline configuration. They cannot be
increased by candidate config. The shared deadline includes preparation and both
stages; each stage consumes its one attempt durably before effects. At least60s
must remain before preparation publication. Async execution calls use the
remaining deadline; synchronous database and filesystem operations retain their
own bounds, so this is not a hard whole-command termination guarantee.

Keep the entire original baseline workspace: original training and evaluation
runconfigs, source seals, custody journals, environment inventory/interpreter
contract, managed checkpoint and receipts. A retained score JSON is insufficient.
Before any candidate preparation, the harness reconstructs original providers,
rechecks native/policy/material/application custody, rereads the original
checkpoint and independent evaluator output, and requires exact receipt equality.
Existing service metadata/configuration is opened without seeding demo identities
or publishing material. Revoked authority, missing evidence or identity drift
blocks the run.

Only the installed adapter's literal hyperparameter edits are supported. Generated
no-ops, other source changes, evaluator changes and a different comparison
manifest are rejected. A candidate starts from the same initialization protocol;
the retained baseline checkpoint is comparison evidence, not its initial state.

## Commands for the authorized local owner

Run with the same approved research interpreter and environment convention as the
accepted baseline. `CANDIDATE_CONFIG` names the private config above; `SOURCE`
names this exact reviewed source checkout; `RESEARCH_PYTHON` names the accepted
research venv interpreter. These variables contain no database credential.

```bash
PYTHONDONTWRITEBYTECODE=1 "$RESEARCH_PYTHON" \
  "$SOURCE/scripts/run_research_candidate.py" --config "$CANDIDATE_CONFIG"
```

Successful completion saves original training/evaluation receipts and
`assessment.json` privately. Assessment is advisory: lower comparable `val_bpb`
recommends keep, equal/worse recommends rollback; incomplete or mismatched
observations are inconclusive. It never changes Git, installs or deploys anything.
Each evaluator uses the fixed independent evaluator and original candidate
checkpoint custody. Training stdout cannot establish its metric.

An ordinary second invocation against an existing workspace is inspect-only.
For an interrupted invocation, use the explicit stop-only command:

```bash
PYTHONDONTWRITEBYTECODE=1 "$RESEARCH_PYTHON" \
  "$SOURCE/scripts/run_research_candidate.py" --recover --config "$CANDIDATE_CONFIG"
```

Recovery acquires the same exclusive journal lock, reconstructs only its consumed
stages, resolves lost task ACKs by the exact original request, and checks original
task/plan/native/lease/provider identities before stopping anything. It does not
start an app lifespan, poll a global queue, submit, retry, continue a native run,
launch a new process or reset an ACK. A never-started native worker object is
used only for the installed native waiting-run cancellation API. Native and
process release need independent positive evidence. Running native work, a
missing binding, unresolved ACK or mismatched journal stays UNKNOWN; no idle-GPU
or missing-PID inference releases capacity.

Recovery writes a new private `recovery-*.json`; it does not overwrite scientific
receipts. Exit0 requires confirmed process and native closure for every consumed
stage. Exit2 retains uncertainty. A stopped candidate is not a resumed or
successfully evaluated candidate. Repeated recovery may improve cleanup evidence
but can never spend another stage attempt or renew the deadline.

## Validation boundary

Unit tests cover source/variant restrictions, journal durability and repeated
cancellation, strict config, lost ACK lookup after deadline, original provider
fingerprints, retained baseline tampering, and native stop identity checks.
Required PostgreSQL tests use real native queues and stdlib child processes with
explicit synthetic device evidence; they do not execute Torch or a GPU workload.
The top-level execution test injects baseline authentication, preparation,
scientific source/environment adaptation and synthetic target assembly; its
controllers, checkpoint import and independent evaluator custody are real. The
top-level recovery test injects synthetic target reconstruction while exercising
the actual journal, existing-database state, original process stop and native
cancellation. Separate tests verify reconstructed provider fingerprints. These
are orchestration tests, not an unmocked scientific bootstrap or a demonstrated
OS-process crash/restart on the target machine.
The CI runner fails if any required case is skipped. Exact CI outcomes are
recorded on the draft PR after the final commit.

For real local acceptance, retain the original numeric limits and run at most one
explicit reviewed candidate. Record both original closure chains, manifest
equality, candidate source hash, independent evaluator result and advisory
assessment. A separately authorized interruption lane must name its interruption
phase precisely; allocation ACK is not proof of GPU training. Do not kill the
guardian or reboot and assume cooperative custody can recover. Production SSO,
department capacity, scientific-provider connectivity and personal-agent24h
remain outside this acceptance.
