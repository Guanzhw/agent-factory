## ADDED Requirements

### Requirement: Read only exact original owner CLI results
The application port SHALL require current membership, exact owner/task/run identity and persisted single-CLI ordinary executor provenance before returning original successful receipts. It SHALL NOT dispatch, resolve credentials or publish output.

#### Scenario: Historical completed owner result
- **WHEN** an active owner requests their exact original task/run with one proven CLI operation
- **THEN** the port returns only successful original personal-tool receipts and minimal immutable provenance, even if no new execution is authorized

#### Scenario: Ambiguous or unsupported provenance
- **WHEN** a plan contains multiple tools, a native component, remote handoff, or lacks a matching persisted CLI operation
- **THEN** the port rejects the request without guessing from output or current registrations

#### Scenario: Identity mismatch and unfinished effects
- **WHEN** the actor does not own the task or supplies a run ID as task ID or a mismatched run
- **THEN** no result is disclosed
- **WHEN** an effect is UNKNOWN, failed, cancelled, another run or not a personal-tool effect
- **THEN** it is not returned as successful CLI evidence
