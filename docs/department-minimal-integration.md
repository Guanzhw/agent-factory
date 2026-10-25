# Trusted-team integration

The current product serves a small trusted department. Active members create,
configure, publish, revise, withdraw and archive their own applications and
materials. Administrators manage accounts only. Public visibility permits use
and copying; a copy receives a new identity owned by the copying member.
Personal data and credentials remain owner-scoped.

## Current composition contract

1. Core `Settings` uses
   `temporary_policy="member-self-service"` and
   `material_review_mode="member-self-service"`. Their default revisions are
   `department-member-v1` and `material-department-v1`. Retired execution/publication
   modes are rejected, including in demo profiles. Plan-review TTL configuration
   is removed. Services consume the supplied runtime configuration; historical
   policy tables do not gate startup.
2. Materials and applications use `service.publish(...)` directly as their author.
   New versions retain immutable body/hash references. Withdrawal and archival
   change availability without rewriting historical versions or completed evidence.
   The author manages public and private versions; account administrators have no
   resource-management override.
3. Material/application navigation is available to members. PlanReviews is
   owner-scoped historical inspection. Retired review-write APIs return HTTP 410.
   New execution uses current membership, ownership, ready plans and available
   resources; old review outcomes are not execution credentials.
4. Tool validation uses the actual installed descriptors, including persisted
   member-created CLI/MCP tools. New workers load missing member registrations
   from stored resources. Tool names/capability metadata express application and
   parent-task scope, not a separate operator authorization allowlist.
5. `PersonalCommandAPI` retains its current connection-pin, session/project and
   project-create-consent guard through Store execution guards. Members manage
   their connections and choose personal/team sharing; shared use keeps the
   credential owner's secrets private. TLS and SSH host identity still verify
   the selected destination.

## Persistence and recovery

Existing plans, reviews, tasks, effects and artifacts retain their original
identities. Historical owner-submission rows remain readable data. Startup does
not replay prior work or rewrite policy rows to manufacture execution approval.

Per-owner/global active-task limits, tool/time/output budgets, cancellation and
current resource state remain enforced. Original request IDs, effect receipts,
UNKNOWN reconciliation and positive stop evidence keep their operational roles.
Disable an account, withdraw a resource, pause a schedule or cancel an owned task
through the corresponding current API rather than selecting an old policy mode.

The earlier branch handoff based on `615a23f` used administrator resource control
and retained executable review modes. It is superseded by this contract. Frozen
historical artifact verifiers continue checking their original release bytes;
they do not define current settings or membership behavior.
