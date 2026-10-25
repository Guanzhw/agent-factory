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

The first eight-module correction run completed 88 cases in 10.556s with four errors and 14 skips (`/tmp/no-demo-full-corrections-targeted.log`). All four errors were one test-helper mistake: `FIXTURE_BINDINGS` stores `(kind, adapterId)` tuples, not runtime-binding objects. Converting explicitly to the existing `{adapterId, revision, config}` contract fixed the helper. The same eight modules then completed **74 passed, 14 skipped, zero failures/errors in 14.110s**, exit 0 (`/tmp/no-demo-full-corrections-targeted-fixed.log`).

Independent review additionally found two remote public-app fixtures and the explicit `owned-user` composition fixture still using internal bearer tokens. Those now use the external test issuer; remote ASGI transports use HTTPS URLs, and the issuer explicitly maps the existing `owned-user` fixture subject. Native-only callers retain internal tokens. Their PostgreSQL runtime verification remains separate.

## Complete portable result

At code commit `9f84216`, the final necessary run after the above fixture changes completed: **2068 cases, 1507 passed, 561 skipped, zero failures/errors, 179.243s, exit 0**. Command: `env -u FACTORY_TEST_DATABASE_URL timeout 600 /workspace/agent-factory-research-next/.venv/bin/python scripts/check_python.py`; log `/tmp/no-demo-full-portable-final.log`. The skips include intentionally unavailable PostgreSQL/platform-specific acceptance; this is not full PostgreSQL validation.

A final read-only scan found three more PG-only public callers in application snapshot transfer, native research QA and research associations. They now use `fixture_identity.access_token` rather than internal tokens. Two relocated runner helpers also had whitespace-only cleanup. These post-run edits do not change any executed portable test body, but the revised PG paths still require real PostgreSQL verification. No full result is attributed to those unexecuted paths.

## PostgreSQL fast first failure diagnosis

The coordinator's first PG fast run completed 61 cases in 177.619s with 12 failure records and 22 error records (`/tmp/af-no-demo-pg-fast-first.log`). Deduplicating subtest identities gives 24 failing case IDs. These are retained, not classified as harmless intermittent failures:

- Twelve setup errors: the shared authorization helper passed an `httpx.URL` instance to the currently installed `httpx2` TestClient. Assigning the HTTPS URL as a string uses both clients' public API and changes no authentication behavior.
- Ten setup errors: the actual personal-tool/MCP fixture used the production empty application, then attempted Alice's material publication without creating its synthetic members. Its test-only publication setup now explicitly initializes those members via the normal directory service.
- One failure: `fixture-owner` existed in the isolated directory but lacked an external issuer subject mapping, producing 401 before the intended no-published-application 404. The disposable test issuer now explicitly maps this existing fixture identity.
- Eleven subtest failures in one scheduling case: the external OIDC boundary rejects an already-disabled owner with 401, before native scheduling authorization. The test now checks exact external `OIDC_ACCESS_TOKEN_INVALID`, independently retains the native boundary's 403 denial, and requires the original task ID/run-ID set and schedule definition to remain unchanged. No dispatch or state change is accepted.

Only these 24 first-failure IDs are selected for the next bounded run, using the current worktree `.venv` and isolated loopback PostgreSQL. This is targeted verification, not another full suite.

The 24-ID targeted run (`/tmp/af-no-demo-pg-failures-targeted-first.log`, timeout 360s) completed in 268.906s, exit 1: 22 passed, one MCP failure and one scheduling case with eleven subtest errors. The latter was a fixture error: minting a native token after disabling its owner is itself forbidden. Minting the retained token before disabling the owner preserves the intended current-membership test. That single case then passed in 5.274s, zero skips, exit 0 (`/tmp/af-no-demo-disabled-member-targeted-fixed.log`).

The remaining MCP failure is **not a queue terminal timeout**: native run `f0656e3b-e229-48d0-bea0-1dbeccc751ff` reached `completed`; task `debfa379-cb67-42c3-bd0c-40e07b4c8aaa` correctly retained capacity for an UNKNOWN tool outcome. Its second invocation failed before business dispatch with `MCP_TRANSPORT_ERROR`, `stopped=false`, SDK/transport closed and all 29 callbacks finished. The observer reported no error. The unchanged capacity assertion failed because this healthy-path attempt did not prove a stopped tool outcome.

