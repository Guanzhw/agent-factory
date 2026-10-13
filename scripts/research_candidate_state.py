"""Narrow existing-database composition, without native workers or demo seeding.

Stop-only mode opens existing task metadata and the application wait journal.
Full evidence verification additionally
initializes existing service metadata/configuration; it never seeds identities,
materials, applications, starts lifespans or schedules execution.
"""
from contextlib import contextmanager


@contextmanager
def open_state(settings, *, full_verification=False):
    from agent_factory_research.services import services_for, release_services
    from agno.db.postgres import PostgresDb
    from agent_factory.store import Store
    from agent_factory.auth import AuthService
    from agent_factory_research.lifecycle_compatibility import ResearchLifecycleObserver
    from agent_factory.resources import PersistentResourceService
    from agent_factory.process_runtime import ProcessRuntimeService
    from agent_factory_research.research_runtime import ResearchProcessRuntimeService
    from agent_factory_research.research_runtime_hooks import ResearchRuntimeHooks
    from agent_factory_research.inference_wait import initialize as initialize_inference_wait, mark_cancel_requested
    from agent_factory_research.storage_compatibility import ResearchStorageGovernance
    from agent_factory.delegation import DelegationService
    from agent_factory.native_bridge import NativeBridge
    from pathlib import Path
    import stat

    class ExistingStorage(ResearchStorageGovernance):
        def __init__(self, store, auth):
            self.store, self.auth, self.settings = store, auth, store.settings
            self.root = Path(settings.workspace) / 'managed-storage'
            self.objects, self.quarantine = self.root / 'objects', self.root / 'quarantine'
            self.identities = {}
            for path in (self.root, self.objects, self.quarantine):
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError('RESEARCH_CANDIDATE_STORAGE_MISSING')
                self.identities[str(path)] = (info.st_dev, info.st_ino)
            from run_research_baseline import read_private
            self.root_id = read_private(self.root / 'root-id', 128, private=False).decode().strip()
            if len(self.root_id) != 36:
                raise ValueError('RESEARCH_CANDIDATE_STORAGE_MISSING')

    class ExistingStore(Store):
        def initialize(self):
            rows = self.sql("SELECT mode FROM af_bootstrap WHERE id='mode'")
            if len(rows) != 1 or rows[0]['mode'] != ('demo' if self.settings.demo else 'production'):
                raise ValueError('RESEARCH_CANDIDATE_EXISTING_DATABASE_REQUIRED')

    store = ExistingStore(settings.db_url, settings)
    native = PostgresDb(db_url=settings.db_url, id='factory-native-postgres')
    try:
        store.native_db = native
        initialize_inference_wait(store)
        store.runtime_mark_cancel_requested = lambda task_id: mark_cancel_requested(store, task_id)
        auth = store.auth = AuthService(settings, native)
        resources = PersistentResourceService(store, auth, settings.remote_targets)
        store.process_runtime = ProcessRuntimeService(store, auth, resources)
        services_for(store).research_runtime = ResearchProcessRuntimeService(store, auth, resources)
        resources.execution_runtimes['research-process-run-v1'] = services_for(store).research_runtime
        store.runtime_effect_held = ResearchRuntimeHooks.effect_held
        store.runtime_cancel_owned = lambda task: ResearchRuntimeHooks.cancel(store, task)
        store.runtime_ended_reason = lambda task: ResearchRuntimeHooks.ended_reason(store, task)
        store.lifecycle_observer = ResearchLifecycleObserver(store, auth, native, lambda: None)
        store.delegation = DelegationService(settings, store, auth, NativeBridge(settings, native, auth))
        store.storage = ExistingStorage(store, auth)
        if full_verification:
            _verification_services(store, auth, settings)
        yield {'store': store, 'auth': auth, 'resources': resources,
               'research_runtime': services_for(store).research_runtime, 'process_runtime': store.process_runtime,
               'settings': settings, 'lifecycle_observer': store.lifecycle_observer}
    finally:
        release_services(store)
        store.dispose_root_locks()
        store.engine.dispose()
        native.db_engine.dispose()


