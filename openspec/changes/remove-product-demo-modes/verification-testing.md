# Test fixture migration checkpoint (not final acceptance)

The product no longer selects demo identities, seeds or runtime adapters. These changes keep synthetic setup inside `platform/tests` / `applications/tests`; they do not introduce a renamed product mode, HTTP login substitute, production auth patch or automatic production membership.

## Fixture responsibilities

- `fixture_settings.Settings` is a test-only dataclass subclass with a fresh ephemeral native signing key and a process-local external RSA test issuer. Production Settings validation still applies, including retention bounds. Public TestClient callers use HTTPS URLs, short-lived RS256 access tokens and the real external verifier, native middleware and current-member checks.
- `fixture_auth.initialize_members` explicitly creates only disposable test members through the real directory and account-role services. Existing disabled flags and role removals are not reset. `authorize_client` configures a test client, then makes a real authenticated `/session` request; it does not install an HTTP login route.
- Non-login subprocess execution/restart/cancellation tests explicitly serve the existing `state.http_app` native internal boundary and use short-lived internal bearer tokens. This is **not public login acceptance**. Product startup has no switch for this. External fail-closed and HTTPS OIDC/browser tests remain separate requirements.
- `core_native_fixture` uses ordinary material/application drafts and publication with explicit runtime bindings. No seed bootstrap adoption or implicit legacy binding survives. Test application creation time alone is fixed to an epoch so two isolated fixture installations have identical immutable pins; actual product clocks and hash algorithms are unchanged.
- Go development binding/profile and process fixture registration code moved into test-only modules, along with the two runner contract fixtures. Their original provider protocol, billing/campaign gate and process behavior tests remain; removed product-profile switching is tested as invalid configuration. No live model credentials or paid calls were used.
- Old stored synthetic plans/materials remain explicit historical data fixtures, readable but denied new execution. Test migration never silently promotes bootstrap state. Browser identity-specific replacements are owned by the authentication reviewer, not simulated by bearer execution fixtures.

## First results and limits

1. Composition portable initial run: 14 cases, 13 passed, one obsolete `adopt_legacy_demo_plan` call errored (`/tmp/no-demo-composition-first.log`). Replaced that obsolete mode assertion with historical bytes preserved plus `APPLICATION_PIN_REQUIRED`; no execution permission was relaxed.
2. Collection first failed on removed Go queue-selector/runner imports (`/tmp/no-demo-collection-first.log`). After moving runner fixtures and asserting retired product-profile rejection, collection succeeded: 2068 discovered / 370 selected (`/tmp/no-demo-collection-second.log`). Concurrent authentication fixture edits mean this is a checkpoint count, not final coverage accounting.
3. The first daily runner overlapped another agent's authorized PG slot. It was explicitly terminated (exit 143), logged at `/tmp/no-demo-daily-python-first.log`, and is **not acceptance evidence**. MCP boolean/numeric-schema subcases failed before interruption; no final stacks were emitted. The unchanged single MCP test subsequently passed 1/1 in 1.503s (`/tmp/no-demo-mcp-schema-first.log`). This does not explain or close the interrupted historical failure.
4. The authorized exclusive daily run executed 370 cases: 369 passed, one failed, zero errors/skips, 57.230s (`/tmp/no-demo-daily-python-exclusive.log`). The sole failure was a fixed old bootstrap application hash in the v1 wire oracle. Normal publication changes origin, explicit material bindings and creation timestamp. Fixture application time is now fixed; the new member-authored fixture golden is `1ae47b187fa677e869316ab5a6801f1e35b738cc9ac91753c0d1f8d91eb1e949`. The v1 envelope/digest/roundtrip assertions and a fixed golden remain. All 16 remote-v2 targeted checks then passed, zero skips, 2.880s (`/tmp/no-demo-remote-v2-fixed.log`).
5. Ruff passes across both test trees. Full-only portable checks, migrated PG/native-process cases and final combined acceptance remain **NOT RUN/PENDING** at this initial fixture commit. No full-suite pass, real IdP or paid-provider compatibility is claimed.

