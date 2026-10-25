## ADDED Requirements
### Requirement: Native Windows existing SSH execution
The factory SHALL use system OpenSSH from a native Windows controller with the existing scoped vault and original remote Linux execution lifecycle, without WSL or a new controller.

#### Scenario: Fresh scoped invocation
- **WHEN** an authorized unexpired Windows lease spawns SSH
- **THEN** resolve only its original credential identity and release one per-call password to the authenticated fixed helper
- **AND** no private key plaintext or password is written to disk, argv, environment or logs

#### Scenario: Revocation or expiry
- **WHEN** the original guard or lease expiry fails before resolution, password release or an effect write
- **THEN** the corresponding fresh action is denied and owned local resources are closed without inventing a new remote operation

#### Scenario: Bounded local carriers
- **WHEN** concurrent Windows carriers reach the configured limit or the service closes
- **THEN** further carriers are rejected and every existing carrier retains bounded owned cleanup

#### Scenario: Process scope failure
- **WHEN** normal exit, cancellation, timeout or an exception ends either SSH consumer
- **THEN** the explicit process scope reaps its owned processes and removes its per-invocation files
- **AND** hard controller termination stops live secret-holding descendants while any residual ciphertext is acknowledged honestly

### Requirement: Independent packaging and original identity
The production fixed helper SHALL be available from the standalone core installation with explicit Windows dependencies, while preserving the existing Linux path.

#### Scenario: Lost remote acknowledgement
- **WHEN** a Windows SSH connection loses an original operation acknowledgement
- **THEN** the existing journal/custody path inspects the same original operation and does not submit a second launch

#### Scenario: Unavailable real integration environment
- **WHEN** no authorized Windows-to-Linux helper endpoint is available for the final real check
- **THEN** mark that gate BLOCKED rather than equating Windows loopback or synthetic protocol checks with cross-machine acceptance
