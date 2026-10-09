# Ordinary native OpenResearch project creation

This implementation connects **preview → per-request owner consent → existing
Factory plan review/native Agno task → native project ID → native session →
approved research message → observed result**. It does not install a runtime,
add a research scheduler or change managed budgets. Live external acceptance is
still unverified; controlled fixtures are not proof of a live model/tool loop.

## Explicit authority and setup

Use the existing `openresearch-personal-session-v1` provider, owner-bound service
credential and HTTPS network guard. Add a separate remote configuration with
`projectCreation: true` and no `projectId`. Its read-only verification accepts an
empty native project list and grants only `runtime:health`, `project:read` and
`project:create`. Verification/connection binding does not create a project or
invoke a model. Existing project-bound connections retain their prior session
capabilities and reject project POSTs; they are not silently upgraded.

The trusted installer must independently publish the separate immutable
`personal-orx-project-create-v1` application, using
`publish_application(state, author=..., reviewer=..., project_creation=True)`.
The ordinary command application and its prior definitions remain separate.
Both reuse the installed deterministic command controller/tool, native queue,
existing temporary-plan review policy and persisted effect records. No provider,
vault or shared definition is installed or published by an HTTP user request.

In the resource form, explicitly enable **用于创建新项目**, choose service Bearer
or Basic-proxy authentication, save the destination-bound service credential,
then verify and bind. The OpenResearch ordinary workspace shows this creation
connection separately from project/session connections.

## Source and exact side effects

Inputs are a name, absolute **remote** path and one source:

| Source | Request effects disclosed before consent |
|---|---|
| Empty | Require a new remote folder, initialize Git, register the project |
| Existing path | Register the chosen existing remote folder; it is not cloned or implicitly initialized |
| Public repository | Clone the exact public HTTPS GitHub URL into a required new remote folder, register the project |
| Paper | Fetch the explicitly identified arXiv paper/PDF, seed a required new folder, initialize Git, register the project |

The minimal interface does not accept run commands, arbitrary shell options,
authentication in clone URLs, implicit repository publication or runtime setup.
The actual inputs, exact connection pin and versioned disclosure are hashed into
the immutable plan. Preparation performs local admission/connection checks;
it does not send project inputs to the remote service.

For an existing directory, upstream resolves the canonical path/enclosing Git
repository root. A subtree or symlink is not a filesystem sandbox. The preview
states this; the input should be the intended repository root whose context the
owner authorizes the remote model to read. The acknowledged native path is kept
separately from the requested path rather than claiming an unverified path pin.

Pinned source is
[`CreateProjectReq`/`create_project`](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L1392-L1522).
The Rust member is `github_sync_enabled`, while `#[serde(rename_all = "camelCase")]`
makes the recognized HTTP field **`githubSyncEnabled`**. The adapter explicitly
sends both `github_sync_enabled: false` and `githubSyncEnabled: false` and never
sends `githubSync`. Sending snake_case alone would leave the wire override unset
and could inherit the upstream sync default. The recognized false value skips
the create handler's automatic `push_project_for_sync` branch. This is a request
contract, not proof that arbitrary existing remote configuration or future
user-approved tools cannot publish anything.

