# Versioned material governance

Six inert material kinds are supported: instructions/prompts, skills, tools,
knowledge, models and environments. A material content version, SHA-256 and
pinned dependencies are immutable. Draft, published, withdrawn and archived
state lives in a separate governance record; it never changes old plan content
or artifact evidence.

## Current permissions and publication

Authors require current native `components:write`. Ordinary users discover only
active approved versions. Authors inspect their own draft/history; a current
native administrator can inspect and review all authors. Labels in the UI
reflect current capabilities and grant no permissions themselves.

Default policy is `separate-admin` in both demo and production. The author first
requests review for one exact version/digest; a different current `agent_os:admin`
principal approves or denies it. Reviewing a plan or approving one experiment
does not publish materials. A configured policy revision is persisted and cannot
silently overwrite another running process's current governance configuration.
Stale revision/digest, lost rights, self-review and conflicting duplicate commands
fail closed. Unreviewed published database records are not trusted.

`FACTORY_MATERIAL_REVIEW_MODE=demo-self-review` is an explicit compatibility mode
accepted only in synthetic demo configuration. Production rejects it. The
checked-in nine original synthetic bootstrap versions have exact-content,
original-audit adoption; startup does not restore an archived/withdrawn version.
No second administrator or production account is provisioned automatically.

Archive is an author-managed version state; withdrawal requires current native
administrator rights. Both remove the version from discovery and current plan
execution. Native admission, resumes, tools and every delegated ancestor recheck
current governed versions. Active fixed compute also rechecks current authority
every 250 ms and cleans up its owned process when authority ends. Existing
historical plans/results remain inspectable with current read permission.

## Bounded inert import

The importer accepts at most 30 structured JSON definitions, 256 KiB, depth 12
and 3,000 nodes. It does not fetch a URL, install a package, load code or run an
agent. Definitions include compatibility, supported license, provenance/notice,
typed schemas and exact versioned dependencies. Upstream reuse requires a source,
pinned revision and preserved notice. Secret fields, credential-bearing URLs,
external schema references and unknown runtime tool/capability names are rejected.
A new imported definition enters draft state and uses the same review path.

Registered tools use fixed identifiers and permission sets; editor text cannot
register arbitrary code. Current original runtime tools remain allowlisted.
Supported import licenses are MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause,
CC0-1.0 and CC-BY-4.0. This validation preserves supplied provenance; it cannot
independently certify an author's licensing claim.

## Commands and UI recovery

`/api/factory/material-governance` exposes draft/import, version inspection,
review request/decision, archive and withdrawal. Mutations require a semantic
request key. Identical retries return the persisted command result; changed
payload with the same key returns conflict. Current permissions are checked even
on a repeated command. The legacy publication endpoint now requests review;
it cannot directly publish.

The material UI supports all six kinds, exact active dependencies, registered
tool selection, provenance/license/schema editing and bounded JSON import.
Session storage contains only payload hashes and opaque command IDs, never
material text or credentials. Lost acknowledgements retain the same command key.
Malformed policy/review responses disable write actions until a verified refresh.

Nineteen focused tests include actual PostgreSQL/native queue/HTTP, author/reviewer
separation, concurrency, current permissions, immutable history, import rejection
and dependency/plan guards. Actual Edge acceptance covered duplicate clicks,
lost acknowledgement recovery, independent administrator publication, version
archive/withdrawal, fail-closed malformed responses and 390px layouts. All
identities and materials in that acceptance belong to disposable synthetic DBs.
