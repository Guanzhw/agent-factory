## ADDED Requirements

### Requirement: Material publication participates in its owning transaction
The system SHALL preserve an existing Store transaction when creating or publishing materials, including the original idempotency receipts.

#### Scenario: A composite publication fails after material publication
- **WHEN** an outer transaction publishes a material and then fails before publishing its application
- **THEN** material and publication rows and their command receipts roll back together
- **AND** retrying the original request uses the ordinary governance path without duplicate versions

#### Scenario: Standalone publication retains its commit ownership
- **WHEN** no outer Store transaction exists
- **THEN** the ordinary material operation commits normally and releases its connection context
