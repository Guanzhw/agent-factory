## ADDED Requirements
### Requirement: Isolated Windows key lifetime experiment
The probe SHALL use only synthetic keys and the installed system OpenSSH key loader, with a creation-time protected current-user DACL and a non-inheritable delete-on-close keeper handle. It SHALL NOT modify product behavior, system services, security configuration, or credentials.

#### Scenario: Key loader compatibility
- **WHEN** the actual system ssh-keygen reads the protected synthetic key while the keeper remains open
- **THEN** the probe records whether its public output matches the original in-memory public key
- **AND** a loader rejection is preserved without weakening the file flags or ACL

#### Scenario: Normal and forced process exit
- **WHEN** the keeper closes normally or is terminated through TerminateProcess
- **THEN** the probe checks key absence after process exit before removing its owned directories
- **AND** reports cleanup failure as candidate rejection, not successful crash safety

#### Scenario: Safe bounded output
- **WHEN** the experiment finishes or encounters a prerequisite/framework failure
- **THEN** it emits only structured non-secret outcomes and versions with a bounded runtime
- **AND** distinguishes completed candidate rejection from an incomplete experiment
