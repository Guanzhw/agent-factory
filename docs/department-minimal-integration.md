# Department collaboration integration (base 615a23f)

User scope, 2026-10-13: a trusted department of a few dozen people. Members create,
configure, publish and use public resources themselves. Only public deletion /
withdrawal / archival needs an administrator; history and immutable versions stay.
Personal secrets and data remain owner-scoped. No OS/network/provider grants change.

## Ownership

This branch owns auth.py, plan_policy.py, owner_submission.py, factory_api.py,
applications.py, material_governance.py, personal_command_api.py; PlanReviews, ApplicationGovernance,
MaterialGovernance and their focused tests. A owns main.py, store.py, config.py,
App.tsx, navigation and shared API assembly. B owns personal_models/ModelSettings.
C owns root instructions, architecture and CI. Shared files are not edited here.
No .agents/skills files existed in the selected environment.

## Required A integration

1. Settings and from_env: production new default temporary_policy=`member-self-service`,
   policy_revision=`department-member-v1`; accept that policy name. Explicit legacy
   policy names remain for historical regression fixtures, not a new product default.
   material_review_mode=`member-self-service`, material_policy_revision=`material-department-v1`;
   accept that mode. Existing demo bootstrap may retain explicit legacy modes; normal
   department entrypoints should select self-service. main.py's GovernanceConfig
   Literal cast must include `member-self-service`. Store continues writing the exact
   settings.temporary_policy in new immutable plans (currently composition.py does so).
2. Expose applications/materials navigation and panels to members. Admin label and
   destructive controls must use the actual administrator capability, not component
   author privileges. PlanReviews is historical read-only. Remove ordinary plan
   approval wording/steps. Keep native hazardous-operation/project-creation consent.
3. This branch supplies `web/publicationApi.ts` using the existing `factoryRequest`
   export; no shared API edit is needed. Application POST
   `/api/factory/applications/${id}/versions/${version}/publish` returns the exact
   `FactoryApplication` body; material POST
   `/api/factory/material-governance/versions/${id}/${version}/publish` returns
   `FactoryMaterial`. Both use `{requestId}` and expected-owner headers.
   Historical review projections preserve old API flags and add `readOnly`; no
   shared review type or validator change is required.
4. After A extracts app bootstraps, change normal application publication setup to
   service.publish(...) (no request_publication/decide_publication pair). Explicit
   historical fixtures using separate-admin can continue exercising old contracts.
   personal_command_api now delegates permission recheck to Factory admission. Its
   installed `personal-command` execution guard retains current connection expiry,
   owner scope and exact project-create consent checks for every ingress, including
   generic /instances. Keep this guard when extracting the application; these are
   write-safety checks, not plan approval or app-ID/prefix exemptions.
   The old owner-submission table is retained only as historical metadata.
5. Product profile guards explicitly requiring admin-review / separate-admin must
   be reviewed during extraction, especially development_workflows.py and profiles.
   Keep operator-installed adapters/remote grants and native dangerous-tool guards;
   only remove per-plan/per-version human-review predicates from normal entrypoints.

## Behavior and migration

New self-service plans must persist `policy=member-self-service`. Legacy plans
(including approved, denied, pending and UNKNOWN) fail new admission with
`LEGACY_PLAN_READ_ONLY`; create a new plan explicitly. No task dispatch runs during
migration, no history rows are rewritten, and original request IDs never become new
attempts. Legacy review mutation APIs return 410 under the new mode; GET remains.

Startup may migrate only the review name/revision while runtime tool contracts and
registrations match exactly. An emergency unset policy or changed execution contract
requires explicit reconciliation and is not automatically widened.

Public edits create new immutable versions. Existing exact-version references stay
unchanged; owner chooses a new version explicitly. Personal credentials are not public
materials; native identity, current access, owner isolation, TLS/SSRF, tool contracts,
request identity, effect idempotency, UNKNOWN reconciliation, and stop evidence remain.

## Retained application boundaries for A

- OwnerSubmissions has no research session/project imports or injected dependencies.
  It no longer grants admission and needs no new application exception interface.
- PlanPolicyService._project still calls project_review_summary only when rendering
  an old project-create review. A may supply this history-only formatter from the
  research application; it must not become an approval or dispatch hook.
- PersonalCommandAPI installs `_require_command_current` through the existing Store
  execution guard. This preserves private inputValues connection-pin freshness and
  exact project-create consent for both personal and generic task admission.
- ResourceService.execution_runtime still has its pre-existing research effect
  binding. This branch makes no resource executor changes; A can replace that import
  with its proposed explicit static research binding. No dynamic policy engine or
  new resource approval interface is needed.
