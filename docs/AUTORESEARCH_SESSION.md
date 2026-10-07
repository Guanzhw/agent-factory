# Goal-driven AutoResearch session integration

This checkpoint adds the default AutoResearch screen and a real OpenResearch
session adapter. It does **not** accept the scientific autonomous application.
An operator-selected candidate, a deterministic workflow model, an HTTP session,
and a model-driven research cycle are different evidence levels.

## Ownership and existing implementation

Agno 3.1 and PostgreSQL retain native task, immutable-plan, material, permission,
cancellation and capacity ownership. Scientific presets first publish an original
Agno external-execution requirement. The paused parent releases the single worker
while its explicitly admitted controller owns the ORX turn; the same native run
continues only after original stop/result custody. The inline diagnostic profile
still delegates one whole turn through `ORXResearchModel.aresponse`. Neither
wrapper runs another research model/tool loop. ORX delegates
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
issued a title-generation request in the historical wire probe. The current
launcher explicitly disables OpenCode's built-in title agent and verifies that
effective setting; no hidden title request receives a separate budget. Interrupt ACK and
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

The durable subordinate path is now implemented in `autoresearch_children.py`,
`autoresearch_scientific_child.py` and `autoresearch_session_control.py`.
Approved same-application modes prepare, train and independently evaluate one
candidate through original DelegationService/native tasks. The first bounded
scientific preset admits one experiment/three children; it does not change the
generic delegation cap. Parent runtime cleanup also checks original child stops.

`scripts/autoresearch_scientific_assembly.py` constructs actual existing
preparation/local research providers in the same control plane. It binds candidate
bytes and derived variant, original prepared input and training checkpoint to the
reviewed parent manifest and operator environment/device/limits. A phase intent
must be committed before a content-addressed target can be registered; existing
targets cannot be overwritten. Result verification rereads original custody.
Completed-child artifact reads use a narrow read-only path; they do not renew
execution permission or bypass cancellation/UNKNOWN.

The operator installs `Settings.autoresearch_children_factory` returning the
concrete `AutoResearchChildren` service with its assembler, preparation store,
checkpoint store and existing evaluation service. Preset callbacks call that
service's `experiment` and `result_verifier`; publication does not create targets,
start a baseline or grant a new environment. Missing service wiring disables the
preset. Actual baseline/config/receipt bindings on the existing GPU target remain
unavailable here, and the target's installed source identities must be checked
before execution. The standalone candidate CLI is not used as a shortcut.

Actual single-worker native pause/process-child/same-parent continuation has been
verified separately with an inert ORX fixture and a trusted scientific-pin seam.
It is not the full three-stage scientific integration or real inference proof.
The complete real model → candidate → target experiment → independent result →
next decision acceptance is still missing; no scientific completion is claimed.

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
Later independent, public read-only diagnostics retained the original failed
ledgers and snapshots. Each stopped after two requests (one settled, one UNKNOWN),
with positive original container exit/reclaim and no experiment. The second
settled 667 input/200 output tokens; the third settled 667/407. The third's safe
origin diagnostic identified a 30-second GET `/api/chat/sessions` transport
timeout during message polling. Session cleanup then denied broker authority
while request two was streaming. This diagnoses that run; it does not rewrite
unknown history or invent missing usage.

The current fix retries only classified GET transport timeouts for the same
original session within its unchanged total deadline. It does not resend a
message, reset a turn, retry a provider call, ignore protocol/authorization errors
or release UNKNOWN reservations. OpenCode title generation is also disabled from
its pinned upstream configuration contract. Updated real-wire/live validation is
recorded separately when obtained.

The new scientific integration code has focused guard tests and independent
review. Native fixture acceptance does not certify real GPU execution or prove
that the target's older baseline matches the current installed code identities.
Those are remaining acceptance requirements, not substituted by callback flags.

## Updated deterministic/runtime evidence

The updated isolated ORX/OpenCode wire probe completed the context tool and final
response with exactly two **synthetic** provider responses; no title request was
forwarded. Effective configuration, original Docker exit and exact container
reclaim were verified. This demonstrates the title-disable configuration on the
actual pinned binary; it is not real Go inference evidence.

The separate native PostgreSQL fixture passed in33.984 seconds: the original
parent paused at queue attempt1/max_attempts1, one delegated bounded process ran
on the single worker, and the same parent continued at attempt2/max_attempts2.
Agno explicitly adds one continuation attempt (`update_job_for_continue`); this
is not a provider retry. There was one controller runtime invocation, one original
continuation command, one child allocation and positive released custody.

Pinned OpenCode title behavior is documented in its
[agent configuration source](https://raw.githubusercontent.com/anomalyco/opencode/v1.18.35/packages/opencode/src/agent/agent.ts)
and [session prompt source](https://raw.githubusercontent.com/anomalyco/opencode/v1.18.35/packages/opencode/src/session/prompt.ts).

## Real Go recovery validation

After the GET-timeout/title fixes, an independent public read-only run completed
through the actual pinned ORX/OpenCode binaries and actual Go `deepseek-flash`.
The persisted transcript contains a completed `factory_research_context` tool
with the original public diagnostic statement, followed by the model's final
reply. All three provider attempts settled:2734/60,2884/145 and3068/83 input/output
tokens. Provider attempts have no UNKNOWN; actual subscription invoice remains
unverified. The rejected decision nevertheless left an UNKNOWN tool effect, so
the overall task is not cleanly completed despite its original completed projection. Original container exit and exact reclaim were confirmed.

The model also attempted `research_decision(stop)` without an independent result.
Factory rejected it under the existing stage guard; the subsequent model reply
finished the diagnostic. The original UNKNOWN tool effect is retained; validation
before reservation and truthful unresolved-effect projection are now implemented.
Original DONE session receipts cannot bypass an unresolved tool during native
continuation. Diagnostic-write failures cannot prevent original cancellation. There was no candidate, experiment, independent result
or accepted scientific next-decision. This is real model/harness/context-tool
compatibility evidence, not scientific autonomous research acceptance. The three
older UNKNOWN attempts and their original private snapshots remain retained.

## Final post-fix public diagnostic

Code checkpoint `a9eb50ab657d9e8e2253fdff1e101e8fa98af1d5` completed an independent
actual ORX/OpenCode/Go diagnostic on 2026-10-07. Task
`4549862e-569b-4b20-825c-e6a71d347162` read the public context and returned a final
reply. Three streaming attempts settled at 2742/46, 2878/123 and 3041/47
input/output tokens (8,877 total). Both original context and session effects are
DONE; provider held tokens are zero. The out-of-stage stop decision was rejected
without reserving an effect. Original Docker exit and exact reclaim were verified.
This verifies the precondition fix in the actual harness. All older UNKNOWN
records remain unchanged. Invoice verification and scientific acceptance remain
unverified; no candidate or experiment ran.
