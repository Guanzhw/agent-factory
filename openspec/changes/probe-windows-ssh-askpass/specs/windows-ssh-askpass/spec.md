## ADDED Requirements
### Requirement: Encrypted Windows key carrier experiment
The probe SHALL write only per-call randomly encrypted synthetic private keys and SHALL confine the passphrase to controller/helper memory and an OS-authenticated one-use local pipe.

#### Scenario: Authorized system key loader
- **WHEN** the exact system OpenSSH process invokes the fixed installed ASKPASS helper
- **THEN** a successful process/pipe identity check permits one bounded passphrase release and the real decrypted public key matches the synthetic key
- **AND** no secret is placed in argv, environment, diagnostics or a plaintext file

#### Scenario: Foreign or repeated request
- **WHEN** a different process, unexpected helper chain, confirmation prompt or second request reaches the broker
- **THEN** it receives no passphrase and cannot extend the invocation deadline

#### Scenario: Controller termination
- **WHEN** the controller is forcibly terminated
- **THEN** its broker and owned SSH/helper process group cease within the probe bound
- **AND** remaining key files, if any, are reported as encrypted residues rather than claimed absent

### Requirement: Genuine public-key client validation
The probe SHALL distinguish successful key loading from actual system ssh.exe authentication and from Linux helper execution.

#### Scenario: Controlled SSH endpoint
- **WHEN** an existing foreground loopback sshd can run without service or account changes
- **THEN** correct pinned public-key authentication succeeds and wrong host pin or extra prompts do not execute a command or disclose a passphrase
- **AND** missing prerequisites are BLOCKED rather than a simulated pass
