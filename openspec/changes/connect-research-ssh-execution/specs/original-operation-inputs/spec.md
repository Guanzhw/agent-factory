## ADDED Requirements

### Requirement: Explicit original input retention precedes dispatch
Operation custody SHALL retain bounded validated inputs only when the trusted caller explicitly requests retention. It SHALL write those inputs atomically with the original intent before any adapter call. Existing callers SHALL keep their hash-only behavior. Replays SHALL not replace original inputs or dispatch again.

#### Scenario: SSH parameters survive an unknown acknowledgement
- **WHEN** the SSH caller requests original input retention and the adapter acknowledgement is unknown
- **THEN** a restarted controller reads the exact validated original inputs and their matching fingerprint
- **AND** different inputs under the original effect slot are refused before another adapter call

#### Scenario: An existing caller does not request retention
- **WHEN** an ordinary existing operation starts without retention
- **THEN** custody persists the original input fingerprint without adding the raw input payload
