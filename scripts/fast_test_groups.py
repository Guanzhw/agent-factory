"""Small daily regression selections; full discovery retains every other case.

Python selections need neither PostgreSQL nor host-specific process/SSH tools.
The PostgreSQL lane runs on Linux and includes the small POSIX inventory cases.
All model responses and credentials are synthetic; no live provider is called.
"""

FAST_PYTHON_TESTS = {
    'architecture_checks': (
        'test_architecture_checker',
        'test_postgres_checks',
        'test_ci_checks',
    ),
    'owner_model_protocols': (
        'test_byok_model.ByokModelTests',
        'test_model_protocol_execution.OwnerProtocolExecutionTests',
        'test_trusted_model_proxy.TrustedModelProxyTests.test_explicit_routes_use_real_codec_and_exact_gateway_wire',
        'test_trusted_model_proxy.TrustedModelProxyTests.test_legacy_grant_does_not_authorize_new_protocol_or_prefix',
    ),
    'selected_model_and_current_authority': (
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_concurrent_native_runs_keep_models_knowledge_and_owner_context_separate',
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_each_provider_turn_rechecks_current_authority_after_actual_native_tool',
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_unavailable_forged_and_unadopted_bindings_have_no_demo_fallback',
    ),
    'department_defaults': (
        'test_department_plan_policy.DepartmentPlanPolicyTests',
        'test_billing_mode.BillingModeTests',
    ),
    'personal_tool_connections': (
        'test_personal_tools',
        'test_personal_tool_execution',
        'test_personal_tool_assembly.PersonalToolSettingsTests',
    ),
    'original_receipt_and_stop': (
        'test_process_receipt_validation.ProcessReceiptValidation',
        'test_research_candidate_native_stop.NativeStopTests',
    ),
    'research_input_contracts': (
        'test_research_package_paths.RelativePackagePathTests',
        'test_research_staging.StagingContractTests',
    ),
}

FAST_POSTGRES_TESTS = {
    'original_process_custody': (
        'test_process_runtime_postgres.ProcessRuntimePostgresTests.test_original_native_plan_task_lease_and_process_identity_survive_reopen',
        'test_process_runtime_postgres.ProcessRuntimePostgresTests.test_lost_launch_receipt_reconciles_original_process_without_replay',
        'test_process_runtime_postgres.ProcessRuntimePostgresTests.test_unknown_launch_retains_pool_after_provider_restart_without_replay',
        'test_process_runtime_postgres.ProcessRuntimePostgresTests.test_lost_stop_receipt_reconciles_without_repeating_cancel',
        'test_process_runtime_postgres.ProcessRuntimeTransactionPostgresTests.test_two_receipts_share_one_artifact_with_size_one_metadata_pool',
    ),
    'credentials_and_original_model_selection': (
        'test_credential_vault_postgres.CredentialVaultPostgresTests.test_ciphertext_restart_rotation_revoke_and_cas',
        'test_model_command_recovery_postgres.ModelCommandRecoveryPostgresTests.test_default_replay_recovers_original_receipt_after_another_default_command',
        'test_personal_models_postgres.PersonalModelsPostgresTests.test_stale_tab_expected_owner_rejects_secret_and_metadata_before_any_write',
        'test_environment_bindings_postgres.EnvironmentBindingPostgresTests.test_explicit_generation_restore_after_restart_rotation_and_lost_ack_never_selects_default',
        'test_trusted_model_proxy_postgres.TrustedModelProxyPostgresTests.test_generic_protocols_complete_native_task_with_existing_owner_vault',
    ),
    'member_self_service': (
        'test_personal_models_postgres.PersonalModelsPostgresTests.test_single_submit_native_queue_no_billing_no_admin_and_replay',
        'test_department_admission_postgres.DepartmentAdmissionPostgresTests.test_member_runs_multiple_applications_and_workflow_without_admin_decision',
        'test_department_publication.DepartmentPublicationPostgresTests.test_public_deactivation_requires_admin_and_keeps_history',
        'test_department_publication.DepartmentPublicationPostgresTests.test_http_member_publish_and_admin_only_delete_surface',
        'test_personal_tool_assembly.PersonalToolAssemblyPostgresTests',
    ),
    # Tiny inert trees, including mutation checks; no installed ML tree or scale campaign.
    'research_inventory_posix': (
        'test_research_package_paths.CompletePackagePathJourneyTests',
        'test_research_bootstrap_inventory.BootstrapInventoryTests',
        'test_research_inventory_document_bounds.InventoryDocumentBoundsTests',
        'test_research_staging.StagingFilesystemTests',
    ),
}
