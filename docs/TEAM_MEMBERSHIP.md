# Team membership and account migration

An existing, enabled Agno directory account is a member. Members can use supported components and workflows, connect resources, and publish or manage their own content. New components do not require additional resource grants. Disabling the account revokes subsequent requests made with existing browser sessions or member JWTs; execution boundaries also recheck membership.

Account administrators additionally manage accounts through `/api/factory/accounts`: list and create accounts, edit names and email addresses, enable or disable accounts, and change the `accountAdmin` flag. Administrator status preserves ordinary session, task, resource and credential ownership boundaries. The identity response's existing `role: "manager"` label means account administrator; `role: "user"` means member.

The account API accepts `GET` with `limit`/`offset`, `POST` with `id`, optional `name`, `email`, and `accountAdmin`, and `PATCH /{id}` with changed `name`, `email`, `disabled` or `accountAdmin` fields. Existing account creation returns 409. Renaming an account does not enable it. Login identity verification remains explicit; external subject mapping applies to the OIDC path. For a few local function-check accounts, use the [controlled new-member command](../README.md#start-with-configured-authentication), which rejects existing owners and grants no administrator role.

## Existing installations

Startup preserves the native directory, disabled flags, and existing role data. Existing `factory-manager` assignments continue as the account-administrator flag. A custom role that formerly granted effective global `agent_os:admin` authority is converted once to that same account flag. The native directory metadata marker `factory_account_admin_v1` records completion for each account while retaining unrelated metadata.

After migration, removing the account flag remains effective across restart even if historical resource policies remain stored. Historical resource grants no longer decide ordinary member capabilities. Members are explicitly provisioned through the account API or trusted tooling; the local password command creates only new ordinary members and never attaches credentials to existing identities. Startup does not create demo identities, restore removed administrator assignments or enable disabled accounts.

Native global administration, cross-user durable queue operations and native service-account administration are closed to both member roles. Previously issued Agno PATs are rejected at the member-token ingress boundary, including WebSocket authentication frames, because that native credential plane bypasses the owner's current directory status. Local password and OIDC browser login use the same session-to-native identity bridge and owner isolation; a directly supplied internal JWT is not a public login method. Native workflow WebSocket behavior remains unchanged.

Agno's native `config:write` scope includes database schema upgrade and downgrade endpoints. Both member roles are denied that installation operation; ordinary `config:read` discovery remains available. Schema migration remains a deployment operation.

## Credential custody and backup

The default local vault persists its 32-byte master key at `<workspace>/runtime/credential-vault.key`. First creation publishes a complete file atomically; subsequent startup reuses it. An invalid existing key fails explicitly instead of replacing it. Organizations can supply their own vault through the existing vault factory configuration.

Back up the database and the corresponding key file together, preserving the key's access restrictions. Restoring the database with a newly generated key cannot decrypt the existing credential records. Keep the key outside exported catalogs and shared resource descriptions; the database stores credential ciphertext and non-secret operation metadata. Resource use resolves the exact credential owner, endpoint and revision independently of the invoking member.

## Verification

`test_auth_contract.py` exercises native SQLite identity, workflow execution, component creation, private session isolation, account administration, account disablement, historical PAT refusal and migration/demotion across restart. `test_team_membership_postgres.py` covers native PostgreSQL components/workflows, an active durable queue, the global-management boundaries and administrator migration. `test_local_credentials.py` checks key reuse, concurrent first creation, restart decryption, ciphertext storage and exact owner/endpoint binding with real temporary files and SQLite.
