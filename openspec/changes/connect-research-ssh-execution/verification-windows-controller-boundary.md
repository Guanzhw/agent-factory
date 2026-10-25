# Native Windows controller capability boundary

Spec 27ce70f precedes this implementation. One known-platform guard in SSHAgents.acquire rejects win32 before callbacks, vault.resolve, decoding or subprocess creation. Existing verification codes retain the specific diagnostic. Capabilities keep configuration-management enabled and report controllerDiagnostic; list/revoke, bindings and stored data remain unchanged. UI reuses its existing error presentation; no platform framework, Windows agent service or alternate credential custody was added.

Two new portable Python cases passed first run: 2/2, 0.436s, no skips (`/tmp/af-windows-controller-boundary-first.log`). They verify zero guard/secret decoding/process launch, recognized verification failure, capability reason, retained listing and actual revocation. The tests simulate win32 on Linux; they do not establish Windows SSH execution.

Targeted UI first run: 20 passed, one new test failed because its selector used a nonexistent label. The existing button is 撤销授权. Corrected the test to assert that exact button remains enabled; no product assertion or behavior was relaxed. First log `/tmp/af-windows-controller-ui-first.log`; final 21/21 passed in 2.37s (`/tmp/af-windows-controller-ui-final.log`).

Required full frontend command `NODE_OPTIONS=--no-experimental-webstorage timeout 180 npm run check` passed, exit 0: lint/typecheck, 53 files / 490 tests, build. Log `/tmp/af-windows-controller-npm-check.log`. Production and full npm audits against https://registry.npmjs.org both returned zero vulnerabilities, exit 0 (`/tmp/af-windows-controller-audit-prod.log`, `...-full.log`). Python Ruff and git diff --check passed.

No PG, real SSH, new credentials, network/security configuration, deployment or CI cancellation occurred. The Linux helper guard is a separate remote-side boundary. Native Windows controller execution remains unimplemented; null diagnostics do not certify untested Darwin or other platforms.
