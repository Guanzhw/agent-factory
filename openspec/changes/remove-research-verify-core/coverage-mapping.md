# Removal and retained behavior

本变更退役内置 Research 应用，不是测试成本优化，不能据此声称整套加速。历史失败与验收记录保留在既有 change 和 Git 历史中。

| 移除或迁移范围 | 保留的独立行为 |
| --- | --- |
| Research 源码、检索/ORX/candidate/迭代/session 算法与页面 | 显式应用/材料发布、Agno 原生 agent/workflow、通用任务历史和资源 |
| 应用专属夹具和选择器 | core_native_fixture 只在测试中显式安装合成 checksum/question/自有进程适配器；生产默认无种子与应用 |
| 导入 Research 装配的模型测试 | 同一所有者凭据选择、版本/撤回、原回执、原生队列、usage/无fallback，改为通用 application starts |
| 远程科学 placement 扩展 | 通用 v1/v2、原身份、有界取消、UNKNOWN；旧 placement/evidence 在重派或释放容量前拒绝 |
| 应用专属浏览器旅程 | 默认部署+新空PG，登录/主页/资源/任务/退出重登/直达刷新/旧URL，桌面和移动 |
| 旧 Research bootstrap 修复脚本/测试 | 通用复制/安装/解释器身份工具、core wheel真实启停、只读历史custody审计 |

通用进程类保留历史 ResearchProcessSpec/wire 名称，其实现是可复用 cwd/env/uv 执行与不可变身份，不包含 Research 编排。旧 v1 literature/experiment 模式字符串和禁止旧计费配置的防护是兼容词汇，不是已安装应用。代码不迁移或清空旧数据库；旧数据的清单确认和执行另行记录。

## Removed required/fast selectors

以下选择器对应实际移除的应用专属测试模块。保留选择器必须通过完整发现验证，不在运行时静默过滤；混合模块迁移通用行为，最终源码仍需完整验收。

