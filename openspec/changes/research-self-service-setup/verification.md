# Verification

- Spec review: independent reviewer accepted base301811b..4c191fc.
- First portable run: 5 tests, 4 pass/1 fail (1.189s). `test_partial_publication_rolls_back_and_same_command_can_recover` expected material/application/setup/receipt counts `(1,0,1,1)` but observed `(9,0,1,1)` after injected application publication failure. Existing `MaterialGovernance._write` starts a separate transaction rather than borrowing `store._connection`; generated material versions escaped the outer rollback. Core integration owner notified; rollback assertion retained.
- No live model, GPU or remote probes. Synthetic local adapter and personal localhost model configuration test metadata/authority only.
- Browser integration pending; portable/PG metadata evidence does not replace the empty-catalog browser journey or actual execution.
- Initial Pyright invocation had no local `.venv`, resulting in seven missing-import diagnostics. After pointing this worktree at the existing installed interpreter, the same focused check reported 0 errors/0 warnings. Ruff passed. New revoked/foreign-owner regression passed (1 test, 0.116s); transaction-dependent cases remain blocked on the core fix.

## Final focused checks after the core transaction fix

Core commits 5c076b9/74f83f9 were integrated as 360e724/1437c4a. The shared-transaction fix belongs to the core integration owner, not an application override. Original rollback assertions were retained.

- `PYTHONPATH=.:platform:platform/tests timeout 60 .venv/bin/python -m unittest discover -s applications/tests -p test_research_setup.py -v`: exit 0, **7 passed, 0 skipped**, 0.933s.
- With the coordinator-provided loopback PostgreSQL fixture URL, `PYTHONPATH=.:platform:platform/tests timeout 120 .venv/bin/python -m unittest discover -s applications/tests -p test_research_setup_postgres.py -v`: exit 0, **3 passed, 0 skipped**, 6.085s. Each test creates and drops its own generated database. Existing PostgreSQL server retained.
- PG covers same-request concurrent publication, complete rollback after a late application publication failure, persisted original receipt after constructing a new service, and two owners preflighting the same immutable application/material hashes with separate personal model bindings. It does **not** claim a new OS process restart or actual model/GPU execution.
- Independent code review accepted setup changes 4c191fc..21912ac apart from the then-unfixed core transaction blocker. The additional PG tests and integrated fix await final exact-head review.
- `ruff check applications/research/setup.py applications/tests/test_research_setup*.py`: exit 0. `timeout 60 .venv/bin/pyright applications/research/setup.py`: exit 0, 0 errors/warnings. `git diff --check`: exit 0.

Current deployment still requires explicit suitable environment registration and a real experiment tool publication. The existing bounded-process profile requires targetRef configuration; this setup slice intentionally does not invent a target or accept raw JSON to fill it. A missing environment remains a visible blocker rather than a seeded test resource.

## Optional deployment integration (2026-10-25)

The research installer now creates `ResearchSetup` with the actual installed Workflow's `tool_registrations`, existing connection/model services, and the existing authenticated HTTP application. No startup publication, second lifespan or task dispatch was added. The current flat component has four governed functions plus the native wait tool; setup follows those actual registrations instead of obsolete five-function or hard-coded fingerprints.

- Real portable HTTP candidates → owner draft → explicit publish → project agreement/confirmation preserves the exact published applicationRef and owner's connectionRefs: 1 passed in 0.387 s, exit 0. The earlier combined invocation executed 15 cases because an imported TestCase was discovered twice (8 distinct cases); the import is now a module reference so the seven service cases are not duplicated in discovery. No failed case was masked.
- Actual `agent_factory_server.research.create_app` and isolated PostgreSQL: HTTP setup publishes the current flat Workflow pin and experiment definition, with zero native tasks and zero model calls: 1 passed in 6.400 s, exit 0. Worker, scheduler, owned root locks and isolated database were cleaned up.
- Ruff and correctly scoped, bounded Pyright passed (0 errors/warnings). Integration OpenSpec strict validation passed.

Local evidence: `/tmp/research-native-workflow-evidence/setup-http-portable-first.log` and `setup-installed-pg-first.log`. Fixtures use synthetic model connection metadata and a local test environment/tool adapter; no provider endpoint was invoked, no credential created, no GPU or paid resource used. Existing bounded-process capabilities still require explicit targetRef/operator configuration; this integration does not invent a target or claim real environment execution. Full browser usability and production identities remain separate integration acceptance.

## CI discovery import repair

Exact first fast CI 40204034535 failed during collection in both Python and PG lanes: setup tests imported `applications.research`, which resolved to the core `applications.py` under the real runner import roots. Tests now use the declared `research` package. The first local partial correction still missed the PostgreSQL test import and failed; after correcting both files, the actual `scripts/check_fast.py --suite python --collect-only` completed with `selectionValid=true`, 1992 discovered cases, 370 selected, `executed=false`. This is collection evidence, not execution. Earlier complete portable backend selection remains 26 passed/zero skips. Failure logs: `/tmp/research-native-first-fast-failed.log`, `/tmp/research-native-ci-collection-fixed.log`; final collection `/tmp/research-native-ci-collection-complete.log`. No product code or assertions changed.
