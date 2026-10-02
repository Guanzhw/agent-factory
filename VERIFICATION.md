
## Cloud Linux actual ORX continuation (2026-10-02)

- Built unchanged upstream `f336b121525d99364e2dee4fe90b2784894a54e6`
  with official Rust 1.93.1, locked Cargo inputs; real Linux `orx --version`
  reports 0.2.13. Source, binary and runtime image hashes are recorded in
  `docs/ORX_BUILD_PROVENANCE.json` and `docs/LINUX_ORX.md`.
- Actual Linux adapter: first 9 scenarios passed in the 10-case run; the last
  owning-worker hard-exit case hit the old 15-second cold-container setup wait.
  Its corrected 60-second setup wait subsequently passed. Evaluator limits
  remain unchanged. Real success/failure metrics, cancel, lost ACK, supervisor
  SIGKILL, source/command drift, revoked execution and trusted stop are covered.
- Actual Linux native Factory: 4/6 passed initially; 2 cases exhausted the old
  30-second pre-approval setup wait on the cloud Docker `vfs` driver. Both passed
  after allowing 90 seconds for cold fixture preparation. The three focused
  rechecks together passed in 117.785 seconds. These are cumulative passes for
  all 16 real Linux cases, not a claim of a fresh single all-green combined run.
- Separate actual HTTP/native queue process acceptance passed: Factory SIGKILL
  left four detached task processes alive; same database/workspace restart and
  cancellation preserved one native admission and one original ORX run, with
  Factory `canceled`, native ORX `cancelled`, and positive all-stopped evidence.
- Frontend: 52 tests, lint/typecheck/build passed; official production dependency
  audit found zero vulnerabilities. Ruff and Pyright passed.
- The startup profile was actually run and resumed. Its previously unrun
  application configuration used unsupported fields; the fixed profile retains
  scenario selection in the exact reviewed tool material and uses the existing
  closed application configuration schema.
- Browser end-to-end acceptance and the new full core regression are still in
  progress at this checkpoint. Do not infer completion from startup or focused
  tests. No Windows Job Object test was represented as Linux evidence.
- No paid provider or paid compute was used. Production isolation, real model
  research, remote real ORX and target-host departmental load remain unverified.
