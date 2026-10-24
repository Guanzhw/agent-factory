# Member execution and resource maintenance

Active members create and run applications, native components, workflows and schedules, and publish their own materials/applications directly. Account administrators manage accounts. Each task remains bound to its submitting member, selected application, native run and resources.

Production callers use `AuthService.require_member(user_id)` for current membership. Account management routes use `require_account_admin(user_id)`. Resource services check ownership and current sharing at their actual use boundary. Account administration grants no access to another member's private resources, credentials, drafts or histories.

## Submission and migration

Create or accept a ready plan, then submit it to `POST /api/factory/instances` with the original `planId` and `requestId`. The request ID identifies that submission: retry with the same ID to recover the original task. Resolve a lost acknowledgement through the original request/task receipt before considering another submission.

The supported `temporary_policy` and `material_review_mode` value is `member-self-service`. Remove `admin-review`, `read-only-auto`, `bounded-synthetic`, `unset`, `separate-admin` and `demo-self-review` from deployment configuration. Startup rejects these retired modes. Plan review TTL and the secondary `tool_policies` registration are removed configuration fields.

Existing plan, review, decision, task, effect and artifact records retain their original identities and contents. Old approval configuration tables remain historical data; startup and execution use the current runtime configuration. Members read their own review history through `GET /api/factory/plan-reviews` and `GET /api/factory/plan-reviews/{id}`. Retired review creation and decision routes return HTTP 410. Historical decisions never authorize a new task. A historical plan without an execution manifest remains readable; regenerate it to execute with explicit bindings.

Research bootstrap, baseline and candidate scripts publish as the task owner and submit the resulting plan directly. A native tool can still request the invoking member's consent for its own operation. For example, the synthetic experiment tool pauses on its native requirement. Continuation keeps the original task/run/requirement identity and cannot resume a cancelled task.

## Runtime boundaries

The plan store verifies persisted snapshot integrity when loading a plan. The binding compiler validates selected material/configuration and produces its execution manifest. Internal runtime consumers use that compiled manifest directly. Tool entry owns the current member, selected task/tool and resource checks; model invocations retain their current execution/resource checks. A withdrawn application or unavailable resource rejects subsequent execution explicitly.

Cancellation, timeouts, concurrency, tool-call/output budgets, shared delegation budgets and usage accounting remain enforced by their owning runtime services. Child operations retain their parent scope and budget. Long-running adapters continue checking cancellation and resource state where new external work could start.

Original operation receipts remain durable. A completed effect reuses its recorded result; an UNKNOWN effect keeps capacity and requires reconciliation instead of starting another external operation. Artifact hashes identify actual saved bytes and remain part of provenance.

## Member-created tools

A supported CLI/MCP tool is saved as a resource with its public descriptor and owner-scoped credential connection. Application and material validation discover current tool identities from installed and persisted member tools. New tool names require no separate deployment permission registration.

Startup registers persisted tool adapters. A worker that has not loaded a newly created adapter resolves its exact adapter ID from the resource store on demand. It still checks current personal/team visibility and resource/credential state when called. The original adapter revision and connection pin remain part of the task; unavailable resources do not select substitutes.

## Resource maintenance

`POST /api/factory/resources/maintenance` scans only the current member's compute leases. The owner can reconcile expired leases, terminal tasks and requested stops. The service rechecks membership and lease ownership around provider calls. Account administrators cannot sweep another owner's leases.

Maintenance retains effect claims and UNKNOWN acknowledgements across retries. A cancellation acknowledgement does not prove process termination; capacity is released after the provider confirms release. Disabled members cannot invoke maintenance through the public endpoint.

## Verification boundaries

Portable tests exercise real native Agno loops with deterministic models, local processes and protocol fixtures. PostgreSQL tests exercise persisted submission/recovery, native cancellation and history with a size-one metadata pool. CLI execution is POSIX-only where required by its process containment contract; Windows skips do not establish Linux or CLI acceptance. Live paid providers and deployment compatibility require their own authorized verification.
