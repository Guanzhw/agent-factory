"""Small daily regression selections; full discovery retains every other case.

Python selections need neither PostgreSQL nor external process/SSH tools; their
personal CLI fixtures require POSIX. Both fast lanes run on Linux.
All model responses and credentials are synthetic; no live provider is called.
"""

FAST_PYTHON_TESTS = {
    'local_login': (
        'test_local_login',
        'test_credential_vault.CredentialVaultTests.test_browser_bridge_rejects_missing_csrf_before_body_or_vault',
    ),
    'ssh_original_contracts': (
        'test_ssh_operation_runtime', 'test_ssh_operation_waits', 'test_ssh_tool_factory',
    ),
    'assistant_event_contracts': ('test_assistant_events', 'test_assistant_message_recovery'),
    'research_projects': ('test_research_projects',),
    'shared_mcp_authority_regressions': (
        'test_application_closure_authority.BoundedApplicationClosureTests',
        'test_personal_mcp_callbacks',
        'test_mcp_diagnostic_custody',
        'test_mcp_phase_ring',
        'test_native_fixture_lifecycle',
        'test_personal_mcp_teardown_auth',
    ),
    'bounded_research_iterations': (
        'test_native_workflow_bridge',
    ),
    'application_instance_ownership': (
        'test_application_runtime.ApplicationRuntimeTests',
    ),
    'remote_v2_contract': (
        'test_remote_v2_manifest',
        'test_remote_v2_bindings',
        'test_remote_v2_authority',
    ),
    'architecture_checks': (
        'test_architecture_checker',
        'test_postgres_checks',
        'test_profile_tests',
        'test_ci_checks',
    ),
    'owner_model_protocols': (
        'test_byok_model.ByokModelTests',
        'test_model_protocol_execution.OwnerProtocolExecutionTests',
        'test_trusted_model_proxy.TrustedModelProxyTests.test_explicit_routes_use_real_codec_and_exact_gateway_wire',
        'test_trusted_model_proxy.TrustedModelProxyTests.test_legacy_grant_does_not_authorize_new_protocol_or_prefix',
    ),
    'selected_model_and_current_authority': (
        'test_application_closure_authority.BoundedApplicationClosureTests',
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_concurrent_native_runs_keep_models_knowledge_and_owner_context_separate',
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_each_provider_turn_rechecks_current_authority_after_actual_native_tool',
        'test_execution_bindings.ExecutionBindingRuntimeTests.test_unavailable_forged_and_unadopted_bindings_have_no_demo_fallback',
    ),
    'department_defaults': (
        'test_department_plan_policy.DepartmentPlanPolicyTests',
        'test_billing_mode.BillingModeTests',
        'test_schedule_permissions.ScheduleMemberPermissionTests',
    ),
    'reusable_tool_operations': (
        'test_tool_operations',
        'test_member_tool_operations',
        'test_reusable_tool_accounts',
    ),
    'personal_tool_connections': (
        'test_personal_tool_adapter_integration',
        'test_personal_tool_contract',
        'test_personal_cli',
        'test_personal_cli_process',
        'test_personal_mcp',
        'test_mcp_phase_ring',
        'test_personal_mcp_callbacks',
        'test_personal_mcp_teardown_auth',
        'test_mcp_diagnostic_custody',
        'test_native_fixture_lifecycle',
        'test_material_governance_bulk_postgres.MaterialDependencyTraversalTests',
        'test_personal_tools',
        'test_personal_tool_execution',
        'test_personal_tool_assembly.PersonalToolSettingsTests',
    ),
    'original_receipt_and_stop': (
        'test_native_timeout_diagnostics',
        'test_process_receipt_validation.ProcessReceiptValidation',
        'test_guardian_reaping',
    ),
    'history_control_separation': (
        'test_history_summary_status.HistorySummaryStatusTests',
        'test_remote_receipt_snapshot',
    ),
}

FAST_POSTGRES_TESTS = {
    'local_login': ('test_local_login_postgres.LocalLoginPostgresTests',),
    'ssh_original_native_wait': (
        'test_ssh_native_postgres.SSHNativePostgresTests.test_original_native_wait_resumes_once_after_controller_restart',
    ),
    'owned_native_finalization': (
        'test_owned_native_finalization_postgres.OwnedNativeFinalizationPostgresTests.test_unknown_usage_retains_holds_then_original_evidence_finishes_once_after_reopen',
        'test_owned_native_finalization_postgres.OwnedNativeFinalizationPostgresTests.test_two_observers_and_reserve_share_commit_without_duplicate_outbox',
        'test_owned_native_finalization_queue_postgres.OwnedNativeFinalizationQueuePostgresTests.test_native_completion_callback_rollback_then_restart_finishes_original_once',
    ),
    'bounded_assistant_admission': (
        'test_assistant_budget_request_postgres.AssistantBudgetRequestPostgresTests.test_public_handoff_wins_reservation_but_inherits_original_budget',
        'test_assistant_budget_request_postgres.AssistantBudgetRequestPostgresTests.test_bound_plan_cannot_start_with_an_unbudgeted_new_request_key',
        'test_assistant_budget_request_postgres.AssistantBudgetRequestPostgresTests.test_local_budget_root_cannot_select_remote_before_or_after_reservation',
        'test_assistant_events_postgres.AssistantEventsPostgresTests.test_actual_background_delivery_wakes_offline_receiver_with_bound_scope',
        'test_assistant_events_postgres.AssistantEventsPostgresTests.test_revocation_commits_after_initial_check_before_reservation_and_dispatch_is_zero',
        'test_assistant_events_postgres.AssistantEventsPostgresTests.test_stopping_after_recovery_check_before_reservation_blocks_fresh_dispatch',
        'test_assistant_message_recovery_postgres.AssistantMessageRecoveryPostgresTests.test_two_recoverers_both_observe_no_task_but_native_dispatches_once',
        'test_assistant_budget_guard_postgres.AssistantBudgetGuardPostgresTests.test_cancelled_scope_blocks_retained_native_model_and_tool',
    ),
    'research_projects': ('test_research_projects_postgres',),
    'fresh_bounded_material_authority': (
        'test_material_governance_bulk_postgres.MaterialGovernanceBulkPostgresTests',
    ),
    'shared_local_budget_commitments': (
        'test_local_budget_scopes_postgres',
        'test_local_budget_scope_boundaries_postgres',
    ),
    'history_background_finalization': (
        'test_task_history_postgres.TaskHistoryPostgresTests.test_z_native_completion_waits_for_background_finalization_without_read_side_effects',
    ),
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
        'test_material_governance_bulk_postgres.MaterialGovernanceBulkPostgresTests.test_thirty_pins_use_one_join_and_next_call_observes_withdrawal',
        'test_scheduling_member_postgres.MemberSchedulingPostgresTests',
        'test_personal_models_postgres.PersonalModelsPostgresTests.test_single_submit_native_queue_no_billing_no_admin_and_replay',
        'test_department_admission_postgres.DepartmentAdmissionPostgresTests.test_member_runs_multiple_applications_and_workflow_without_admin_decision',
        'test_department_publication.DepartmentPublicationPostgresTests.test_http_own_private_archive_preserves_owner_visibility',
        'test_department_publication.DepartmentPublicationPostgresTests.test_http_member_can_publish_and_archive_own_resource',
        'test_personal_tool_assembly.PersonalToolAssemblyPostgresTests',
        'test_personal_tool_native_postgres.PersonalToolNativePostgresTests',
        'test_personal_mcp_capacity_postgres.PersonalMCPCapacityPostgresTests',
    ),
}
