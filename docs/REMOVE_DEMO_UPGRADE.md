# Remove demo modes: deployment update

The following is the historical rollout record. Current startup and local account creation use the configured PostgreSQL database directly. Older databases can keep their original mode marker. New databases have no mode table. See the [current setup instructions](../README.md).

The product has no persona login, demo cookie, built-in mock OIDC, automatic synthetic seeds or downloadable runnable prototype. `FACTORY_MODE=demo` and retired development options fail closed. No compatibility switch re-enables them. Test-only local identity/model fixtures remain solely for deterministic acceptance.

## Existing local installation

1. Keep the old service stopped. Do not restart old `scripts/dev.py`, development-login or prototype commands.
2. Preserve the existing database, workspace and paired vault key; do not delete or relabel a demo database. Updating code does not authorize data deletion or migration of synthetic users into real identities.
3. Install the frozen dependencies and rebuild the frontend with `npm ci` and `npm run build`.
4. Start with the original database, workspace and signing key. Set `FACTORY_LOCAL_LOGIN_ORIGIN` to the HTTPS address the team uses. [Deployment instructions](WINDOWS_LOCAL_START.md)
5. Set a local password on each existing member ID that previously used an external provider. If the administrator needs a password to sign in, run `uv run agent-factory-local-user --reset MEMBER_ID` on the service host with the original database configuration. [Account migration](TEAM_MEMBERSHIP.md)
6. Verify sign-in, return to the original deep link, refresh, logout and the member's access to their existing work.

## Data boundary

This change performs no deletion or promotion. The separate local deployment reported three synthetic users and one acceptance draft/receipt, with zero tasks/models/connections/credentials/experiments/deliveries; that report is not a new cloud inventory or deletion authorization. Keep the local PostgreSQL data until an exact cleanup plan is separately confirmed. This cloud task does not access the user's machine.

## Authentication and network limits

A webpage reverse proxy must preserve the configured HTTPS public callback and secure-cookie/Origin constraints. It is not an SSH or GPU outbound proxy. Production identity and actual target deployment acceptance remain blocked until their real endpoints and existing secure configuration are supplied. Never put signing keys, private SSH keys or passwords in a PR, diagnostic report or chat message.
