# Operations and restoration evidence

Initial topology is one application process, PostgreSQL and two native worker
slots. The default holds at most two tasks per user and twelve globally; paused
and UNKNOWN work retain capacity. Twenty users are not twenty workers. Resource
targets of 32 cores/64 GB or 54 cores/192 GB have not been load benchmarked.

## Logical backup and restore

The automated acceptance test uses official PostgreSQL 17.11 `pg_dump` custom
format with `--no-owner --no-acl`, followed by `pg_restore` into a distinct empty
generated database. It stops its original API/worker/poller before backup and
restarts the actual application against the restored DB and a fresh workspace.
It never clears the supplied base database or copies production data.

Verified restoration covers every owned table's types/defaults/nullability and
primary key plus row counts/data digests; immutable plans/reviews, native original
ticket, current managed rights, revoked run permission, archived/withdrawn
material, UNKNOWN admission hold and artifact bytes/SHA survive. Startup submits
no second ticket and does not re-enable withdrawn materials or revoked grants.

Operator-owned JWT keys, policy revisions, runtime configuration, provider/remote
connections and executable provenance are separate trusted configuration; a DB
dump is not their backup. Restore them through the approved secret/configuration
channel. PostgreSQL owners/ACLs are intentionally excluded in this test and must
be provisioned appropriately for a real deployment.

To reproduce only on an authorized disposable PostgreSQL server:

```powershell
$env:FACTORY_TEST_DATABASE_URL='postgresql+psycopg://test-user@127.0.0.1:5432/disposable_test_db'
$env:FACTORY_PG_BIN='C:\path\to\postgresql\bin'
$env:PYTHONPATH='platform;platform/tests'
uv run python -m unittest test_restore_postgres -v
```

Both environment values are required; otherwise this test explicitly skips.
Use server-side secret configuration or an approved private password file for
real credentials. Do not put passwords into command arguments, logs or repository
files. Test-created databases and the temporary dump are removed by their own
recorded fixture cleanup.

This establishes clean-stop logical restoration. The separate online-write
acceptance below covers one exported database snapshot. PITR, power loss, RPO/RTO,
backup encryption, offsite recovery and target-host throughput remain production
acceptance work.

## Admission capacity acceptance

Three actual native queue/PostgreSQL tests use twenty generated test identities.
Twenty concurrent submissions yield twelve held tasks and eight quota rejections;
the held count never exceeds twelve. Per-user limits, original-key duplicate
recovery, current-rights revocation and positive cancellation release are tested.
An UNKNOWN/no-ticket reservation remains held after cancel/reconcile; a known
stopped ticket frees its own reservation and allows a previously rejected request.
No production identities/grants are created by these tests. They verify admission
invariants, not CPU/RAM throughput, fairness under sustained model load, or
twenty simultaneous experiments.

## Online-write snapshot acceptance

`test_online_restore_postgres` adds a separate live-write test; it does not replace
the clean-stop proof above. A completed native task and a durable UNKNOWN admission
exist before the cut. An explicit read-only REPEATABLE READ transaction exports a
PostgreSQL snapshot and remains open while official `pg_dump --snapshot` runs.
A bounded writer commits up to 64 KiB of new database-backed artifacts concurrently.
The dump is restored into a distinct empty generated database and the real Factory
starts against it. Artifact IDs and SHA-256 bytes match the exported snapshot;
confirmed-before records survive, confirmed-after records are excluded, and the
original completed native ticket plus UNKNOWN/no-ticket hold survive without a
second submission.

For an operational cut, record the exported snapshot and its cut boundary in a
private backup receipt, keep its transaction open until pg_dump succeeds, verify
restore into a separate target, then reconcile uncertain external operations by
their original identities. An acknowledgement after the cut is not promised by
that backup even if the live server committed it successfully. A restored UNKNOWN
is not evidence of failure or permission to replay.

This proves one database snapshot, including BYTEA artifacts, under concurrent
writes. It does not provide online consistency for separately mutable workspace
files, Docker state, provider credentials, external side effects or files copied
at a different time. Protect immutable external evidence with its own verified
manifest/cut procedure before production recovery. PITR, WAL archival, production
RPO/RTO and offsite recovery remain unproven.

## Bounded resource-pressure and progress acceptance

`test_resource_pressure_postgres` uses twenty synthetic users, two actual native
workers, a twelve-task global limit, a two-task user limit and one UNKNOWN
reservation held throughout. Twenty finite client requests are admitted in bounded
waves; quota refusals have no task row and retry the same original key after
positive cleanup. Every admitted task reaches native waiting-input state; waiting
tasks retain disk holds. Low-water observation is injected rather than filling the
disk. Original admission receipts remain recoverable under pressure, new work is
refused, and positive cleanup releases only its own hold. UNKNOWN remains occupied.
The existing real-worker delegation tests additionally enforce the shared inherited
tool budget and refuse work after its durable exhaustion.

This establishes absence of starvation **for this finite, bounded retry workload**.
Agno's native claimed-job order remains FIFO. Factory's 429 pre-admission boundary
has no durable fair waiting queue, so fairness under unbounded hot-user refills,
long-running CPU jobs and adversarial arrival patterns is not established. No
replacement execution queue or unbounded load generator was introduced. Measurements
from the cloud's 4-CPU/16-GiB cgroup are not 32-core/64-GB or 54-core/192-GB capacity
validation. See [disk operations](STORAGE_OPERATIONS.md) and the checked-in synthetic
measurement curves for configuration, occupancy, process memory and CPU limits.
