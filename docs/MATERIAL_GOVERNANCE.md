# Versioned material governance

Six inert material kinds are supported: prompts, skills, tools, knowledge,
models and environments. Content versions, SHA-256 values and pinned dependencies
are immutable. Draft, published, withdrawn and archived state lives in a separate
record, preserving earlier plans and artifact evidence.

## Membership, ownership and publication

`Settings` and `ResearchSettings` use `member-self-service`. Every active member
can create and directly publish their own exact versions. Authors manage their
own drafts, revisions, withdrawals and archives. Account administrators manage
accounts and have no override over another author's materials or private history.

Members can use active published versions. Copying another author's published
material creates a new ID owned by the copying member; the original version chain
and task references retain their identity. Revising an owned material creates a
new immutable version. Withdrawn or archived versions require a new draft before
publication. See [member publication](MEMBER_PUBLICATION.md) for the page flow and
API examples.

Publication requires the stored immutable body and its published dependency
closure to remain current. A withdrawal or archive removes the exact version from
active discovery and later execution checks. Admission, tool invocation and
relevant delegated ancestors continue to check current resource state and budgets.
Completed plans, artifacts and version history retain their original content.

The original synthetic bootstrap versions have exact-content and seed-audit
adoption. Demo startup preserves an existing withdrawal or archive; it does not
reactivate it. Synthetic seed publication remains restricted to demo use.

## Bounded inert import and tool declarations

The importer accepts at most 30 structured JSON definitions, 256 KiB, depth 12
and 3,000 nodes. Definitions include compatibility, supported license,
provenance/notice, schemas and exact versioned dependencies. Upstream reuse
requires a source, pinned revision and preserved notice. Secret fields,
credential-bearing URLs and external schema references are rejected. Import saves
drafts and starts no process or provider call.

A tool material with `runtimeBinding` names an exact adapter ID and revision.
Its tool name and declared capabilities must match that adapter's current
registration. Member CLI/MCP connections use the same registry as installed
adapters; no deployment tool-permission list or extra policy revision is needed.
Same-name tools remain distinct by adapter identity. The material editor can load
current connected tool declarations and retains their binding when revising or
copying a material. Commands, endpoints and credentials stay in resource connections.

Supported import licenses are MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause,
CC0-1.0 and CC-BY-4.0. Validation preserves supplied provenance; it does not
independently certify the author's licensing claim.

## Commands, history and recovery

`/api/factory/material-governance` exposes draft/import, inspection, direct
publication, archive and withdrawal. Mutations require `requestId`. Identical
retries recover the persisted result; changed intent under the same key returns
conflict. Membership is checked on retries, and version mutations remain
owner-scoped.

Publication review request and decision APIs return HTTP 410. Historical reviews
remain readable only within their author's scope. Existing review/configuration
rows, hashes and version bodies remain intact. Runtime startup uses the current
supplied configuration, so old database approval modes do not gate startup or
publication. Supplying retired `separate-admin` or `demo-self-review` modes as new
runtime configuration is rejected.

The material page supports six kinds, exact active dependencies, current tool
declarations, provenance/license/schema editing and bounded JSON import. Session
storage retains payload hashes and opaque command IDs for acknowledgement
recovery; a lost reply is retried with the original key. Historical review loading
is separate from direct publication.

Focused regressions cover owner lifecycle and copies, administrator isolation,
old configuration/review preservation through a real PostgreSQL restart,
size-one-pool concurrency, exact same-name tool declarations, and native execution
of a newly connected member tool. See
[`test_material_governance.py`](../platform/tests/test_material_governance.py),
[`test_applications_composition.py`](../platform/tests/test_applications_composition.py)
and [`test_member_tool_restart_postgres.py`](../platform/tests/test_member_tool_restart_postgres.py).
Run records and live/browser acceptance remain separate from these source contracts.
