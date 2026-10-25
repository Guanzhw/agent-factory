## ADDED Requirements

### Requirement: Derived publication access retains all source authority
Core SHALL bind the complete immutable original source set at publication and require current authorization to every source on all body and artifact reads. It SHALL NOT grant owner proxy access or truncate dependencies.

#### Scenario: Source withdrawal cannot be bypassed
- **WHEN** a source becomes unreadable after a derived team publication is created
- **THEN** generic body, list, artifact and original publication replay do not expose the derived body or bytes
- **AND** application download routes cannot bypass that denial

#### Scenario: Derived sources retain original dependencies
- **WHEN** an owner publishes from another derived publication
- **THEN** all original source dependencies are included and remain enforced after either source is withdrawn

#### Scenario: Owner may withdraw unavailable derived content
- **WHEN** the owner changes their publication visibility after losing source access
- **THEN** the operation succeeds with an explicit metadata-only receipt and no derived body or artifact references

#### Scenario: Read and withdrawal are ordered
- **WHEN** withdrawal commits before read admission
- **THEN** the read is denied
- **WHEN** a bounded snapshot was admitted first
- **THEN** it may finish without claiming already disclosed bytes can be revoked
