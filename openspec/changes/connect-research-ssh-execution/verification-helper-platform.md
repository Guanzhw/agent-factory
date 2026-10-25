# Linux-only helper platform boundary

The final full Windows static check exposed 14 Linux-only os/fcntl symbol errors. Spec 2cf6e69 precedes the fix: explicit Linux guards in handle/directory/read_file reject unsupported execution before parsing or filesystem access. Linux descriptor flags and flock remain unchanged; no type ignores, Any escapes or zero-value fallbacks.

First targeted Linux run: `PYTHONPATH=platform:platform/tests timeout 60 /workspace/agent-factory-core-only/.venv/bin/python -m unittest test_ssh_process_helper` — 12/12 passed, zero skipped, 0.045s; `/tmp/af-ssh-helper-platform-first.log`. The portable negative case patches win32/darwin, calls all three entrypoints and asserts no os.open or request parsing. The Linux filesystem class is explicitly Linux-only on other hosts.

Both `pyright --project .ssh-pyright.json --pythonplatform Windows` and `--pythonplatform Linux`, each bounded by timeout60, finished with 0 errors, 0 warnings. Scope: platform/agent_factory, deployment/agent_factory_server and applications/research; Python3.12/basic using existing core-only venv. Logs `/tmp/af-ssh-helper-windows-pyright.log` and `/tmp/af-ssh-helper-linux-pyright.log`. Ruff and git diff --check passed.

These are local Linux execution plus cross-platform static simulation; not an actual Windows runtime run or replacement for exact-head CI. No PG, remote SSH, provider, GPU or deployment execution was performed. Existing CLI error envelope is unchanged.
