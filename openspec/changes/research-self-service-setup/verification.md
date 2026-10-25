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
