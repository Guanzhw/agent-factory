# Verification

- Spec review: independent reviewer accepted base301811b..4c191fc.
- First portable run: 5 tests, 4 pass/1 fail (1.189s). `test_partial_publication_rolls_back_and_same_command_can_recover` expected material/application/setup/receipt counts `(1,0,1,1)` but observed `(9,0,1,1)` after injected application publication failure. Existing `MaterialGovernance._write` starts a separate transaction rather than borrowing `store._connection`; generated material versions escaped the outer rollback. Core integration owner notified; rollback assertion retained.
- No live model, GPU or remote probes. Synthetic local adapter and personal localhost model configuration test metadata/authority only.
- PostgreSQL atomicity/concurrency, browser integration and independent code review pending; portable evidence does not replace them.
- Initial Pyright invocation had no local `.venv`, resulting in seven missing-import diagnostics. After pointing this worktree at the existing installed interpreter, the same focused check reported 0 errors/0 warnings. Ruff passed. New revoked/foreign-owner regression passed (1 test, 0.116s); transaction-dependent cases remain blocked on the core fix.
