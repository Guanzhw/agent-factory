# Configurable plan approval

Normal `Settings.from_env()` and `ResearchSettings.from_env()` use `member-self-service` for direct new-plan admission. This document records the exact-plan review path for operators who explicitly select `admin-review` or `read-only-auto`; the review API, UI and browser evidence below do not describe the ordinary direct-member flow. It does not enable a live provider, authorize spending or provision production identities.

## Operator configuration

| Setting | Default and behavior |
| --- | --- |
| `FACTORY_TEMPORARY_POLICY` | Normal `from_env()` entrypoints: `member-self-service`. Direct demo fixtures may default to `bounded-synthetic`. Also supports `unset`, `admin-review` and `read-only-auto`. |
| `FACTORY_POLICY_REVISION` | Normal `from_env()` default: `department-member-v1`; immutable configuration identity. Reusing a revision with different policy semantics is rejected. |
| `FACTORY_PLAN_REVIEW_TTL_SECONDS` | 3600; accepted range 60–86400 seconds. |

`member-self-service` admits a direct member-created plan without a separate plan-review receipt; current permissions, materials, connections, adapters and budgets are still checked. `unset` denies execution. `admin-review` requires an administrator decision for the exact persisted plan. `read-only-auto` permits registered read-only tools/capabilities and requires review for other plans. `bounded-synthetic` is limited to demo mode and explicitly synthetic plans. These policies cannot select a model, grant a role, widen tools or approve native experiment confirmation.

Configuration is persisted in PostgreSQL and checked at admission, native plan binding and every protected tool boundary, including direct registered tool entrypoints. Changing settings to `unset` is also an emergency execution clamp. Operator changes use the trusted `replace_configuration` compare-and-swap method with an expected current revision. There is no HTTP policy-edit endpoint. Restarting with a mismatched configured revision fails rather than silently changing the persisted policy; apply an intentional operator transition first, then start with matching settings.

Live material/model/runtime preflight remains blocked until separately configured and validated. Selecting an approval policy does not remove that restriction. Demo identities are test fixtures and are never provisioned in production mode.

## Explicit plan-review and execution boundaries

When the active policy requires a review, users request it using `POST /api/factory/plan-reviews` with `planId` and a stable `requestId`. Native managed identity supplies the owner. Requests bind the immutable plan digest/fingerprint, policy revision/digest and expiry. Repeated identical requests return the same persisted review; changed meaning returns 409. Only current `agent_os:admin` authority can decide. Requester/body role claims are ignored, and an ordinary user cannot approve their own request. Decision keys are also semantically idempotent.

The owner or a current administrator can inspect reviews. Review projections include verified goal, tools, capability ceilings, budget and material references for human assessment. Administrator status comes from current native SQL authority, not the model or token role claims. Approvals expire, and newer exact-plan decisions supersede earlier decisions. A new policy revision invalidates prior approvals. Current run rights must still exist when work executes.

When the active policy requires review, the Chinese UI submits an owner's request and shows current execution permission. The administrator review page exposes exact scope and permits approval or denial. A denied, expired or superseded review requires an explicit new request; uncertain acknowledgements retain the original key. The UI polls authoritative state and fails closed when it cannot read it. A general durable browser command journal remains separate work.

Native tool HITL stays independent. Under a review-requiring policy, an approved experiment plan still pauses for native confirmation. Native confirmation cannot replace a missing, revoked, expired or superseded plan approval. Once execution rights change, prior valid artifacts remain as evidence; no new process, protected effect or artifact is authorized.

When the active policy requires review, delegated children inherit it only after verifying the actual persisted parent/root links, native ticket owner/session/component, current ancestor mandate and subset tools/capabilities/budgets. Their root's current approval must remain effective. Models cannot invent an ancestor proof or reset shared budgets.

## Evidence for explicit review policies

Eighteen focused tests use real native JWT/managed SQL authorization and durable review storage. Four use the actual wired Factory app, PostgreSQL queue, native HITL and persisted child mandates; fourteen portable boundary tests use an explicitly separate disk SQLite fixture. Production Factory metadata remains PostgreSQL-only. Concurrent requests with a one-connection pool retain one review and avoid nested-transaction pool deadlock.

Real browser acceptance of the review-required policy used an isolated PostgreSQL database and separate owner/reviewer browser contexts. Repeated review submission produced one review; self-approval returned 403; unreviewed admission returned 409 and created zero tasks. The administrator inspected scope and approved; the owner then created exactly one native ticket and one hashed synthetic artifact with one execution POST. A denied plan remained disabled with zero tasks; an explicit new review recovered after administrator approval. Desktop scope rendering and both owner/administrator 390px layouts passed inspection. Expected refusal responses were injected/checked explicitly. This evidence describes the explicit review path, not the current direct member-self-service default.

Real identity onboarding, a chosen provider/spending limit and live research acceptance remain unapproved. Normal environment entrypoints currently use `member-self-service`; `admin-review` remains an explicit operator-selected policy. Neither policy configures a provider or proves live production acceptance. No external access or paid execution was introduced by this stage.
