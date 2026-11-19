# Team membership and account migration

An existing, enabled Agno directory account is a member. Members can use supported components and workflows, connect resources, and publish or manage their own content. New components do not require additional resource grants. Disabling the account revokes subsequent requests made with existing browser sessions; execution boundaries also recheck membership.

Account administrators additionally manage accounts through `/api/factory/accounts`: list and create accounts, edit names and email addresses, enable or disable accounts, and change the `accountAdmin` flag. Administrator status preserves ordinary session, task, resource and credential ownership boundaries. The identity response's existing `role: "manager"` label means account administrator; `role: "user"` means member.

Members sign in over HTTPS using their local ID and password. Creating a member requires an initial password. Administrators can set or change a password for an existing member. The maintenance command `uv run agent-factory-local-user <new-id>` creates an ordinary member. [Local startup](WINDOWS_LOCAL_START.md)

## Existing installations

Startup preserves the native directory, disabled flags, and existing role data. Existing `factory-manager` assignments continue as the account-administrator flag. A custom role that formerly granted effective global `agent_os:admin` authority is converted once to that same account flag. The native directory metadata marker `factory_account_admin_v1` records completion for each account while retaining unrelated metadata.

After upgrading an installation that used an external identity provider, set a local password on the **existing member ID** in account settings. If the only administrator has no local password yet, point `FACTORY_DATABASE_URL` at the original database on the service host and run the following command. Replace `MEMBER_ID` with the original administrator's ID.

```sh
uv run agent-factory-local-user --reset MEMBER_ID
```

Enter the password at the prompt. The member retains their owned data, role and enabled or disabled status. Changing the password revokes that member's existing browser sessions. An enabled member can immediately sign in with the new password.

Agno's native `config:write` scope includes database schema upgrade and downgrade endpoints. Both member roles are denied that installation operation; ordinary `config:read` discovery remains available. Schema migration remains a deployment operation.

## Credential custody and backup

The default local vault persists its 32-byte master key at `<workspace>/runtime/credential-vault.key`. First creation publishes a complete file atomically; subsequent startup reuses it. An invalid existing key fails explicitly instead of replacing it. Organizations can supply their own vault through the existing vault factory configuration.

Back up the database and the corresponding key file together, preserving the key's access restrictions. Restoring the database with a newly generated key cannot decrypt the existing credential records. Keep the key outside exported catalogs and shared resource descriptions; the database stores credential ciphertext and non-secret operation metadata. Resource use resolves the exact credential owner, endpoint and revision independently of the invoking member.

## Verification

The browser journey creates a second local member, signs in with the initial password, resets the password and verifies the result. [Account and model diagnostics test](../tests/test_audit_journey.py)