- `test_research_iterations` (scripts/fast_test_groups.py, `bounded_research_iterations`)
- `test_research_iteration_driver` (scripts/fast_test_groups.py, `bounded_research_iterations`)
- `test_research_iteration_recipe` (scripts/fast_test_groups.py, `bounded_research_iterations`)
- `test_research_iteration_api` (scripts/fast_test_groups.py, `bounded_research_iterations`)
- `test_research_iteration_retirement` (scripts/fast_test_groups.py, `bounded_research_iterations`)
- `test_research_iteration_revocation_driver` (scripts/fast_test_groups.py, `bounded_research_iterations`)
- `test_application_assembly.ApplicationAssemblyTests` (scripts/fast_test_groups.py, `application_instance_ownership`)
- `test_research_candidate_native_stop.NativeStopTests` (scripts/fast_test_groups.py, `original_receipt_and_stop`)
- `test_research_package_paths.RelativePackagePathTests` (scripts/fast_test_groups.py, `research_input_contracts`)
- `test_research_staging.StagingContractTests` (scripts/fast_test_groups.py, `research_input_contracts`)
- `test_remote_scientific_phase_reads.RemoteScientificPhaseReadTests` (scripts/fast_test_groups.py, `history_control_separation`)
- `test_remote_scientific_evidence_contention` (scripts/fast_test_groups.py, `history_control_separation`)
- `test_remote_scientific_late_authority` (scripts/fast_test_groups.py, `history_control_separation`)
- `test_scientific_completion_claims` (scripts/fast_test_groups.py, `history_control_separation`)
- `test_autoresearch_remote_children.RemoteChildrenTests.test_lost_drive_ack_observes_original_only_after_validated_intent` (scripts/fast_test_groups.py, `history_control_separation`)
- `test_autoresearch_remote_children.RemoteChildrenTests.test_503_without_original_drive_intent_is_not_swallowed` (scripts/fast_test_groups.py, `history_control_separation`)
- `test_autoresearch_remote_children.RemoteChildrenTests.test_terminal_child_with_validated_drive_intent_only_observes_original` (scripts/fast_test_groups.py, `history_control_separation`)
- `test_research_iteration_retirement_postgres` (scripts/fast_test_groups.py, `shared_local_budget_commitments`)
- `test_research_package_paths.CompletePackagePathJourneyTests` (scripts/fast_test_groups.py, `research_inventory_posix`)
- `test_research_bootstrap_inventory.BootstrapInventoryTests` (scripts/fast_test_groups.py, `research_inventory_posix`)
- `test_research_inventory_document_bounds.InventoryDocumentBoundsTests` (scripts/fast_test_groups.py, `research_inventory_posix`)
- `test_research_staging.StagingFilesystemTests` (scripts/fast_test_groups.py, `research_inventory_posix`)
- `test_platform_openresearch_runtime.PlatformOpenResearchRuntimeTests` (scripts/postgres_requirements.py, `owner_byok_default_off`)
- `test_platform_openresearch_custody.PlatformOpenResearchCustodyTests` (scripts/postgres_requirements.py, `owner_byok_default_off`)
- `test_native_research_artifacts.NativeArtifactWireTests` (scripts/postgres_requirements.py, `owner_byok_default_off`)
- `test_native_research_artifacts.NativePlatformFileReaderTests` (scripts/postgres_requirements.py, `owner_byok_default_off`)
- `test_ssh_openresearch.SSHOpenResearchTests` (scripts/postgres_requirements.py, `owner_byok_default_off`)
- `test_openresearch_workspace_postgres.WorkspacePostgresTests` (scripts/postgres_requirements.py, `platform_application_boundaries`)
- `test_managed_workspace_postgres.ManagedWorkspacePostgresTests` (scripts/postgres_requirements.py, `platform_application_boundaries`)
- `test_managed_orx_attachment_postgres.ManagedORXPostgresTests` (scripts/postgres_requirements.py, `platform_application_boundaries`)
- `test_personal_command_postgres.PersonalCommandPostgresTests` (scripts/postgres_requirements.py, `platform_application_boundaries`)
- `test_personal_orx_postgres.PersonalOrxPostgresTests` (scripts/postgres_requirements.py, `platform_application_boundaries`)
- `test_native_research_artifacts_postgres.NativeArtifactPostgresTests` (scripts/postgres_requirements.py, `platform_application_boundaries`)
- `test_personal_orx_projects_postgres.OrxProjectPostgresTests` (scripts/postgres_requirements.py, `platform_application_boundaries`)
- `test_openresearch_journey_postgres.ResearchJourneyPostgresTests` (scripts/postgres_requirements.py, `platform_application_boundaries`)
- `test_research_candidate_postgres` (scripts/postgres_requirements.py, `research_candidate_postgres`)
- `test_research_candidate_baseline_postgres` (scripts/postgres_requirements.py, `research_candidate_postgres`)
- `test_research_candidate_command_postgres` (scripts/postgres_requirements.py, `research_candidate_postgres`)
- `test_research_candidate_execute_postgres` (scripts/postgres_requirements.py, `research_candidate_postgres`)
- `test_candidate_database_auth_postgres` (scripts/postgres_requirements.py, `research_candidate_postgres`)
- `test_autoresearch_postgres` (scripts/postgres_requirements.py, `autoresearch_native_fixture`)
- `test_autoresearch_session_control_postgres` (scripts/postgres_requirements.py, `autoresearch_native_fixture`)
- `test_autoresearch_scientific_children_postgres` (scripts/postgres_requirements.py, `autoresearch_native_fixture`)
- `test_remote_scientific_integration` (scripts/postgres_requirements.py, `autoresearch_native_fixture`)
- `test_remote_scientific_debit_postgres` (scripts/postgres_requirements.py, `autoresearch_native_fixture`)
- `test_autoresearch_postgres.AutoResearchPostgresTests.test_missing_stop_proof_holds_original_effect_and_replay_never_dispatches` (scripts/postgres_requirements.py, `execution_invariants`)

## Mixed module selectors

- `test_personal_ssh.SSHPrerequisiteTests`: 仅删除 Research Docker/目录启动探针；通用 SSH 账号、vault 与 agent 生命周期测试仍为 required。
- `LifecycleObserverPostgresTests.test_13_terminal_orx_without_stop_proof_holds_every_capacity_projection` → `test_13_terminal_effect_requires_registered_positive_stop_proof`: 保留通用效果注册器的正向停止证明、UNKNOWN 与容量断言，移除对 ORX 服务的依赖。