The original assertion includes a complete 250-event phase trace, now retained in [the safe synthetic diagnostic](evidence/mcp-schema-original-failure.json). Relative times: queued 17.275s, running 17.498s, SDK entered 18.672s, body exited 34.089s, SDK closed 34.641s, native completed 34.694s. Credential callbacks lasted up to 5.593s; an authorization callback lasted 4.886s. Their overlap means durations cannot be summed as wall time. A 10.947s generation-2 collection occurred before the second submission, not during its SDK call; that correlation is not a demonstrated cause. The fixture database was cleaned up, but the assertion retained original identities, effect/observer facts and phase trace. The original transport exception class and precise initialize/list-tools boundary were not recorded; no cause is claimed yet and no unchanged rerun is used to close it.

A separately authorized **single** schema diagnostic run added only test-local observations: original exception class names (including bounded ExceptionGroup child class names), initialize/list-tools begin/end, and fixture HTTP method/status/receive-response times. No headers, bodies, exception messages or credentials are captured; original calls, assertions, deadlines and production code are unchanged.

Command: `FACTORY_TEST_DATABASE_URL=<existing disposable loopback fixture> PYTHONPATH=platform:applications:deployment:platform/tests:applications/tests timeout 120 .venv/bin/python -m unittest test_personal_mcp_capacity_postgres.PersonalMCPCapacityPostgresTests.test_schema_failure_releases_capacity_and_keeps_original_receipt_after_restart`. Result: **one passed, zero skipped, 16.872s, exit 0**, log `/tmp/af-no-demo-mcp-schema-diagnostic-once.log`; [instrumented phase evidence](evidence/mcp-schema-instrumented-single-run.json).

This run's two initializes took 0.348s / 0.333s and list-tools took 0.902s / 0.958s; HTTP response latency after fixture receipt was approximately 1–7ms. Both tool calls completed and capacity released. This rules out a consistently broken handshake or persistently unresponsive server in that run only. It does **not** identify the earlier transport exception or close its failure. The earlier seconds-long authorization/credential callbacks remain a concrete hypothesis for a later controlled investigation; no timeout, GC setting, retry or success assertion was relaxed, and there was no repeat-until-green loop.

### Read-only callback attribution

Comparing the original failure with the instrumented single pass locates the slowdown **inside running callbacks**, without establishing its cause:

| Seconds, median / maximum | Failure | Single pass |
|---|---:|---:|
| Authorization thread execution | 0.241 / 4.886 | 0.086 / 0.168 |
| Credential thread execution | 3.404 / 5.593 | 0.202 / 0.325 |
| Authorization executor queue | 0.000515 / 0.411083 | 0.000313 / 0.004622 |
| Credential executor queue | 0.000253 / 0.003820 | 0.000123 / 0.002386 |
| Authorization return-to-await | 0.000553 / 0.035117 | 0.000207 / 0.003599 |
| Credential return-to-await | 0.001013 / 0.001828 | 0.000199 / 0.001287 |

The failed trace contains 22 authorization / 7 credential callbacks, versus 49 / 16 across two successful invocations. Thread spans are wall time, not CPU time; overlapping spans must not be added. Callback execution overlaps almost the entire SDK window in both runs (failure 15.349 of 15.417s; success 2.016 of 2.054s and 2.020 of 2.050s), partly because the authorization monitor intentionally runs throughout. That overlap alone is not causation.

Executor enqueue/return delays cannot account for most of the slowdown. Heartbeat-to-loop delay reached 0.913s in the failure versus 0.017s in the single pass, indicating some scheduling delay without locating SQL/pool/CPU contention. Gen1/2 collection **within** the failed SDK window totals only 0.0219s; the long generation-2 collection preceded submission. There is no evidence that this invocation directly spent its deadline in GC, that the native queue stopped progressing, or that an old fixture retained a specific pool/lock/thread.

