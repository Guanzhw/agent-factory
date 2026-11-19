# Local accounts for development

Run `uv run agent-factory local` to set up the local HTTPS service and its first account administrator. Sign in with that account and create a second member in account settings to test team sharing. The CLI also signs in with a local member ID and prompts for the password. [Local startup](WINDOWS_LOCAL_START.md) · [Research CLI](PERSONAL_RESEARCH_SESSIONS.md)

For an existing installation, use the original database, signing key and workspace. An administrator can set a password for an existing member. An operator can recover the original administrator with `uv run agent-factory-local-user --reset <member-id>` on the service host. [Team membership and migration](TEAM_MEMBERSHIP.md)
