## 1. Design and prerequisites
- [x] 1.1 Independently review lease accounting/fresh authorization, fixed helper, explicit scope and packaging seams.
- [x] 1.2 Close Stage B's actual authentication failure with preserved first evidence; do not adopt an unvalidated carrier path.

## 2. Narrow production implementation
- [x] 2.1 Add the Windows lease/carrier and minimal owned-process contract, keeping Linux behavior unchanged.
- [x] 2.2 Integrate explicit pinned SSH scope at both consumers and the installed core helper/dependencies.
- [x] 2.3 Independently review exact full diff and fix unnecessary abstraction or unsafe shortcuts.

## 3. Verification
- [ ] 3.1 Run portable scope/guard/limit/failure tests and actual Windows installed-core SSH checks.
- [x] 3.2 Verify Linux checks and standalone wheel behavior.
- [ ] 3.3 Run controlled Windows-to-Linux original submit/recovery/cancel. BLOCKED: no authorized Linux target/access supplied; the Windows-loopback peer does not satisfy this gate.


- [ ] 3.4 Preserve first installed-core failure and independently review fixed safe phase/code instrumentation; run one authorized instrumented acceptance to distinguish acquisition, helper identity/handshake and command failure without changing the oracle.

Implementation/review checks above are complete through f8d59fb; exact fast CI40244764642 passed, including the independent Linux core check. Windows portable checks passed 60/60, but the first installed-product run40244764651 failed at PRODUCTION_CONSUMERS. Thus 3.1 remains open; neither source review nor a successful wheel install closes it. Historical failures remain in verification documents.

- [ ] 3.5 Independently review invocation-local fixed helper filename design against the observed NOT_FOUND/error-2 failure; implement only after review.
- [ ] 3.6 Verify byte-preserving copy and identity/cleanup wiring, then run the unchanged actual installed Windows acceptance with Unicode-and-space parents; retain all failed reports and keep the Windows-to-Linux gate separate.