def _verification_services(store, auth, settings):
    from pathlib import Path
    from agent_factory.material_governance import MaterialGovernance, GovernanceConfig
    from agent_factory_research.bootstrap_catalog import SEEDS
    from agent_factory.connections import ConnectionService
    from agent_factory_research.synthetic_runtime import default_bindings
    from agent_factory.applications import ApplicationService
    from agent_factory.plan_policy import PlanPolicyService, PlanPolicyConfig, persisted_ancestor_guard
    from agent_factory.delegation import DelegationService
    from agent_factory.native_bridge import NativeBridge
    from agent_factory.remote_bindings import RemoteBindingService
    from agent_factory_research.handoff_compatibility import ResearchHandoffClient
    from agent_factory.usage_ledger import UsageLedger
    from agent_factory_research.synthetic_runtime import default_zero_prices
    from agent_factory.native_workflows import NativeWorkflows
    from agent_factory.tool_policy_registry import resolve_tool_policies

    # Existing configuration must be present before any service constructor.
    for table, expected in (('af_plan_policy_state', settings.policy_revision),
                            ('af_material_governance_current', settings.material_policy_revision)):
        rows = store.sql('SELECT revision FROM ' + table + " WHERE id='current'")
        if len(rows) != 1 or rows[0]['revision'] != expected:
            raise ValueError('RESEARCH_CANDIDATE_POLICY_DRIFT')
    root = Path(settings.workspace) / 'managed-storage'
    for path in (root, root / 'objects', root / 'quarantine'):
        if path.is_symlink() or not path.is_dir():
            raise ValueError('RESEARCH_CANDIDATE_STORAGE_MISSING')
    if (root / 'root-id').is_symlink() or not (root / 'root-id').is_file():
        raise ValueError('RESEARCH_CANDIDATE_STORAGE_MISSING')
    governance = store.material_governance = MaterialGovernance(store, auth, GovernanceConfig(
        review_mode=settings.material_review_mode, revision=settings.material_policy_revision,
        tool_contract=settings.runtime_tool_contract, source_synthesis_enabled=settings.source_synthesis_enabled,
        tool_policies=resolve_tool_policies(settings.tool_policies, settings.runtime_adapters)), seed_materials=SEEDS)
    store.register_execution_guard('material-governance',
        lambda owner, plan, context, tool: governance.require_materials_current(plan), tool_independent=True)
    connections = store.connections = ConnectionService(store, auth, settings.trusted_connections)
    bindings = store.execution_bindings = default_bindings(settings, store, connections)
    for entry in settings.runtime_adapters:
        bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
            tool_name=entry.tool_name, connection_kind=entry.connection_kind,
            required_capabilities=entry.required_capabilities, permissions=entry.permissions,
            demo_only=entry.demo_only, validator=entry.validator, connection_adapter_ref=entry.connection_adapter_ref)
    store.remote_bindings = RemoteBindingService(store, auth, bindings, connections, settings.remote_binding_mappings)
    applications = store.applications = ApplicationService(store, auth)
    store.register_execution_guard('execution-bindings',
        lambda owner, plan, context, tool: bindings.recheck(plan, context), tool_independent=True)
    store.register_execution_guard('application-governance',
        lambda owner, plan, context, tool: applications.require_plan_current(plan), tool_independent=True)
    # Native registry construction is in-memory only: no worker, DDL or dispatch.
    store.native_workflows = NativeWorkflows(store, auth, store.native_db, settings.native_workflows)
    store.register_execution_guard('native-workflow', store.native_workflows.require_plan_current)
    bridge = NativeBridge(settings, store.native_db, auth)
    bridge.configure_components(store.native_workflows.component_for_task)
    store.plan_policy = PlanPolicyService(store, auth, PlanPolicyConfig(
        name=settings.temporary_policy, revision=settings.policy_revision,
        review_ttl_seconds=settings.plan_review_ttl_seconds, tool_contract=settings.runtime_tool_contract,
        source_synthesis_enabled=settings.source_synthesis_enabled,
        tool_policies=resolve_tool_policies(settings.tool_policies, settings.runtime_adapters)), ancestor_guard=persisted_ancestor_guard(store))
    store.delegation = DelegationService(settings, store, auth, bridge)
    ResearchHandoffClient(store, auth, settings.handoff_targets).install_guard()
    prices = {(price.adapter_id, price.adapter_revision): price for price in default_zero_prices()}
    for price in settings.usage_pricing:
        prices[(price.adapter_id, price.adapter_revision)] = price
    store.usage_ledger = UsageLedger(store, prices=tuple(prices.values()), policy=settings.usage_policy)