The handler starts
[`starter::warm`](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/local/starter.rs#L269-L277)
in the background. It may generate four chat suggestions, using the remote
preferred/ready harness and model. This is not model-weight warming and does not
automatically run experiments. Empty context, a cache hit or no usable harness
can avoid a model request. When generation runs, README, selected code, file
inventory and/or paper summary may be sent to that model, with possible charges
to the owner's remote account. The preview discloses these effects without
requiring ordinary personal mode to enforce a managed hard budget or patch the
upstream warm function.

## Consent, dispatch and cancellation

Administrative plan approval is necessary when configured, and does not replace
the owner's explicit consent to this create request. The server stores a separate
owner/request/plan/preview-hash consent. Recovered previews reset UI consent;
they never submit automatically. The native tool rechecks current permission,
exact plan/run identity, original credential/connection revision and consent
after blocking address/credential IO, immediately before POST.

Consent moves from `awaiting` to `approved` or `cancelled`. Cancelled consent is
terminal. The last pre-send callback atomically claims `dispatch_started` only
from `approved`. A cancellation winning that comparison prevents POST; a later
cancellation cannot claim it undoes a project, clone, paper download or possible
starter model request. A generic Factory instance endpoint cannot bypass the
tool's consent check. It may create a local UNKNOWN task, but cannot dispatch a
cancelled/unapproved remote create.

A crash between immutable plan admission and consent-row creation recovers an
awaiting preview directly from the original plan, with no write on GET. Only an
explicit owner decision materializes that consent row; it cannot become approved
or dispatch merely because recovery found a plan.

Concurrent preparation/start calls use the original owner/request ID and native
task. Independently committed command reservations prevent a second POST. The
adapter sends no invented upstream idempotency key: the pinned create API has no
such contract.

## Lost responses and continuation

A lost POST response, failed acknowledgement persistence or crash after effect
reservation retains the original UNKNOWN operation. Native retry/restart only
reads it. Read-only reconciliation lists newly appearing project IDs relative to
the persisted pre-submit snapshot; these are **unproven candidates**, not exact
correlation. Name/path resemblance, a single candidate and remote idleness do not
settle the original task. No candidate button silently adopts an ID, changes the
original plan, or creates another project. Resolve an ambiguous creation at the
remote service; a separately explicit existing-project attachment remains an
independent action and does not retroactively prove the original request.

An acknowledged native create response supplies the original project ID. The
owner then selects an explicit harness/model and confirms **关联新项目并进入原生会话**.
This creates a separate project-scoped local configuration with the original
opaque credential references, verifies that project read-only and binds its
session capabilities. It never silently retargets the creation pin or an older
session. Connection revision/expiry remains mandatory. The new connection has
no `project:create` capability. Its explicit `sessionDefaults` allow creating
the first native session without a pre-existing template; the remote default
permission mode is retained. Existing native sessions can also be selected.
Each session-create/message remains a separately prepared/reviewed/confirmed
ordinary command. Native transcripts and result observations reuse the existing
session adapter, including its inferred correlation/advisory usage boundaries.

## Additive API

Routes are authenticated under `/api/factory/personal-agent`:

| Method/path | Meaning |
|---|---|
| POST `/project-commands/prepare` | Exact `requestId`, `connectionRef`, `project`; local immutable preview/plan |
| POST `/project-commands/{requestId}/decision` | Exact `previewHash`, strict `approved` boolean; owner consent or cancellation only |
| POST `/commands/start` | Existing native Factory admission; checks owner consent for creation plans |
| GET `/commands/requests/{requestId}` | Original plan, consent/receipt, native task and run; no new dispatch |
| GET `/project-commands/{requestId}` | Owner's original creation record |
| GET `.../{requestId}?refresh=true` | Read-only remote candidate observation, retaining UNKNOWN |
| POST `.../{requestId}/connect` | Acknowledged project ID only; explicit `harness`/`model`, scoped local binding |

Browser storage holds only request/plan IDs and a start-attempt marker. It does
not retain repo paths, paper details, model credentials or project content.

## Evidence and remaining live gate

Unit/API tests cover source validation, disabled sync, no fake idempotency,
per-request approval/cancel, late cancellation, double clicks, lost responses,
restart, secret echo rejection, expiry and owner isolation. Mounted UI tests
cover disclosed consent, recovery without replay, candidate warnings and explicit
session handoff. The two real-PG/native-queue cases are included in
`scripts/check_boundaries_postgres.py`; its expected case count is 15 and any skip
fails acceptance. They exercise the create-to-session-to-research-result chain
and concurrent admission/UNKNOWN/revocation with a controlled ORX-shaped peer.

Real E2E still requires an owner-authorized compatible endpoint and safe service
credential handoff, exact repo/path/paper input, permission to write/clone/fetch
on that remote host, explicit consent to possible starter/model costs, harness
and model selection, applicable plan reviews, and separately approved research
messages. Collect actual native IDs/transcripts and recovery evidence. No real
credential, model request, clone or research execution was used in this change.
Frontend visual acceptance remains paused; mounted behavior is not browser/live
acceptance. Managed multi-step execution and general installers are outside scope.
