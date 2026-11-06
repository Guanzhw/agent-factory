# Server shutdown

The official launchers use Uvicorn and the shared application shutdown policy:

| Command | Application |
| --- | --- |
| `agent-factory` or `agent-factory-research` | Research composition |
| `python -m agent_factory_server.research` | Research composition |
| `python -m agent_factory_server` | Core deployment composition |
| `python -m agent_factory` | Standalone core |

## Two shutdown stages

Uvicorn first stops accepting connections and waits for network requests and transports to finish. Official launchers set `timeout_graceful_shutdown=35`. When that wait expires, Uvicorn proceeds to application lifespan shutdown.

Application cleanup then receives its existing 35-second deadline from `agent_factory.shutdown.shutdown_guard`. A separate timer also covers synchronous cleanup that blocks the event loop. Normal cleanup returns. An application-cleanup exception or expired deadline exits with status 1.

The budgets run in sequence. Total shutdown can take about 70 seconds plus scheduling overhead. The transport deadline is not a promise that every socket closed normally, and the application deadline does not begin when Uvicorn first receives a stop request.

A direct Uvicorn command must set its transport deadline explicitly:

```sh
uv run python -m uvicorn agent_factory_server.research:create_app --factory --timeout-graceful-shutdown 35
```

Host, TLS, and authentication configuration are covered by [local startup](WINDOWS_LOCAL_START.md). Reusable core `create_app` callers choose their own `shutdown_guard`. The deployment factories install the shared policy.

## Windows connection-reset failure

Native Windows acceptance on Python 3.12.11 observed `WinError 10054` inside `asyncio.proactor_events._call_connection_lost`. The exception interrupted transport cleanup before the server connection count decreased. Uvicorn then waited in `Server.wait_closed()` while its HTTP connection and request-task sets were already empty.

The network deadline prevents that wait from blocking application cleanup indefinitely. It does not patch CPython, change the event-loop implementation, or prove that the affected sockets closed gracefully. Native task stop, transport shutdown, and application process exit remain separate observations.

## Recovery evidence

Process exit does not rewrite original-operation records. Recovery still inspects the original task, run, and effect. Unknown operations retain their existing uncertainty until reconciliation establishes an outcome.

The shutdown regression uses real Uvicorn with synthetic local behavior. A separate Windows real-model research acceptance confirmed original-task stop, application lifespan completion, and temporary-resource cleanup with the transport deadline configured. The observed connection-reset errors remained; bounded shutdown does not repair that runtime defect. PostgreSQL recovery, real-model research, and target-host process stopping are separate checks. [Development checks](DEVELOPMENT_CHECKS.md) lists their entrypoints. Passing a no-model idle shutdown does not certify shutdown after a real research task.

## Run the shutdown regression

From the repository root with the locked dependencies installed:

```sh
uv run --frozen python -m unittest discover -s platform/tests -p test_shutdown.py -v
```

The same command works in PowerShell. It runs three tests, including twelve real
Uvicorn subprocess cases: normal cleanup, cleanup failure, blocked application
cleanup, and blocked network close for each official launcher implementation.
The fixtures shorten the blocked waits and assert the production 35-second
settings. They do not reproduce Windows TLS/RST or start a database or model.
