## ADDED Requirements
### Requirement: Actual bounded Windows public-key authentication
The probe SHALL authenticate the existing runner account using actual installed system ssh.exe and foreground loopback sshd without changing system services, accounts or privileges.

#### Scenario: Correct pin and encrypted identity
- **WHEN** both installed executables and existing rights permit the private fixture
- **THEN** the exact pinned client authenticates with one authorized passphrase release and executes the fixed nonce command
- **AND** all owned processes and temporary files are cleaned within the fixed bound

#### Scenario: Incorrect host pin
- **WHEN** the client pins a different synthetic host key
- **THEN** authentication fails, no passphrase is released and no nonce command output is produced

#### Scenario: Repeated broker request
- **WHEN** the actual authenticated helper asks for another release on the same connection
- **THEN** the broker refuses without extending the deadline or disclosing another passphrase

#### Scenario: Missing existing server prerequisite
- **WHEN** system sshd or existing account privileges cannot support the private foreground fixture
- **THEN** report BLOCKED only for an explicitly identified prerequisite; unknown fixture/configuration errors remain INCOMPLETE and observed authentication failures remain FAIL
- **AND** do not install services, create accounts, modify privileges or claim authentication success
