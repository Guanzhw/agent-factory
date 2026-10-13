"""Required synthetic acceptance selectors, shared by full and focused checks.

Class/module selectors include newly added and inherited cases. Exact method
selectors pin a few model/permission invariants independently of suite size.
"""

REQUIRED_TESTS = {
    'owner_byok_default_off': (
        'test_billing_mode.BillingModeTests',
        'test_byok_model.ByokModelTests',
        'test_personal_models_postgres.PersonalModelsPostgresTests',
        'test_trusted_model_proxy.TrustedModelProxyTests',
        'test_trusted_model_proxy_postgres.TrustedModelProxyPostgresTests',
        'test_application_environments.ApplicationEnvironmentTests',
        'test_application_environments_postgres.ApplicationEnvironmentPostgresTests',
        'test_owner_runtime_broker.OwnerRuntimeBrokerTests',
        'test_platform_openresearch_runtime.PlatformOpenResearchRuntimeTests',
        'test_platform_openresearch_custody.PlatformOpenResearchCustodyTests',
        'test_native_research_artifacts.NativeArtifactWireTests',
        'test_native_research_artifacts.NativePlatformFileReaderTests',
        'test_ssh_openresearch.SSHOpenResearchTests',
        'test_personal_ssh.PersonalSSHPostgresTests',
        'test_personal_ssh.SSHPrerequisiteTests',
        'test_remote_bindings_postgres.RemoteBindingPostgresTests.test_effective_nonlocal_receiver_mapping_obeys_default_off_before_factory',
    ),
    'platform_application_boundaries': (
        'test_application_interface_postgres.ApplicationInterfacePostgresTests',
        'test_application_interface_postgres.ApplicationContextNativePostgresTests',
        'test_application_contract_v2.NeutralChecksumNativeTests.test_neutral_checksum_native_artifact',
        'test_environment_bindings_postgres.EnvironmentBindingPostgresTests',
        'test_personal_remote_postgres.PersonalRemotePostgresTests.test_actual_http_auth_scope_bind_restart_and_native_grant_revocation',
        'test_openresearch_workspace_postgres.WorkspacePostgresTests',
        'test_credential_vault_postgres.CredentialVaultPostgresTests',
        'test_credential_vault_wiring_postgres.CredentialVaultWiringPostgresTests',
        'test_managed_workspace_postgres.ManagedWorkspacePostgresTests',
        'test_managed_orx_attachment_postgres.ManagedORXPostgresTests',
        'test_personal_command_postgres.PersonalCommandPostgresTests',
        'test_personal_orx_postgres.PersonalOrxPostgresTests',
        'test_native_research_artifacts_postgres.NativeArtifactPostgresTests',
        'test_personal_orx_projects_postgres.OrxProjectPostgresTests',
        'test_openresearch_journey_postgres.ResearchJourneyPostgresTests',
        'test_lifecycle_observer_postgres.LifecycleObserverPostgresTests.test_13_terminal_orx_without_stop_proof_holds_every_capacity_projection',
        'test_remote_authority.OriginAuthorityPostgresTests.test_actual_current_owner_connection_revocation_denies_without_resolving_or_constructing_provider',
    ),
    'research_candidate_postgres': (
        'test_research_candidate_postgres',
        'test_research_candidate_baseline_postgres',
        'test_research_candidate_command_postgres',
        'test_research_candidate_execute_postgres',
        'test_candidate_database_auth_postgres',
    ),
    'autoresearch_native_fixture': (
        'test_autoresearch_postgres',
        'test_autoresearch_session_control_postgres',
        'test_autoresearch_scientific_children_postgres',
        'test_remote_scientific_integration',
        'test_remote_scientific_debit_postgres',
    ),
    'workflow_native_fixture': (
        'test_native_workflow_reuse_postgres',
        'test_native_workflow_factory_postgres',
        'test_workflow_custody_postgres',
    ),
    'execution_invariants': (
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_concurrent_native_runs_keep_models_knowledge_and_owner_context_separate',
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_each_provider_turn_rechecks_current_authority_after_actual_native_tool',
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_unavailable_forged_and_unadopted_bindings_have_no_demo_fallback',
        'test_personal_models_postgres.PersonalModelsPostgresTests.test_stale_tab_expected_owner_rejects_secret_and_metadata_before_any_write',
        'test_personal_models_postgres.PersonalModelsPostgresTests.test_single_submit_native_queue_no_billing_no_admin_and_replay',
        'test_byok_model.ByokModelTests.test_no_environment_fallback_and_sanitized_errors_and_echo',
        'test_autoresearch_postgres.AutoResearchPostgresTests.test_missing_stop_proof_holds_original_effect_and_replay_never_dispatches',
    ),
}
