# Configurable plan approval

This verified stage adds approval to the complete factory delivery. It does not enable a live provider, authorize spending or provision production identities. The user has not selected a final production approval policy; the implementation keeps that choice configurable and uses a conservative default.

## Operator configuration

| Setting | Default and behavior |
| --- | --- |
| `FACTORY_TEMPORARY_POLICY` | Production: `admin-review`. Explicit demo: `bounded-synthetic`. Also supports `read-only-auto` and `unset`. |
| `FACTORY_POLICY_REVISION` | `plan-policy-v1`; immutable configuration identity. Reusing a revision with different policy semantics is rejected. |
| `FACTORY_PLAN_REVIEW_TTL_SECONDS` | 3600; accepted range 60–86400 seconds. |

`unset` denies execution. `admin-review` requires an administrator decision for the exact persisted plan. `read-only-auto` permits only registered read-only tools/capabilities; experiments require plan review. `bounded-synthetic` is limited to demo mode and explicitly synthetic plans. These policies cannot select a model, grant a role, widen tools or approve native experiment confirmation.

Configuration is persisted in PostgreSQL and checked at admission, native plan binding and every protected tool boundary, including direct registered tool entrypoints. Changing settings to `unset` is also an emergency execution clamp. Operator changes use the trusted `replace_configuration` compare-and-swap method with an expected current revision. There is no HTTP policy-edit endpoint. Restarting with a mismatched configured revision fails rather than silently changing the persisted policy; apply an intentional operator transition first, then start with matching settings.

Live material/model/runtime preflight remains blocked until separately configured and validated. Selecting an approval policy does not remove that restriction. Demo identities are test fixtures and are never provisioned in production mode.

## Review and execution boundaries

Users request review using `POST /api/factory/plan-reviews` with `planId` and a stable `requestId`. Native managed identity supplies the owner. Requests bind the immutable plan digest/fingerprint, policy revision/digest and expiry. Repeated identical requests return the same persisted review; changed meaning returns 409. Only current `agent_os:admin` authority can decide. Requester/body role claims are ignored, and an ordinary user cannot approve their own request. Decision keys are also semantically idempotent.

The owner or a current administrator can inspect reviews. Review projections include verified goal, tools, capability ceilings, budget and material references for human assessment. Administrator status comes from current native SQL authority, not the model or token role claims. Approvals expire, and newer exact-plan decisions supersede earlier decisions. A new policy revision invalidates prior approvals. Current run rights must still exist when work executes.

The Chinese UI submits an owner's review and shows current execution permission. The administrator review page exposes exact scope and permits approval or denial. A denied, expired or superseded review requires an explicit new request; uncertain acknowledgements retain the original key. The UI polls authoritative state and fails closed when it cannot read it. A general durable browser command journal remains separate work.

Native tool HITL stays independent. An approved experiment plan still pauses for native confirmation. Native confirmation cannot replace a missing, revoked, expired or superseded plan approval. Once execution rights change, prior valid artifacts remain as evidence; no new process, protected effect or artifact is authorized.

Delegated children inherit review only after verifying the actual persisted parent/root links, native ticket owner/session/component, current ancestor mandate and subset tools/capabilities/budgets. Their root's current approval must remain effective. Models cannot invent an ancestor proof or reset shared budgets.

## Evidence and remaining acceptance

Eighteen focused tests use real native JWT/managed SQL authorization and durable review storage. Four use the actual wired Factory app, PostgreSQL queue, native HITL and persisted child mandates; fourteen portable boundary tests use an explicitly separate disk SQLite fixture. Production Factory metadata remains PostgreSQL-only. Concurrent requests with a one-connection pool retain one review and avoid nested-transaction pool deadlock.

Real browser acceptance used an isolated PostgreSQL database and separate owner/reviewer browser contexts. Repeated review submission produced one review; self-approval returned 403; unreviewed admission returned 409 and created zero tasks. The administrator inspected scope and approved; the owner then created exactly one native ticket and one hashed synthetic artifact with one execution POST. A denied plan remained disabled with zero tasks; an explicit new review recovered after administrator approval. Desktop scope rendering and both owner/administrator 390px layouts passed inspection. Expected refusal responses were injected/checked explicitly.

Real identity onboarding, a chosen provider/spending limit and live research acceptance remain unapproved. The conservative production default is a recommendation implemented as configuration, not a final user policy decision. No external access or paid execution was introduced by this stage.
