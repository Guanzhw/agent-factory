# Private original-result verification

Spec first: 83ddd18, task placement correction 915a670 (strict valid), UTF-8 evidence distinction d39c10d (strict valid). Shared target identity contract ba88bd6 is reused, not duplicated.

Command: `PYTHONPATH=platform:platform/tests:deployment:applications:applications/tests timeout 120 /workspace/agent-factory-research-next/.venv/bin/python -m unittest test_application_ssh_results test_ssh_operation_waits test_application_tool_results`

First run: 26 tests, 25 passed, one fixture failure: the test placed the UTF-8 multibyte character after the preview boundary rather than across it. Exact prefix-length arithmetic corrected the fixture; product behavior and limits unchanged. Original log `/tmp/af-ssh-private-observation-first.log` retained.

Final expanded run: **29 passed, zero skipped, 0.439s**, exit 0, `/tmp/af-ssh-private-observation-utf8-final.log`. Ruff and git diff --check passed. Tests cover original delegated child after failure/cancel, absent/unbound versus reserved/no-run child, original identity mismatch, private archived negative outcomes, exact archive identity, 16KiB byte truncation and split UTF-8, invalid UTF-8 beyond the preview, and same native Agent wait/run continuation with original output as tool-result data. Unknown original command replay performs no fresh result read or model call. Original CLI result tests remain unchanged and pass.

These are portable contract tests with synthetic ports/HTTP and actual Agno Agent pause/continuation. They are not PG/nativequeue, SSH-server, real model, GPU, or deployed-target acceptance. No remote execution, new credentials or publication was performed. Root owns main wiring and broader integration checks.
