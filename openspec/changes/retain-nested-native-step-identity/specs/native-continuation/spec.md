## ADDED Requirements

### Requirement: Nested original continuation retains executor identity
The system SHALL accept a registered declaration step ID retained by the original native executor when a persisted original requirement identifies that exact executor run and registered step, even if the requirement step ID is a native runtime UUID.

#### Scenario: Nested external wait resumes the original executor
- **WHEN** the original response and persisted executor use the registered declaration ID while their requirement uses a runtime UUID
- **THEN** the exact requirement name, agent, executor run and original workflow/session/owner/ticket are required before continuation
- **AND** the actual original executor step ID remains unchanged

#### Scenario: A foreign continuation cannot borrow the representation difference
- **WHEN** the response substitutes an unregistered step ID or the requirement refers to another name, agent or executor run
- **THEN** validation rejects the continuation without another model call or child dispatch
