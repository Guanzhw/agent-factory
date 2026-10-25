# Explicit environment continuation

> **Historical — application not installed.** This document records the retired Research/ORX application and earlier acceptance. Its routes, source paths, configuration and commands are not current core-only setup instructions. Original evidence, failures and UNKNOWN outcomes below are preserved; they do not certify the current revision. Source retirement does not authorize deleting old data, credentials, vault keys, artifacts or backups.

Factory retains the original environment body, package pin, native project ID,
runtime control marker and data directory. Changing a personal credential does
not modify an existing task, recreate a session or replay a research goal.

On the OpenResearch page, open **Research records and connection settings** and
check the original environment's recovery conditions. The read distinguishes:

| Condition | Available next step |
| --- | --- |
| Current credentials and compatible original package | Read the session, or explicitly restore the stopped original environment. |
| Verified current credentials changed | Positively stop the environment, review the current choice, then explicitly confirm a credential binding. Restore separately and use the existing session rebind flow. |
| Original operation is UNKNOWN, preparing or stopping | Read that original request. No automatic retry, work replay or checkpoint claim. |
| Credentials unavailable | Repair and verify the owner's credentials, then check again. Original records remain readable. |
| Platform package changed, or original SSH host scope cannot be established | Explicitly create a new environment and project; retain the old environment, session and results. No goal is submitted by this operation. |
| SSH package changed in an existing directory | In-place update is unsupported. Retain the old files and data; explicitly select another authorized private directory or runtime location. No install is attempted in the original directory. |

## Boundaries

Only Factory changes its current credential binding and records an append-only
old/new binding journal. The original environment body is never rewritten.
Rebinding requires a positively `STOPPED` environment, an explicit `approved:
true`, the exact current preview hash, the authenticated owner and current model
authority. This metadata operation neither prepares compute nor resolves a
model key. Runtime access rechecks the current binding and owner authority.

For new SSH environments, a separate stable scope pin covers owner, server
reference, address, port, login, host key and allowed root. A credential revision
may change only within that original scope. Legacy environments without this
evidence refuse a changed SSH server/key pin; they do not guess that two targets
are equivalent. An explicit new environment keeps the old records available.

The platform and SSH adapters continue to use their original fixed runtime,
private data and signed control markers. A changed current credential binding
produces a different connection credential revision. Existing native sessions
must use the existing, explicit same-identity session rebind; unresolved prompts
or interrupts still block it. No replacement executor or universal checkpoint
resume is introduced. A compatible stopped environment is not proof that an
interrupted native loop can resume. Package changes require another environment;
this does not install or upgrade an operator's runtime package.

## Owner-scoped API

- `GET /api/factory/application-environments` lists up to 100 owned metadata
  records. Stored `ready` is not live proof; inspect the original environment.
- `GET /api/factory/application-environments/{id}` inspects current availability
  and exposes its last original prepare/stop operation for recovery.
- `GET /api/factory/application-environments/{id}/continuation` reads recovery
  conditions, choices and the preview hash. It never submits work.
- `POST /api/factory/application-environments/{id}/rebind` accepts `requestId`,
  `previewHash`, and strict `approved: true`, with `X-Factory-Expected-Owner`.
- `GET /api/factory/application-environments/binding-requests/{requestId}` reads
  the original committed binding receipt. A missing receipt does not authorize
  replay. Retain its request ID after an unknown acknowledgement.
- The existing prepare endpoint additionally accepts strict `newEnvironment:
  true` for an explicit distinct generation. Its original request ID identifies
  that generation; replay returns the same custody record and never installs
  again. The existing request endpoint remains the recovery read.
- Prepare also accepts `environmentId` for an explicit restore of existing owner
  custody, including a distinct generation. It cannot be combined with
  `newEnvironment`; application, location, SSH selection and original package
  and credential pins must match. Missing or foreign IDs never select a default
  environment. Start and restore use the selected ID, including after refresh.

The browser persists original binding and stop request IDs before writing.
Refresh/return can discover an owned pending operation, then reads that original
request. Missing acknowledgements remain unresolved. Only named pre-commit
rejections permit another explicit review; transport failures do not.
Only opaque environment/project/connection pointers are retained as the owner's
selection hint. Discovery still inspects server-owned identity before enabling
environment writes. Changing research or location removes the old write target;
missing, ambiguous and late discovery responses cannot act on another project.
Once an explicit new generation is positively prepared and its native identity
is checked, its opaque selection is saved and the previously selected research
is cleared. Refresh cannot select that old research again automatically; its
history and results remain available for an explicit read.

## Validation scope

Portable tests cover frozen identity, authority rechecks, stable SSH scope,
UNKNOWN refusal and explicit distinct generations. Required disposable
PostgreSQL tests additionally exercise restart, actual HTTP owner/consent
checks, old receipts, stale previews, revocation and corrupt binding journals.
Browser tests cover changed previews, lost acknowledgements, original-request
reads, account changes, durable-storage failure and goal-free preparation.
These fixtures prove their declared mechanisms; they do not certify a real
model, external device, arbitrary runtime version or interrupted checkpoint.
