# Goal-driven AutoResearch session integration

This checkpoint adds the default AutoResearch screen and a real OpenResearch
session adapter. It does **not** accept the scientific autonomous application.
An operator-selected candidate, a deterministic workflow model, an HTTP session,
and a model-driven research cycle are different evidence levels.

## Ownership and existing implementation

Agno 3.1 and PostgreSQL retain native task, immutable-plan, material, permission,
cancellation and capacity ownership. `ORXResearchModel.aresponse` delegates one
whole research turn to ORX; it does not run another model/tool loop. ORX delegates
research reasoning to its actual OpenCode harness. Every provider request crosses
the Factory broker and the original task's usage ledger exactly once. The outer
Agno model wrapper has no provider invocation or additional usage charge.

The pinned ORX revision is `f336b121525d99364e2dee4fe90b2784894a54e6` (0.2.13).
The reviewed OpenCode release is 1.18.35, Linux x64 baseline; archive SHA-256 is
`90c97d4a24d36437bce36f27195c9cd2e0b70ed037a04d1c6a6740eb246c2a73`.
The launcher requires exact operator image/binary pins. It runs with no external
network, no published ports, a read-only root, 1 CPU/1 GiB/64-PID limits and
fresh private HOME/XDG/ORX state. Unix sockets connect only the host broker/MCP
and the private ORX API. Each actual OpenCode child verifies its effective config
before serving; built-in shell/edit/network tools are denied. Five Factory tools
expose approved context, candidate validation, managed experiment, original result
and subsequent research decision. This is not general shell or coding access.

Stock ORX project creation warms a model. The launcher instead initializes a
fresh, schema-checked native store and inserts its single explicit project before
starting ORX. It never rewrites an existing store. Session creation has no upstream
idempotency key: lost acknowledgements remain UNKNOWN. A persisted title update
precedes the first message to avoid ORX auto-title inference. The actual harness
still issued a title-generation request in the wire probe; that request crosses
the same broker and consumes the same task budget. Interrupt ACK and
`busy=false` are not stop proofs. Cleanup requires the original Docker exit proof;
unresolved effects continue holding task capacity.

## Goal-only entry and operator setup

The existing Chinese frontend opens AutoResearch by default. The user selects a
published project preset and either starts its default goal or enters one goal.
They do not supply training commands, model credentials, candidate files, resource
identities or evaluator paths. The material composer remains separately available.

An operator builds a `ResearchPreset` using
`scripts/autoresearch_scientific_preset.py`. It reads the pinned upstream source
and an authoritative accepted baseline. Existing source verification and the
eleven-literal candidate validator remain in force. The upstream indefinite,
arbitrary-code loop is narrowed to finite approved experiments and a fixed
architecture/evaluator; these constraints belong in the preset instructions.

`scripts/bootstrap_autoresearch.py` provides explicit settings and a separate
`publish_application(state, preset, author=..., reviewer=...)` operation through
existing material/application governance. Publication is never automatic on
startup. Register the returned exact application reference in the preset. The
trusted `build_settings()` function in an operator Python module can then return
those settings, including the configured runtime factory and current billing
authorization callback. The real Go key stays only in the host credential
callback; only an ephemeral local capability enters OpenCode.

```sh
PYTHONPATH=platform:scripts:/private/operator-config \
  .venv/bin/python scripts/serve_autoresearch.py --operator-module research_operator --check
PYTHONPATH=platform:scripts:/private/operator-config \
  .venv/bin/python scripts/serve_autoresearch.py --operator-module research_operator
```

The module and private target evidence are operator prerequisites, not supplied
scientific evidence. `--check` performs no database or model calls and reports
readiness/blockers. The server binds only 127.0.0.1. Build the existing frontend
with `npm run build`; then use the configured Factory login and AutoResearch tab.
The API also accepts `{presetId, requestId}` for a default goal or adds `goal` for
a custom goal at `POST /api/factory/autoresearch/runs`. Recover the original request
using the read-only `/requests/{requestId}` route under that same prefix.