Per-engine acquisition/query timing, callback thread CPU and safe thread-stack locations were not recorded. SQL pool/lock delays, repeated current-authority reads and host scheduling therefore remain competing hypotheses. The next observation should first use already-running CI diagnostics; any additional authorized experiment should attribute time to concrete callback functions/SQL acquisition rather than repeat an unchanged schema test. No additional runtime experiment accompanied this comparison.

## Published CI checkpoint — 2026-10-25, head ba08307

PR [#136](https://github.com/Guanzhw/agent-factory/pull/136) exact head
`ba083074df8e1f049174f39b654315bd1ef5e8df` has successful
[fast CI 40223992140](https://github.com/Guanzhw/agent-factory/actions/runs/40223992140).
This does not replace the failed full run at the earlier head.

[Full CI 40223312294](https://github.com/Guanzhw/agent-factory/actions/runs/40223312294)
at `d6c8f620322eb4fe246c300000da93b53a2d4163` ended **FAIL**.
Platform PostgreSQL discovery ran 2068 cases in 1347.913s:
**2018 passed, 36 failures, 9 errors, 5 skips**. The raw summary is retained in
`/tmp/no-demo-full-ci-failures.log`. Research discovery completion is not
established by this log; no research full result is inferred. The 45 failing
platform cases remain under fixture diagnosis/correction by assistant_messages
and assistant_endpoints. They are not recorded as fixed or passed.

The old Linux frontend failure is separately identified: the synthetic
`personal_tools_smoke.py` API returned `auth/config.enabled=False`. The product
correctly showed the unconfigured-identity screen, so the resource button timed
out at the unchanged 10-second limit. The same failure appears in the
[first fast frontend job](https://github.com/Guanzhw/agent-factory/actions/runs/40223285963/job/121259321047).
The npm check (487 tests) and audits had passed before this browser failure.

`ba08307` changes only that test fixture to an explicitly configured browser
session, provides synthetic CSRF and checks the mutation header. It removes the
fixture's demo status label. All original configure/bind lost-acknowledgement,
owner-change, descriptor-withdrawal and credential-rejection assertions remain.
Actual Chromium then passed **8/8 scenarios**, including narrow viewports, exit 0:
`python platform/tests/browser/personal_tools_smoke.py --dist /tmp/af-no-demo-core-browser-dist --browser /usr/bin/chromium --output /tmp/af-no-demo-personal-tools-first`.
Results: `/tmp/af-no-demo-personal-tools-first/results.json`; log:
`/tmp/af-no-demo-personal-tools-first.log`. Independent incremental review PASS.
This is browser interaction with a wholly synthetic API, not real OIDC or
CLI/MCP integration. The earlier real local-OIDC runs remain separate evidence.
No product timeout, authentication boundary or business assertion was relaxed.

The historical MCP transport failure remains unresolved; neither a fast green
run nor this browser fixture correction establishes its cause. No real external
IdP, paid model or GPU acceptance is added by this checkpoint.

## Full PostgreSQL CI follow-up (2026-10-25)

Run `40223312294`, PG job `121259401464`, did **not** pass: 2068 tests,
36 failures, 9 errors, 5 skips in 1347.913 seconds. Original failure trace is
preserved at `/tmp/no-demo-full-ci-failures.log`; it is not superseded by any
later targeted result.

The 32 failing IDs outside the separate OIDC/origin-authority review have these
fixture migration causes:

- Capacity/pressure fixtures create twenty directory accounts but omitted their
  explicit external issuer subject mapping. The fixture now supplies those
  exact subjects; product mapping remains closed.
- Member-tool/reusable-tool fixtures send their first public configuration call
  before their former publication helper initialized members. Startup now
  explicitly initializes the disposable accounts, including reused fixtures.
- Disabled-member assertions previously expected the native `403` at the
  public OIDC boundary. The same request now must return exact public
  `401/OIDC_ACCESS_TOKEN_INVALID`, then is exercised against the test-only native
  app with a synthetic internal token and must still return `403`. This does
  not alter production authorization or expose the internal listener.
- The lost-ACK proxy forwarded the retired cookie instead of the client's
  bearer header; its request never committed. Forwarding the actual header
  restores the original commit-before-disconnect oracle.
- Storage's borrowed subprocess fixture omitted its new `headers` helper.
- Delegation's catalog mutation still used removed `seed=True`; it now uses
  ordinary owner draft/publication and retains the immutable child-plan check.
- The historical unbound plan is rejected first by `BINDING_MANIFEST_REQUIRED`;
  the separate application check still explicitly rejects its missing pin.
  The removed legacy adoption method is not reintroduced.
- Receiver identity tests now separate a rejected internal signing token at
  the public boundary from a valid external token belonging to the wrong
  owner (`404`). The shared test issuer no longer implies separate app keys.

`test_oidc_identity_postgres.py` (4 failures) and `test_remote_authority.py`
(7 errors, 2 failures) are handled separately; this work does not claim those
paths fixed. Owned targeted IDs are recorded in
`/tmp/no-demo-owned-failed-ids.txt` (32 exact original failures). Ruff and diff
whitespace checks pass; targeted PG execution is pending its exclusive slot.
No production changes, weakened limits, assertion deletion, or new skips.

### Owned 32-case follow-up and next diagnostics

Fixture head `9e0b729` ran the 32 exact original failing IDs once, serially,
under a 900-second process cap: **28 passed, 3 failed, 1 errored, 0 skipped**,
435.902 seconds, exit 1. Log:
`/tmp/no-demo-full-failures-targeted-first.log`.

- Two newly reached disabled-member checks remained in capacity case 02 and
  resource-maintenance cleanup; `28d5daa` gives these the same public-OIDC and
  internal-native assertions. Their post-fix execution is not yet claimed.
- Storage now starts successfully, but its real cancellation HTTP request
  exceeds the unchanged 15-second client deadline. This is a new observed
  runtime failure, not evidence of an authentication failure. Normal fixture
  teardown removed its temporary server log; no server stack was captured.
- The MCP account-reuse matrix reached Bob after controller restart. Its first
  tool effect is DONE, its second UNKNOWN; the original native queue is still
  running at 20.071 seconds. There are nine actual business calls. The observer
  reports no error. The global diagnostic ring discarded 108 callbacks, so its
  empty per-run list cannot establish that no callbacks ran. Safe original
  metadata is preserved in `/tmp/no-demo-full-targeted-mcp-original.json`.

No additional unchanged rerun is justified by these results. Proposed bounded
single-case diagnostics (not yet executed):

1. Storage cancellation: retain the subprocess server log before fixture
   cleanup; record entry/exit metadata for ControlCommands submit/dispatch,
   delegation cascade/inspect, owned-runtime cancellation, native cancel and
   final job detail. A test-only watchdog before the existing deadline captures
   all-thread stacks (no locals) and schedules a native-loop asyncio task-stack
   snapshot. Log pool-connect entry/exit and checkout/checkin plus SQL duration,
   without SQL text/parameters, on the Store/native/root-lock pools. An absent
   loop snapshot with a thread stuck acquiring a lock is evidence distinct
   from an awaited native cancellation. Do not extend any deadline.
2. MCP original account-reuse matrix: increase only the bounded diagnostic
   metadata capacity enough for its five original runs; retain queued/thread
   entry/thread exit/await-exit and SQL timing for the failing run. At its
   original wait's pre-deadline checkpoint collect the same safe thread/task
   and pool-acquisition evidence, plus initialize/list-tools/tool-call phase
   boundaries. This distinguishes pool acquisition, SQL execution, synchronous
   authorization/credential work, event-loop starvation and SDK/service waits.

Static cancellation chain: FactoryAPI compatibility cancel awaits
ControlCommands submission, then job detail. Dispatch persists its boundary,
then awaits delegation cascade; cascade records cancellation under the original
root lock, invokes owned-runtime/workflow cleanup, native cancel, and group
inspection. Source alone does not identify which stage consumed this timeout.
The MCP callback chain still rechecks current authorization around credentials;
no authority cache, callback removal, GC change or retry is proposed.
