# Remove demo modes: deployment update

The product has no persona login, demo cookie, built-in mock OIDC, automatic synthetic seeds or downloadable runnable prototype. `FACTORY_MODE=demo` and retired development options fail closed. No compatibility switch re-enables them. Test-only local identity/model fixtures remain solely for deterministic acceptance.

## Existing local installation

1. Keep the old service stopped. Do not restart old `scripts/dev.py`, development-login or prototype commands.
2. Preserve the existing database, workspace and paired vault key; do not delete or relabel a demo database. Updating code does not authorize data deletion or migration of synthetic users into real identities.
3. Update to the exact reviewed merge, install frozen dependencies, and rebuild the selected frontend (`npm run build` for core; `npm run build:research` when explicitly installing Research). Replace the old build output rather than serving old assets alongside it.
4. Configure an existing production database, signing key and real identity through the operator's existing secure configuration. No key, account grant or identity provider is automatically created for login. Missing configuration is an expected closed state, not a reason to restore demo.
5. Register the actual external identity in trusted deployment composition. Browser OIDC currently supports a pinned HTTPS public client with S256 PKCE, exact callback, public verification keys and existing-member mappings. See [browser authentication](BROWSER_AUTH_PROCESS_ENFORCEMENT.md) and [external bearer identity](RESOURCE_IDENTITY_INTEGRATION.md). Confidential-client secrets/discovery are not silently invented.
6. Verify real sign-in, exact deep-link return, refresh, logout/relogin and current member permissions only after that external service is configured. Local test OIDC evidence does not certify your organization provider.

## Data boundary

This change performs no deletion or promotion. The separate local deployment reported three synthetic users and one acceptance draft/receipt, with zero tasks/models/connections/credentials/experiments/deliveries; that report is not a new cloud inventory or deletion authorization. Keep the local PostgreSQL data until an exact cleanup plan is separately confirmed. This cloud task does not access the user's machine.

## Authentication and network limits

A webpage reverse proxy must preserve the configured HTTPS public callback and secure-cookie/Origin constraints. It is not an SSH or GPU outbound proxy. Production identity and actual target deployment acceptance remain blocked until their real endpoints and existing secure configuration are supplied. Never put signing keys, private SSH keys or passwords in a PR, diagnostic report or chat message.