The provider route is fixed to Go ChatCompletions and `deepseek-flash`, honest
Factory User-Agent, stable `x-opencode-session`, no retries or paid fallback.
Responses parsing is not reused for ChatCompletions. Initial probes remain at
most three short requests; subsequent operator task budgets are explicit and
bounded (maximum sixteen). Nominal ledger amounts are admission counters, not
invoices or proof of subscription billing. A current subscription-only callback
must pass before credentials/network; a zero balance alone is insufficient.
Unknown auth/quota/usage stops the broker. No new authorization is needed for the
already authorized Go project scope, but missing billing evidence is not invented.

## Outstanding integration and acceptance

The scientific preset is unavailable until a **durable subordinate executor**
binds training/evaluation to the original research task, shares budgets, checks
current parent authority before every dispatch, preserves original native
approval/lease identities and propagates cancellation. The current standalone
candidate CLI does not implement this parent relationship and is not called as a
shortcut. Its preparation/training/evaluation fixtures remain infrastructure.

The paired result verifier must reread original task/plan/lease/checkpoint and
independent evaluator custody. Callback booleans or candidate stdout cannot prove
scientific acceptance. Actual baseline/config/receipt bindings on the existing
GPU target have not been transferred to this cloud checkout. Do not replace the
installed target runtime or rerun its accepted baseline to fill those gaps.

| Evidence | What it proves | What it does not prove |
|---|---|---|
| HTTP mock/unit tests | Guards, parsers, original identities, ledger/cancel behavior | Live ORX/provider compatibility |
| Actual pinned ORX zero-model session | Real create/read/title/message contracts as exercised | Model execution or research |
| Actual isolated OpenCode effective-config/health | Runtime isolation and tool/provider configuration | A model-generated candidate |
| Synthetic provider wire probe | Actual ORX/OpenCode/MCP context call and completed persisted tool result; three synthetic model responses including a title request; original stop and container reclaim | Live model reasoning or scientific results |
| PostgreSQL native fixture tests | Goal admission, native whole-turn delegation, owner recovery/cancel | Autonomous research or GPU execution |
| Required final research acceptance | Real model → instructions → agent hypothesis/action → managed experiment → independent result → next decision | Not yet obtained |

`scientificConclusionVerified` remains false. Execution completion and the six
observed lifecycle markers are separate; neither automatically certifies a
scientific conclusion. Exact-head CI receipts belong to the draft PR. No merge
or deployment is included.

## 2026-10-07 observed validation

Five required PostgreSQL/native cases passed with zero skips (47.283 seconds),
including exactly two settled provider attempts for two mock HTTP responses,
then an UNKNOWN attempt and no fourth dispatch. The actual pinned ORX/OpenCode
wire probe completed MCP negotiation, five-tool discovery, a `research_context`
call and a persisted successful tool result using three synthetic responses.
The first of those was harness title generation. Original exit/reclaim receipts
were verified; the fixture is not live reasoning evidence.

One real Go diagnostic was then run, with at most three requests and no
scientific experiment authorization. It stopped after two provider attempts:
first SETTLED (667 input, 115 output tokens), second UNKNOWN. No real context
read or research decision was observed, and no third request or retry was made.
The task failed with positive original container stop/reclaim; 33,280 reserved
tokens remain held for the unknown attempt. The first response only proves a
model response, not a working research agent. The original private PostgreSQL
snapshot and ORX session store are retained. The broker did not retain sufficient
phase evidence to identify the second failure, so its cause is not inferred.
Safe finite-phase diagnostics are now retained for later runs without rewriting
that history; no additional live request was used to validate the change.

Scientific parent/child integration still requires real code: approved same-app
phase modes and material closure, a delegated scientific profile preserving
ancestor guards, original-request stage coordination, a native durable pause
that frees the single worker while children run, and complete budget/cancel/
checkpoint/evaluator binding. Missing target configuration is an additional
prerequisite, not a substitute explanation for this implementation gap.
