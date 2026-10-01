# Independent cloud acceptance support

This directory runs without the application, database, model keys, paid compute,
or a connected developer laptop. It adds test support only. It does **not**
replace or modify the Agno AgentOS 3.1.0 / PostgreSQL application implementation.

The HTTP contract here is a **proposed Factory adapter test boundary**, not a
claim that these endpoints exist in AgentOS or the application. The reference
server is a disposable synthetic fixture with deliberate fault controls. Never
deploy it or use its fixed fixture identities as authentication.

## Run

Python 3.11+; standard library only. From the repository root, on Windows or Linux:

```sh
python cloud-validation/run.py --report cloud-validation/reports/result.json
python cloud-validation/resource_profile.py cloud-validation/profiles/standard-32core-64gb.json
python cloud-validation/resource_profile.py cloud-validation/profiles/upper-54core-192gb.json
```

The runner discovers all `test_*.py` files here. Each HTTP scenario creates an
isolated, temporary SQLite fixture database and an ephemeral **127.0.0.1** port,
then closes both. There are no model requests, external network dependencies,
credentials, installations, provisioned environments, or production mutations.
A nonzero exit means a failure, error, or skipped check. Generated reports contain
case IDs/results, source digest, and explicit evidence limitations; they are
ignored by Git. They use the executor's clock, not an external time authority.

For just the runtime contract:

```sh
python -m unittest discover -s cloud-validation -p test_runtime_contract.py -v
```

Continue running the repository's existing `npm run check` independently. Its CI
currently checks the scaffold, **not this Python suite**. This isolated change
does not alter root dependencies, scripts, application code, or workflow files.

## What is executable

- Real HTTP requests against a synthetic server, including post-commit connection
  loss, malformed acknowledgements, HTTP 503, concurrent duplicate commands, and
  fixture database reopen after restart
- Scoped session/run/operation/event/artifact behavior, interaction typing,
  revocation, snapshot reconciliation, and artifact digest validation
- Shared parent-child/user/host reservation accounting and cleanup gates with
  synthetic process evidence; a deliberately broken premature-release mutant
  demonstrates that the assertion catches that defect
- Strict arithmetic validation for two host planning profiles, including retained
  processes during waits and subtree budgets that cannot mint extra capacity

## What is not verified

Agno/AgentOS API compatibility, PostgreSQL transactions/migrations, browser UI,
identity-provider security, actual process-tree termination, filesystem/home/
credential isolation, network policy, real experiments or models, throughput,
latency, production capacity, backup RPO/RTO, and deployment are **unverified**.
The SQLite fixture is not a substitute for production database acceptance. The
post-commit fault is a controlled crash-window simulation; fixture restart is a
clean server shutdown/reopen, not an operating-system power-loss test.

See [protocol and integration handoff](../docs/cloud-acceptance/runtime-contract.md)
and [resource profiles](../docs/cloud-acceptance/resource-profiles.md).
