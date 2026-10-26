## Why
The first Windows experiment rejected a plaintext delete-on-close private-key carrier. Native Windows remains the selected controller target. Test a different carrier: a per-call random-passphrase-encrypted OpenSSH key and a fixed ASKPASS executable, with the passphrase confined to memory and an authenticated local pipe.

## What Changes
- Add a test-only installed console entry point and bounded Windows mechanism probe, after independent design review.
- Stage A validates real system key loading, precise process/pipe identity and crash behavior. Stage B validates actual system ssh public-key authentication against an available controlled loopback server.
- Preserve the previous candidate's rejected evidence. Do not integrate a product Windows credential path before the mechanism is demonstrated.

## Impact
Test scripts/fixtures and a separately integrated CI job only. No new dependencies, global services, users, vault grants, real keys, WSL or remote GPU. Product runtime remains unchanged.