## Removed or renamed test IDs and reasons

The following is an explicit AST method-name comparison against `9454000`, captured during the shared-tree migration. Renames are replacements, not lost coverage. The old fixed-persona/mock-IdP/launcher behavior is deliberately removed; its relevant external verifier, nonce/PKCE, browser session and CSRF coverage belongs to the retained production BrowserAuth/OIDC modules and new fail-closed tests. Final exact discovery counts must be checked after all writers freeze.

### platform/tests/test_applications_composition.py

- Removed/renamed: `ApplicationCompositionTests.test_legacy_pin_is_explicit_exact_demo_only_and_never_implicitly_adopted`.
- Replacement: `ApplicationCompositionTests.test_legacy_plan_is_readable_but_never_adopted_for_execution`.

### platform/tests/test_auth_contract.py

- Removed/renamed: `NativeAuthContractTests.test_cookie_mutations_reject_explicit_cross_origin`.
- Removed/renamed: `NativeAuthContractTests.test_demo_token_matches_cookie_lifetime`.
- Removed/renamed: `NativeAuthContractTests.test_native_verification_and_cookie_bridge`.
- Removed/renamed: `NativeAuthContractTests.test_production_has_no_demo_setup_or_cookie_identity`.
- Replacement: `NativeAuthContractTests.test_configured_external_oidc_accepts_only_external_identity`.
- Replacement: `NativeAuthContractTests.test_internal_bridge_token_has_short_default_lifetime`.
- Replacement: `NativeAuthContractTests.test_native_internal_verification_does_not_promote_legacy_cookies`.
- Replacement: `NativeAuthContractTests.test_unconfigured_public_boundary_rejects_valid_internal_tokens_and_old_cookies`.

### platform/tests/test_development_identity.py

- Removed/renamed: `DevelopmentLauncherTests.test_launcher_builds_only_explicit_demo_settings_without_starting_server`.
- Removed/renamed: `DevelopmentLauncherTests.test_launcher_rejects_missing_or_external_inputs_and_sanitizes_failures`.
- Removed/renamed: `DevelopmentLauncherTests.test_settings_rejects_mock_production_unknown_origin_and_implicit_enablement`.
- Removed/renamed: `DevelopmentLauncherTests.test_temporary_tls_is_private_loopback_only_and_removed_after_error`.
- Removed/renamed: `MockIdentityTests.test_cancel_and_expiry_issue_no_identity`.
- Removed/renamed: `MockIdentityTests.test_existing_sql_session_lifecycle_logout_and_current_owner_recheck`.
- Removed/renamed: `MockIdentityTests.test_expired_code_and_wrong_nonce_use_original_verifier`.
- Removed/renamed: `MockIdentityTests.test_https_host_not_forwarded_headers_define_transport`.
- Removed/renamed: `MockIdentityTests.test_mock_is_explicit_demo_loopback_and_ephemeral`.
- Removed/renamed: `MockIdentityTests.test_selector_origin_csrf_cookie_and_one_use_flow`.
- Removed/renamed: `MockIdentityTests.test_strict_requests_and_wrong_pkce_never_mint_an_identity`.
- Removed/renamed: `MockIdentityTests.test_two_browsers_choose_independent_personas_and_original_oidc_verifies`.
- Replacement: `RemovedDevelopmentIdentityTests.test_missing_key_and_obsolete_environment_fail_closed`.
- Replacement: `RemovedDevelopmentIdentityTests.test_removed_product_modules_are_not_importable`.
- Replacement: `RemovedDevelopmentIdentityTests.test_removed_settings_are_not_alternative_login_modes`.

### platform/tests/test_go_project_workflow.py

- Removed/renamed: `GoProjectWorkflowTests.test_deployment_queue_policy_bounds_default_go_profile`.
- Replacement: `GoProjectWorkflowTests.test_product_rejects_retired_development_profile`.

