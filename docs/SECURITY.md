# Security and deployment assumptions

M1 exposes a local health/status API and static foundation UI on `127.0.0.1`. It has no user data, accounts, submission endpoint, research runtime or credentials. It is a development initialization build. Shared departmental deployment requires the M2–M4 controls below.

The threat model includes malicious or mistaken users, hostile uploaded instructions/retrieved papers, credential leakage, cross-user data access, runaway model/tool execution, process escape, untrusted artifacts and orphaned experiments after cancellation or crash.

Required controls include authenticated identity; role plus ownership enforcement at every data/action boundary; CSRF/origin policy for browser sessions; input limits and idempotency; secrets in trusted connection stores; capability scoping and approval revalidation; immutable policy/definition snapshots; audit logging; output bounds and path-safe artifact storage; experiment/model budget limits; durable cancel/recovery; egress controls and isolated worker processes.

Project directories and `ORX_DATA_DIR` alone are not tenant security. Production workers must isolate home, configuration, credentials, environment, processes, filesystem and network. The exact isolation platform will be selected with the reusable platform; no current scaffold claims container, VM, Windows ACL or production tenant isolation.

No model/provider credentials, GitHub tokens, user files, company data or local configuration belong in the repository. Source publication uses only new project files and synthetic examples. Dependency changes should be audited; CI has read-only repository permissions. Draft PRs are reviewed and never automatically merged. Public deployment, inviting users/granting access, and paid compute require specific authorization.
