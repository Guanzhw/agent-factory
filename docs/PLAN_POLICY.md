# Member plan execution

Active members submit their own ready plans directly. Administrators manage
accounts; they do not approve plans or gain access to another member's history.
The native runtime still checks task ownership, current resources, cancellation
and execution budgets.

## Runtime configuration

| Setting | Current behavior |
| --- | --- |
| `FACTORY_TEMPORARY_POLICY` | `member-self-service`, the only supported value |
| `FACTORY_POLICY_REVISION` | Defaults to `department-member-v1`; identifies the supplied runtime configuration |
| `FACTORY_MATERIAL_REVIEW_MODE` | `member-self-service`, the only supported value |
| `FACTORY_MATERIAL_POLICY_REVISION` | Defaults to `material-department-v1`; identifies material runtime configuration |

`Settings` and `ResearchSettings` reject retired modes such as `admin-review`,
`read-only-auto`, `bounded-synthetic`, `unset` and `separate-admin`. Remove the old
`plan_review_ttl_seconds` constructor field and `FACTORY_PLAN_REVIEW_TTL_SECONDS`
environment variable. Review expiry is no longer an execution setting.

Services use the current configuration supplied at startup. Historical policy
configuration rows and fingerprints remain stored data; they do not require a
revision transition or a matching approval before startup or new execution.
Materials and applications validate against the installed tool descriptors,
including member-created tools, rather than a separate tool-policy allowlist.

## Admission and runtime controls

`GET /api/factory/plans/{plan_id}/authorization` reports the current owner's
plan readiness and execution status. Submission uses the normal Factory task
API and native queue. The selected application, material versions, model,
connections and runtime bindings must remain available for that operation.
Budget, cancellation, member-disable and resource-withdrawal checks continue
at their owning execution boundaries.

Delegated children retain their persisted parent/task/run identities and stay
within the parent's tool scope and budgets. An installed tool's native operation
confirmation remains specific to that operation; it is not administrator plan
review. UNKNOWN acknowledgements retain the original operation and capacity
until reconciliation establishes the result or positive stop evidence.

## Historical reviews

Members can read their own historical records through the `/plan-reviews` GET
routes. Original decisions, expiry and plan references remain visible as history;
they grant no current execution authority. The plan-review POST and decision
routes return HTTP 410 (`PLAN_REVIEWS_RETIRED`).

Earlier review-required browser and PostgreSQL results describe the retired
implementation. Current direct-member execution, history isolation and runtime
controls must be verified against the current source and test results.