### platform/tests/test_material_governance.py

- Removed/renamed: `MaterialGovernanceTests.test_bootstrap_requires_original_seed_receipt_and_does_not_restore_withdrawn`.
- Replacement: `MaterialGovernanceTests.test_historical_bootstrap_remains_unadopted_and_cannot_execute`.

Additional real PostgreSQL replacements in `test_development_login_postgres.py`: unconfigured public boundary rejects internal tokens/old cookies; old demo database rejected before schema/identity mutation. No blanket skips were introduced. The authentication author supplies final detailed login-behavior equivalence evidence.

## Follow-up fixture boundary corrections

- Public department-publication HTTP checks use the configured external RS256 issuer; bare native team-membership HTTP/WebSocket checks retain the original internal HS256 token. They test different identity boundaries and are not interchangeable.
- The core workspace browser fixture now runs only the real BrowserAuth flow against its disposable loopback HTTPS OIDC issuer. Desktop/mobile selection controls viewport only. Original login, navigation, empty state, deep link, refresh and logout/relogin assertions remain; this synthetic issuer does not prove deployment identity integration.
- Storage governance fixtures use the production-valid 60-second retention grace. Positive purge cases advance only the service's clock after establishing the plan; permission denial and not-yet-elapsed rejection remain direct checks. No product retention validation or timeout was relaxed. These storage cases require their own PostgreSQL run.

## First complete portable discovery and corrections

`env -u FACTORY_TEST_DATABASE_URL timeout 600 python scripts/check_python.py` completed with exit 1: 2069 cases in 175.686s, 7 failure records, 12 error records, 561 skips. Some records are subtests, so subtracting failure/error records from case count does not give an accurate passed-case count. Original evidence: `/tmp/no-demo-full-portable-first.log`.

Corrections are confined to fixture contracts:

- Two snapshot tests assumed a globally empty command ledger. Ordinary fixture draft/publication now legitimately creates six commands. Capture the initial count and assert unchanged / exactly one new import command; no arbitrary replacement constant.
- The historical unpinned-plan denial includes an explanatory message. Assert the precise current error, preserving the denial and unchanged original body.
- Four actual-runtime failures shared hand-built materials lacking `runtimeBinding`. The helper now includes the same explicit fixture binding before hashing; original native tool/HITL/budget/UNKNOWN assertions remain.
- Four lifecycle errors came from a fake TestClient constructor not accepting the now-explicit HTTPS `base_url`. The fake checks that exact URL; lifecycle ordering and engine-disposal assertions remain.
- The removed `publish_demo_compatibility` method is asserted absent; ordinary production publication remains exercised.
- Old product-reserved fixture material names are no longer special. Catalog/material tests retain rejection of unknown `arbitrary_shell` and `checksum` with `fixture:operate` permission, then assert another author receives 403, the actual owner can create version 2, and version 1's complete inspected body/governance remains unchanged. This does not loosen reserved request fields or runtime tool authority.

Additional ID mapping:

- `CatalogContractTests.test_tool_kind_and_registered_binding_cannot_be_replaced` → `test_tool_contract_and_owner_pins_cannot_be_replaced`.
- `MaterialGovernanceTests.test_registered_tool_binding_and_reserved_identity_cannot_expand` → `test_registered_tool_permissions_and_material_owner_cannot_expand`.
- Removed `CoreGoQueueBoundaryTests.test_direct_core_go_rejects_queue_amplification_before_database_or_workspace`: it exclusively asserted the deleted product Go-profile queue override. `GoProjectWorkflowTests.test_product_rejects_retired_development_profile` covers removed configuration; retained `GoLiveRunnerTests.test_member_settings_reach_local_app_boundary_without_provider_access` checks the test-only campaign explicitly passes `queue_max_attempts=1` without provider/credential access. No ordinary queue/retry behavior was deleted.

The first full run is still a failure; targeted corrections and final combined validation must be recorded separately.
