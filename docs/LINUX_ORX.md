# Pinned Linux ORX toy profile

The Linux profile executes the same fixed upstream ORX 0.2.13 source and the
same four original sealed toy evaluator files as the Windows profile. It uses
real ORX project/experiment/run rows and commands. No provider/model, cloud job,
GitHub synchronization or arbitrary user command is enabled. This is toy
execution evidence, not real model research or production isolation acceptance.

## Build and prerequisites

Use Linux x86_64, Python 3.12, Git and an already configured local Docker daemon.
No daemon installation, host security change or extra persistent access is part
of this setup. Dependencies remain exact in `uv.lock` / `package-lock.json`;
`uv sync --frozen` and `npm ci` use official package sources.

```sh
python scripts/build_orx_linux.py --workspace /absolute/new/owned-build \
  --ca-bundle /etc/ssl/certs/ca-certificates.crt
docker pull python:3.12.14-trixie@sha256:4d1caded1f729ae443eb803f26ffde7b61e696aeaef62f099abb6dd6b14257c7
```

The build script verifies the fixed public source archive and Cargo inputs,
uses official digest-pinned Rust 1.93.1, and runs `cargo build --locked --release
--bin orx`. TLS verification stays enabled. Its receipt must match the reviewed
Linux binary hash in `ORX_BUILD_PROVENANCE.json`; a different build fails closed
and needs provenance review. The existing Windows binary pin remains separate.

## Runtime boundary and identity

Each admitted task has an immutable named container, exact ID/spec receipt and
exclusive workspace. The runtime image, binary, guardian, mounts and resource
configuration are checked before execution and stopping. The container has no
network, a read-only root filesystem, no added capabilities, all capabilities
dropped, no-new-privileges, and the operator's unprivileged UID/GID. Only its task
workspace is writable. It does not receive Docker's socket or provider secrets.

The existing bounds stay 30 seconds, 512 MiB and 25% CPU for this profile.
Linux uses a cgroup PID limit of 64 **including native threads**; Windows retains
its eight-process Job Object limit. A trusted PID 1 reaps detached children and
ends the PID namespace at the aggregate CPU allowance. Empty containers stop
after 30 seconds. A stopped guardian is not a running experiment. Positive stop
evidence requires no task processes or a stopped original container with PID 0.
Missing/replaced containers are not treated as stop evidence.

The container ID is retained for future exact cleanup/inspection. On Docker's
`vfs` storage driver, each task can consume a full image copy even after it stops.
The observed cloud host used `vfs`: accumulating disposable fixtures exhausted
its 32 GiB root filesystem. Tests now retire their generated containers only
after checking stop evidence. Production disk retention, hostile tenancy,
20-department load and the target 32-core/64-GiB or 54-core/192-GiB capacity are
not certified by these tests. The cloud test allocation is only 4 CPU / 16 GiB.

## Opt-in acceptance

Set `FACTORY_ORX_BINARY`, `FACTORY_ORX_SOURCE_ARCHIVE`,
`FACTORY_ORX_GIT_BINARY`, `FACTORY_ORX_SHA256` to the exact reviewed artifacts,
`FACTORY_ORX_LINUX_CONTAINER=1`, `AGNO_TELEMETRY=false`, and a task-owned loopback
`FACTORY_TEST_DATABASE_URL`. The native database fixture creates disposable
`af_test_*` databases; do not point this at a production service.

```sh
PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest \
  test_actual_orx_local.ActualLinuxLocalORXTests \
  test_orx_experiment_factory.ActualLinuxORXNativeFactoryTests -v
```

These Linux classes use actual Linux container/kernel evidence. Windows suites
remain independently gated and unchanged in their containment expectations.
Cold container preparation may take over 30 seconds on `vfs`; acceptance setup
waits allow this without increasing the immutable evaluator runtime budget.

`scripts/start_orx_local.py --isolated-demo` creates a separate generated
loopback database and private demo identity fixture; `--resume` requires its
exact workspace marker and database identity. A distinct native administrator
publishes the application. The reviewed scenario lives in its pinned tool
material; it cannot be injected into the closed application configuration.

`scripts/accept_orx_browser.py --fixture <private-fixture> --output <owned-output>`
uses Playwright Chromium by default (`--browser-channel msedge` remains available).
It checks separate plan review/native approval, repeated submission, lost
admission acknowledgement, actual metrics, artifact hash verification/tampering,
reload, evaluator failure, cancellation, offline recovery and mobile layout.

`scripts/accept_orx_process.py` takes the same database/toolchain arguments plus
a new `--workspace`. It kills the actual Factory HTTP/native-queue process with
SIGKILL after observing a live original run, proves detached processes survive,
restarts the exact workspace/database and cancels the original run. Its evidence
checks one native admission, one ORX run and positive stop proof. Private auth
fixtures and raw logs stay outside the repository. No test authorizes publishing
the service, enabling paid models or widening real resource access.
