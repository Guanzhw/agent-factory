# Security and deployment assumptions

Agent Factory serves a trusted small team. Members can publish content, configure resources, and execute work without a separate administrator review. Account administrators manage accounts. The platform retains ownership, credential custody, and operational recovery boundaries.

## Identity and ownership

Browser access requires configured local password login or external OIDC login. Accounts must be enabled. Browser sessions use HTTPS cookies, revocation, and Origin/CSRF checks. There is no bundled demo account or public self-registration. [Team membership](TEAM_MEMBERSHIP.md) describes account management.

A task, session, credential, or personal resource remains owned by its member. Team sharing permits use without transferring the resource's secret. Current account and resource state apply to subsequent calls. [Resource sharing](RESOURCE_SHARING.md) describes the supported changes.

The native executor is reached through Factory's trusted bridge. Public requests cannot bypass Factory task bindings by invoking an unrestricted native run endpoint. This does not prevent members from configuring their own supported model, CLI, MCP, SSH, or remote-service connections.

## Credentials

The default credential vault stores encrypted values in PostgreSQL. Its persistent key is under `FACTORY_WORKSPACE/runtime/credential-vault.key`. Database backups and that key must remain paired. Losing the key makes stored credentials unreadable. [Operations](OPERATIONS.md) describes backup boundaries.

Resource definitions and shared content carry references, not credential values. Goals, retrieved text, and tool output do not grant new identity or resource ownership. Secrets and generated research stay outside the public source repository.

## Local code execution

With host commands enabled, the research Agent can create and run code in its configured workspace. This is not limited to the former fixed reviewed experiment program. User-selected operation budgets, output bounds, and owned process cleanup still apply.

Windows commands use Job Objects; POSIX commands use process groups. Those mechanisms support cancellation and cleanup. They do not isolate hostile code from every host file, network destination, or other operating-system resource. Workspace directories are organization, not a tenant-security boundary.

Choose a host and service account appropriate for the code you allow the team to run. The current trusted-team deployment is not a claim of hostile multi-tenant isolation.

## Uncertain operations

A missing acknowledgement remains uncertain. Recovery reads the original request and effect instead of silently starting another operation. A disconnected client, expired lease, canceled queue ticket, or application process exit does not independently prove that remote work stopped.

The lifecycle observer reconciles owned work and retained receipts. It does not provision a new environment or grant access after revocation. [Lifecycle](LIFECYCLE.md) and [shutdown](SHUTDOWN.md) explain the different stop observations.

## Deployment limits

The intended topology is one application process with PostgreSQL. Current in-process signals and scheduling coordination do not establish a multi-replica deployment. Approximate team size and machine profiles are targets, not load-test results.

Real identity-provider compatibility, persistent target-host login, remote execution, GPU allocation, backup recovery objectives, and team capacity need explicit acceptance in their actual environment. A synthetic fixture pass does not establish those outcomes.
