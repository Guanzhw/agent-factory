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

This establishes clean-stop logical restoration. Live-write consistency, PITR,
power loss, RPO/RTO, backup encryption, retention, offsite recovery, monitoring and
target-host throughput remain production acceptance work.

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
