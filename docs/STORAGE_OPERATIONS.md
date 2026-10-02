# Single-host disk governance and recoverable retention

Factory now observes physical free space before committing a new task admission.
A PostgreSQL transaction serializes task and disk reservations together: refusal
leaves neither a task nor a partial disk hold. An existing request still returns
its original admission during low space. UNKNOWN work, paused tasks and resources
without positive reclamation evidence continue to consume reservations.

This is conservative admission control, not a filesystem quota. A task can write
more than its reserved amount; unrelated processes and Docker can consume space
between observations. Used bytes and still-held reservations are both subtracted,
intentionally overestimating committed space rather than promising capacity that
may disappear. Existing nonterminal tasks receive holds on upgrade, without
adopting their historical directories for cleanup.

## Operator settings

| Trusted setting / environment | Default | Meaning |
| --- | --- | --- |
| `storage_task_reserve_bytes` / `FACTORY_STORAGE_TASK_RESERVE_BYTES` | 64 MiB | Additional hold per admitted task; the selected local ORX profile explicitly uses 4 GiB |
| `storage_low_water_bytes` / `FACTORY_STORAGE_LOW_WATER_BYTES` | 1 GiB | Free-space floor after all holds and the proposed admission |
| `storage_monitor_paths` / `FACTORY_STORAGE_MONITOR_PATHS` | empty | Additional operator-owned filesystems to check, separated by the OS path separator |
| `storage_retention_grace_seconds` / `FACTORY_STORAGE_RETENTION_GRACE_SECONDS` | 86400 | Quarantine recovery window; production requires at least 60 seconds |
| `storage_allow_purge` / `FACTORY_STORAGE_ALLOW_PURGE` | false | Permanent manifest reclamation is disabled unless explicitly enabled (`true`) |
| `storage_scan_entries`, `storage_hash_bytes` | 20000, 64 MiB | Per-directory inventory/hash bounds; exceeding them refuses retention |

Workspace storage is always checked. Add the actual Docker data-root mount and
local PostgreSQL data mount if they are separate; remote PostgreSQL disk is not
observable from this host. Filesystems are deduplicated by device identity. In
this cloud environment `/workspace` and Docker vfs use the 32 GiB root filesystem,
whereas temporary test workspaces may be on a separate tmpfs. Do not extrapolate
a tmpfs fixture's free-space display to the Docker root mount.

`GET /api/factory/storage` is owner scoped for task holds, database artifact bytes,
managed directories, retention plans and original ORX container identities. Global
filesystem usage and total reserved bytes are shared capacity observations. The
response declares its bounded inventory limits; it is not an exhaustive history
export. Unconfirmed hold reconciliation is returned separately, retaining its
reservation. Inventory runs off the event loop. Docker inspection has a two-second
per-container bound and never constructs an adapter or starts a runtime.

Docker `SizeRw` and `SizeRootFs` are logical observations, **not additive physical
allocation accounting**. In particular, vfs copies and shared images cannot be
assigned accurately to users by summing those fields. Original container ID,
task-derived name, receipt/specification, image and scope mount must match. Missing
or substituted containers are unconfirmed. Existing ORX containers and evidence
remain protected; this implementation does not delete them, prune images, clean
build caches, or infer positive stop from missing files. A future container
retention protocol must preserve durable stop proof before removing identities.

## Owner-scoped retention

Only internal producers register a deterministic task scratch object under
`managed-storage/objects`. No API accepts a host path or registers a historical
directory. Database artifacts, ORX evidence, evidence-marked objects, active or
UNKNOWN tasks, unresolved control evidence, and unreclaimed leases are protected.
A stopped root also requires positive stop of its delegation group.

1. `POST /api/factory/storage/retention/plans` with `objectId` and `requestId`
   records a dry-run manifest and audit event. It moves nothing. Reusing the key
   recovers the original plan even after quarantine; substituting an object fails.
2. `POST .../retention/plans/{id}/quarantine` rechecks current run permission,
   ownership, protection, directory identity and content hash, then persists a
   MOVING intent before renaming into the private quarantine namespace.
3. `GET .../retention/plans/{id}` can reconcile an interrupted rename's receipt.
   It never moves or deletes files and never resumes a partial purge.
4. `POST .../retention/plans/{id}/restore` explicitly restores a matching complete
   quarantine to an empty original location. Conflicting content is not overwritten.
5. Only with operator policy enabled and grace elapsed, `POST .../{id}/purge`
   records PURGING, removes the explicitly observed manifest, and retains PURGED,
   the audit history and logical-byte receipt. A partial purge needs another
   explicit owner action. Once PURGING begins, restore is refused: some bytes may
   already be gone. Reported reclaimed logical bytes are not a physical-free-space
   guarantee; use a new filesystem observation to assess admission.

The Chinese “磁盘与回收” screen exposes these operations, the recovery window and
UNKNOWN occupancy. Browser restart loads original server plans without issuing
mutation requests; switching identities clears owner data.

A shared PostgreSQL advisory lock fences registration, plan construction, receipt
reconciliation and transitions across processes. Permission/protection is checked
again after acquiring it. Linux descriptor walks reject symlinks, hardlinks,
nonregular entries, mount crossings, replaced directory identities and incomplete
inventories. Renames fsync both namespace directories. This proves bounded process
crash recovery, not power-loss durability across arbitrary storage hardware, a
security sandbox against a hostile host administrator, or Windows retention.

## Reproduction on disposable fixtures

Use the repository's isolated PostgreSQL test configuration, then:

```sh
PYTHONPATH=platform:platform/tests uv run python -m unittest -v \
  test_storage_governance test_storage_process test_storage_runtime \
  test_resource_pressure_postgres test_online_restore_postgres
npm run check
npm audit
```

The online restore case also requires `FACTORY_PG_BIN` pointing to official
`pg_dump`/`pg_restore`. Optional `FACTORY_PRESSURE_EVIDENCE` and
`FACTORY_ONLINE_RESTORE_EVIDENCE` write synthetic measurement JSON. The browser
acceptance uses installed Playwright Chromium, a built frontend and
`scripts/accept_storage_browser.py --output <owned-output-directory>`.

All destructive tests create their own rebuildable directories. They never
recursively delete historical evidence, use Docker prune, or operate on unrelated
user directories. The recovery package created during the cloud disconnection
check remains outside the repository.
