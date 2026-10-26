# Remove demo modes: deployment update

The product has no persona login, demo cookie, built-in mock OIDC, automatic synthetic seeds or downloadable runnable prototype. `FACTORY_MODE=demo` and retired development options fail closed. No compatibility switch re-enables them. Test-only local identity/model fixtures remain solely for deterministic acceptance.

## Existing local installation

1. Keep the old service stopped. Do not restart old `scripts/dev.py`, development-login or prototype commands.
2. Preserve the existing database, workspace and paired vault key; do not delete or relabel a demo database. Updating code does not authorize data deletion or migration of synthetic users into real identities.
3. Update to the exact reviewed merge, install frozen dependencies, and rebuild the selected frontend (`npm run build` for core; `npm run build:research` when explicitly installing Research). Replace the old build output rather than serving old assets alongside it.
4. Configure the existing database and signing key through the operator's secure configuration, then explicitly choose [local password or OIDC login](../README.md#start-with-configured-authentication). No key, account or identity provider is automatically created for login. Missing configuration remains a closed state, not a reason to restore demo.
5. Local function checks can use newly created ordinary members and HTTPS password login. The separate external OIDC path still needs trusted deployment composition: pinned HTTPS public client, S256 PKCE, exact callback, public verification keys and existing-member mappings. See [browser authentication](BROWSER_AUTH_PROCESS_ENFORCEMENT.md) and [external bearer identity](RESOURCE_IDENTITY_INTEGRATION.md); no confidential-client secret or discovery is invented.
6. Verify sign-in, exact deep-link return, refresh, logout/relogin and current member permissions for the selected method. Local password or test OIDC results do not certify the organization provider; its external acceptance still requires the actual service.

## Data boundary

This change performs no deletion or promotion. The separate local deployment reported three synthetic users and one acceptance draft/receipt, with zero tasks/models/connections/credentials/experiments/deliveries; that report is not a new cloud inventory or deletion authorization. Keep the local PostgreSQL data until an exact cleanup plan is separately confirmed. This cloud task does not access the user's machine.

## Authentication and network limits

A webpage reverse proxy must preserve the configured HTTPS public callback and secure-cookie/Origin constraints. It is not an SSH or GPU outbound proxy. Production identity and actual target deployment acceptance remain blocked until their real endpoints and existing secure configuration are supplied. Never put signing keys, private SSH keys or passwords in a PR, diagnostic report or chat message.
