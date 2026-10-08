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

## Managed attachment is required before session admission

A read/attach connection cannot yet execute a governed native session. Its
capability projection explicitly reports:

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
an approval boolean. No native attached-project session is admitted by this change.

Copying/importing the project into that isolated runtime would change native
identity and requires a separate product choice; this implementation does not do it.

## Native project creation remains unavailable

Pinned upstream [`create_project`](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L1411-L1522)
unconditionally starts `local::starter::warm`, which can make a model call. The
endpoint has no request-budget parameter or warmup suppression flag. It also defaults
GitHub synchronization from local configuration when omitted. A future approved
creation flow must explicitly disable GitHub synchronization unless separately
authorized and account for warmup through bounded shared usage controls. The current
adapter sends no create request, clones no repository and makes no model call.

Sources: pinned upstream [project projection/list](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L1255-L1281),
[project read](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L1524-L1530),
and [session creation/options](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L6667-L6748).
