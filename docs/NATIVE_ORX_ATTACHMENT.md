# Native OpenResearch attachment boundary

The `openresearch-workspace-v1` adapter reads real upstream projects at pinned
revision `f336b121525d99364e2dee4fe90b2784894a54e6`. It returns the original native
project ID and an identity hash of the upstream revision, ID and pinned repository
path. That hash does **not** attest repository contents. Owner-exclusive instance
isolation and canonical project paths must be installed by trusted operator code;
users cannot assert either through connection metadata.

Implemented: bounded native project list/read, owner-scoped attach, exact project
identity refresh, and validated inert session-profile options. Controlled wire tests
cover these contracts. They do not prove a live provider or end-to-end model run.

The ordinary research screen offers first-project setup beside the goal, retains
the draft, and distinguishes loading, failed project reads, and a verified empty
list. Setup selects only a current owner-verified creation connection. The
connection list is re-read when setup opens, a newly bound service is selected,
or the research page is refreshed, retaining the goal and checking owner identity.
The owner must supply the remote folder, tool and complete model name; no local path, model,
clone source or extra permission is inferred. Factory BYOK remains separate from
the upstream service's model settings. Binding verifies the project, not model
availability. These desktop changes preserve the existing creation preview,
approval and durable unknown-request recovery.

Empty-service setup remains incomplete: the pinned upstream `CreateProjectReq`
has no per-request model selection or option to disable starter warmup. Project
creation can use the service's preferred or first ready harness for suggestions.
The adapter does not expose an available-model catalog on creation bindings.
Therefore setup must retain explicit creation approval and service-confirmed
model input; it cannot promise automatic two-action initialization or live model
compatibility. See the pinned [creation implementation](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L1411-L1522)
and [starter model selection](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/local/starter.rs#L226-L262).

Page synchronization is labeled separately from research state. Unknown requests
take priority over earlier replies and active pointers. A tool-only record or
unfinished message is not presented as a completed readable reply; an observed
reply still does not certify scientific validity.

## Execution mode determines the admission requirements

The original `openresearch-workspace-v1` read/attach connection alone does not
execute sessions. Ordinary personal execution now uses the separate
`openresearch-personal-session-v1` adapter and actual upstream project/session
APIs; see [ordinary native OpenResearch](PERSONAL_OPENRESEARCH.md). It preserves
native identity, leaves model credentials/billing upstream, reports advisory
usage and sends best-effort interrupts. Its controlled multi-turn, renewal and
recovery tests do not establish hard budgets, process-stop proof or live
compatibility.

For shared Factory credentials/budgets and managed execution, read/attach alone
still cannot authorize a research session. The original gap projection identifies:

- `NATIVE_PROJECT_APPROVED_PLAN_BINDING_REQUIRED`: an immutable reviewed Factory
  plan must bind this exact native project identity, original connection revision,
  session profile, permissions and shared budget. An unrelated controlled workload
  preset cannot stand in for this binding.
- `NATIVE_SESSION_BROKER_ACCOUNTING_REQUIRED`: all model requests, including
  multiple requests within one upstream user turn, must pass through the existing
  `ORXResearchBroker` and shared usage ledger. A harness/model name, `contextUsage`,
  one-message limit or owner-exclusive server is not billing enforcement.
- `NATIVE_SESSION_ORIGINAL_CUSTODY_REQUIRED`: the original task must have scoped
  process custody and a stop-only cleanup path after ordinary permission revocation.
  Release requires positive process-stop proof. Upstream `busy=false` and interrupt
  acknowledgement cannot prove that tools or descendant processes stopped.

The existing `AutoResearchRuntime` satisfies these constraints for its separate
sealed, task-owned runtime: it launches an isolated container with an ephemeral
broker capability, reserves/settles actual provider requests, and checks original
container exit before reclamation. It creates a fresh isolated project/store; it
does not attach an existing owner server. Reusing its controller therefore requires
a real managed-attachment enforcement contract, not a new shadow inference loop or
an approval boolean. The implemented [managed connection probe](managed-openresearch-probe.md)
now admits one text-only provider request with native tools disabled. It does not
implement managed multi-step research.

The minimum remaining managed implementation is to connect the existing governed
ORX MCP tools to the attached native harness, reserve/settle every provider request
through the same broker/ledger, and retain tool receipts plus original-session and
process custody through cancellation/restart. It depends on an independently
installed supervisor that can prove broker-only egress and control the original
tool/descendant process scope. Raising the probe's request limit is insufficient.

Copying/importing the project into that isolated runtime would change native
identity and requires a separate product choice; this implementation does not do it.

## Native project creation remains unavailable

Pinned upstream [`create_project`](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L1411-L1522)
unconditionally starts `local::starter::warm`, which can make a model call. The
endpoint has no request-budget parameter or warmup suppression flag. It also defaults
GitHub synchronization from local configuration when omitted. A future approved
creation flow must explicitly disable GitHub synchronization unless separately
authorized and account for warmup through bounded shared usage controls where
hard enforcement is promised. The minimum remaining application flow needs explicit
path/repository/paper inputs, disclosure and approval of model warmup and repository
writes, durable create intent and read-only reconciliation of unknown acknowledgments.
Upstream support must either suppress warmup or enforce its approved budget for
managed creation; an ordinary remote-funded alternative would need explicit
advisory-cost consent. `githubSync=false` must be verified as honored before offering
a no-publication create path. These are unimplemented capabilities, not merely
missing endpoint configuration. The current
adapter sends no create request, clones no repository and makes no model call.

Sources: pinned upstream [project projection/list](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L1255-L1281),
[project read](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L1524-L1530),
and [session creation/options](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L6667-L6748).
