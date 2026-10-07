"""Original baseline service composition, isolated from the controller database.

Policy/lineage preflights are read-only and precede every service constructor.
Existing full-verification constructors can perform idempotent metadata/config
operations. This is not a read-only database connection: it never seeds users,
publishes materials, approves plans, opens a lifespan, or dispatches work.
"""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from agent_factory.config import Settings
from agent_factory.research_bootstrap_database_preflight import database_preflight
from agent_factory.research_bootstrap_policy import development_settings
from agent_factory.research_checkpoint_store import ResearchCheckpointStore
from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.research_local_driver import ScientificRuntimePin
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.research_runtime_profile import research_settings, registrations
from agent_factory.process_runtime_profile import process_settings
from agent_factory.store import digest
from research_candidate_database import anchor_database
from research_candidate_reopen import reconstruct_research_target
from research_candidate_state import open_state

_ERROR = 'AUTORESEARCH_BASELINE_CONTEXT_UNVERIFIED'


def _database_identity(value):
    """Private connection comparison; credentials never enter evidence/errors."""
    try:
        url = make_url(value)
        if url.get_backend_name() != 'postgresql' or not url.host or not url.database or url.query:
            raise ValueError(_ERROR)
        return (url.host.lower(), url.port or 5432, url.database)
    except Exception:
        raise ValueError(_ERROR) from None


class BaselineServiceFactory:
    """Trusted operator factory for RetainedBaselineReader.service_factory.

Both URLs are supplied privately by the operator. Distinct connection database
names are mandatory, even across different hosts, avoiding accidental aliases
back into the active controller database. This is not physical-server identity
attestation; original retained rows are independently checked on every entry.
    """
    def __init__(self, *, baseline_database_url, controller_database_url,
                 scientific_runtime: ScientificRuntimePin):
        baseline = _database_identity(baseline_database_url)
        controller = _database_identity(controller_database_url)
        if baseline[2] == controller[2] or type(scientific_runtime) is not ScientificRuntimePin:
            raise ValueError(_ERROR)
        self._database_url = baseline_database_url
        self._scientific_runtime = scientific_runtime

    @contextmanager
    def __call__(self, captured):
        original = captured['originalConfig']
        manifest = captured['contract']['comparisonManifest']
        workspace = Path(original['workspace'])
        basic = development_settings(Settings(db_url=self._database_url, workspace=workspace,
            max_workers=1, temporary_policy='admin-review'))
        # Must finish before even the stop-only provider-state composition.
        engine = create_engine(self._database_url, pool_pre_ping=True)
        try:
            if database_preflight(engine, basic).get('status') != 'PASS':
                raise ValueError(_ERROR)
        finally:
            engine.dispose()
        anchor_database(self._database_url, {'baselineReceipt': captured['receipt'],
            'manifestSha256': manifest_fingerprint(manifest)})
        with open_state(basic) as provider_state:
            targets = {stage: reconstruct_research_target(provider_state, original,
                captured['snapshots'][stage], candidate=False,
                scientific_runtime=self._scientific_runtime)['target']
                for stage in ('training', 'evaluation')}
            settings = research_settings(db_url=self._database_url, workspace=workspace,
                target_ref='evaluation', remote_targets=targets, comparison_manifest=manifest)
            preparation = process_settings(db_url=self._database_url, workspace=workspace,
                target_ref='preparation', remote_targets={})
            settings = development_settings(replace(settings,
                runtime_adapters=[*preparation.runtime_adapters,
                    *registrations(target_ref='training', comparison_manifest=manifest),
                    *registrations(target_ref='evaluation', comparison_manifest=manifest,
                                   adapter_suffix='-evaluation')],
                usage_pricing=(*preparation.usage_pricing, *settings.usage_pricing,
                    *(replace(price, adapter_id=price.adapter_id + '-evaluation')
                      for price in settings.usage_pricing))))
            with open_state(settings, full_verification=True) as state:
                checkpoints = ResearchCheckpointStore(state['store'], state['auth'],
                    state['resources'], state['store'].storage)
                yield ResearchEvaluationService(state['store'], state['auth'], state['resources'],
                    {digest(manifest['evaluator']): 'evaluation'}, checkpoint_reader=checkpoints.identity)
