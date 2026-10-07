# Original research queue closure: read-only root-only gate

This narrowly scoped audit complements the original custody handoff. It does not
initialize services, mutate queue state, replay ACKs, reclaim resources, or claim
successful training. It proves absence of runnable descendants for the fixed
**root-only** research profile, not for arbitrary delegated workflows.

Use the original task ID, owner ID and request ID from the preserved bootstrap
progress plus original persisted mapping. Do not select the latest task. Run only
with an already configured trusted read-only PostgreSQL connection, while the old
service and workers remain stopped. Do not discover/export credentials, put a DSN
on the command line, or restart the app to obtain a connection.

For a preconfigured libpq service named `factory-original-readonly`:

```sh
psql -X --dbname='service=factory-original-readonly' \
  --set=original_task_id='ORIGINAL_TASK_ID' \
  --set=original_owner_id='ORIGINAL_OWNER_ID' \
  --set=original_request_id='ORIGINAL_REQUEST_ID' \
  --file=scripts/research_original_queue_audit.sql
```

The service name is illustrative: use the **existing** approved connection name;
do not create credentials to match this example. A trusted worker may instead
execute the same SQL through its already established read-only connection,
binding the three values as SQL parameters. Never interpolate them as SQL code.
IDs/results remain private. Do not publish raw queue payloads, session bodies or
plan contents; they may contain sensitive input.

The script uses one repeatable-read, read-only transaction, a 30-second statement
limit and a 2-second lock limit. It always rolls back. A SQL error, timeout,
missing table/column, absent output, or `UNKNOWN` is **not PASS**. Exit code zero
alone is insufficient: inspect the JSON `status` and every check. No rows are
truncated. This snapshot is valid only while old writers remain stopped; it is
not protection against a subsequently restarted worker or new submission.

## Scope and schema

The current `main.py` constructs `PostgresDb` without custom table/schema names:
Factory tables are `public.af_tasks` and `public.af_delegation_links`; pinned
Agno 3.1 tables are `ai.agno_jobs`, `ai.agno_runs`, `ai.agno_sessions`. These must
be the original database and original schema. A differently configured deployment
needs a reviewed schema mapping; never silently fall back to another database.

The query includes **every** ticket in the original session, every ticket named
by the original task or persisted session runs, and tickets whose persisted
`payload.kwargs.session_state.factory_envelope` names the original task or
owner/request pair. Thus same-session retries and continuations are not hidden
by only checking the original ticket. Owner mismatches are rejected, not filtered
away. Every included ticket must have a terminal status and the exact original
Factory envelope (including the persisted task's `plan_id`).

Every persisted original-session run must be terminal and backed by a queue
ticket. Every `parent_run_id` edge into or out of included run/ticket IDs causes
`UNKNOWN`, including cross-session children, cycles and dangling parents.
The same checks inspect nested `parent_run_id` fields in job payloads and run
data, including queued children without a run row yet. Every Factory link touching the task as root, parent or child also causes
`UNKNOWN`, including an unresolved intent with `child_id IS NULL`.

Consequently, **PASS proves that there is no first descendant edge at either
layer**, so a deeper descendant traversal is not applicable. A graph with any
actual delegation is outside this gate: do not reinterpret its zero related
pending count as a complete recursive closure. Preserve the failing check and
request a bounded graph-specific audit if such links exist.

A run/session row may never have been created for a ticket cancelled before
execution. Their absence is allowed when no run row exists; the original exact
terminal ticket is still mandatory. Neither training output, run-config, driver
seal nor train/eval receipts are required by this pre-dispatch queue check.

## Result boundary

`PASS` / `NO_DESCENDANTS_OF_ORIGINAL_ROOT` closes only the original queue/descendant question. Combine
it with the original task terminal state and the independently validated positive
compute/GPU release and never-dispatched custody chain. It does not replace those
resource checks, require their ACK replay, reconstruct missing historical driver
configuration, or transform the failed old attempt into success. Preparation of
a separately pinned, newly inventoried attempt remains governed by the main
handoff; preserve all old files, claims and receipts.

## Original plan provenance

The original plan source is `public.af_tasks.plan_id` joined to
`public.af_plans.id`; its preserved document is `af_plans.body` and its stored
canonical digest is `af_plans.hash`. `FactoryStore.save_plan()` wrote
`sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
ensure_ascii=False).encode())`. Existing plan audit must verify that digest and
the task fingerprint; hashing PostgreSQL `body::text` is not equivalent.
Neither a missing separate historical plan-hash file nor absent training artifacts
requires inventing replacement provenance. This SQL additionally verifies the
persisted body has the exact controlled research application, single research
tool, single local-compute capability, and no delegation/remote handoff. The SQL
profile check complements, and does not replace, the existing canonical hash audit.
