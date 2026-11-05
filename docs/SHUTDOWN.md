# Official launcher shutdown

`python -m agent_factory` (standalone core) and `python -m agent_factory_server`
(deployment composition, also the `agent-factory` command) use the same process
policy from `agent_factory.shutdown`. The Research launcher inherits that policy
through deployment composition.

The existing 35-second deadline starts when lifespan cleanup begins. A daemon
timer also enforces it when synchronous cleanup blocks the event loop. Clean
cleanup returns normally; cleanup failure or an expired deadline exits with
status 1. Process exit does not rewrite original-operation recovery records;
uncertain operations still require inspection of their original identity.

Reusable `create_app` callers can continue to supply their own `shutdown_guard`.
The official CLI selects the shared process policy explicitly. The former
`agent_factory_server.shutdown` imports remain compatible exports of that policy.

Run `python -m unittest test_shutdown test_worker_capacity test_workflow_contracts
test_workflow_operations` with the repository's `platform`, `deployment`,
`platform/tests`, `applications`, and `applications/tests` on `PYTHONPATH`.
The portable shutdown check launches both CLI modules with real Uvicorn and a
synthetic database-free lifespan. Its stalled-cleanup case shortens only the test
timer; a separate assertion retains the actual 35-second argument. This does not
validate native PostgreSQL recovery, Linux process cleanup, or deployed capacity.
