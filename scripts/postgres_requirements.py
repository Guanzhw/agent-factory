"""Required synthetic acceptance selectors, shared by full and focused checks.

Class/module selectors include newly added and inherited cases. Exact method
selectors pin a few model/permission invariants independently of suite size.
"""

REQUIRED_TESTS = {
    'ssh_original_execution': (
        'test_ssh_native_postgres.SSHNativePostgresTests',
        'test_research_ssh_native_postgres.ResearchSSHNativePostgresTests',
    ),
    'owner_byok_default_off': (
        'test_billing_mode.BillingModeTests',
        'test_byok_model.ByokModelTests',
        'test_personal_models_postgres.PersonalModelsPostgresTests',
        'test_trusted_model_proxy.TrustedModelProxyTests',
        'test_trusted_model_proxy_postgres.TrustedModelProxyPostgresTests',
        'test_application_environments.ApplicationEnvironmentTests',
        'test_application_environments_postgres.ApplicationEnvironmentPostgresTests',
        'test_owner_runtime_broker.OwnerRuntimeBrokerTests',
        'test_personal_ssh.PersonalSSHPostgresTests',
        'test_remote_bindings_postgres.RemoteBindingPostgresTests.test_effective_nonlocal_receiver_mapping_obeys_default_off_before_factory',
    ),
    'platform_application_boundaries': (
        'test_application_interface_postgres.ApplicationInterfacePostgresTests',
        'test_application_interface_postgres.ApplicationContextNativePostgresTests',
        'test_application_contract_v2.NeutralChecksumNativeTests.test_neutral_checksum_native_artifact',
        'test_environment_bindings_postgres.EnvironmentBindingPostgresTests',
        'test_personal_remote_postgres.PersonalRemotePostgresTests.test_actual_http_member_scope_bind_restart_and_member_disable',
        'test_credential_vault_postgres.CredentialVaultPostgresTests',
        'test_credential_vault_wiring_postgres.CredentialVaultWiringPostgresTests',
        'test_lifecycle_observer_postgres.LifecycleObserverPostgresTests.test_13_terminal_effect_requires_registered_positive_stop_proof',
        'test_remote_authority.OriginAuthorityPostgresTests.test_actual_current_owner_connection_revocation_denies_without_resolving_or_constructing_provider',
    ),
    'workflow_native_fixture': (
        'test_native_workflow_reuse_postgres',
        'test_native_workflow_factory_postgres',
        'test_workflow_custody_postgres',
    ),
    'department_self_service': (
        'test_department_admission_postgres.DepartmentAdmissionPostgresTests',
        'test_department_publication.DepartmentPublicationPostgresTests',
        'test_department_plan_policy.DepartmentPlanPolicyTests',
    ),
    'execution_invariants': (
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_concurrent_native_runs_keep_models_knowledge_and_owner_context_separate',
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_each_provider_turn_rechecks_current_authority_after_actual_native_tool',
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_unavailable_forged_and_unadopted_bindings_have_no_demo_fallback',
        'test_personal_models_postgres.PersonalModelsPostgresTests.test_stale_tab_expected_owner_rejects_secret_and_metadata_before_any_write',
        'test_byok_model.ByokModelTests.test_no_environment_fallback_and_sanitized_errors_and_echo',
    ),
}
