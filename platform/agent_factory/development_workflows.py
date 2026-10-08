"""Explicit persistent synthetic development profile; no external providers.

Setup installs trusted local adapters. Publication and initial connection binding
are separate, explicit bootstrap operations; task-plan reviews remain untouched.
"""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import stat
import sys

import httpx

from . import comparison_profile, pubmed_profile, synthesis_runtime
from .comparison_fixture import CHOICES, fixture_limits, fixture_spec
from .config import Settings
from .connections import TrustedConnectionBinding
from .literature_synthesis import SCIENTIFIC_CAPABILITY
from .literature_synthesis_profile import trusted_model_binding
from .process_provider import ProcessResourceProvider
from .resources import ComputePool, RemoteTarget
from .store import Store, digest
from .usage_ledger import PricingRevision

PROFILE = 'controlled-development-v1'
OWNERS = ('alice', 'bob')


def _require(value):
    if not value:
        raise ValueError('DEVELOPMENT_WORKFLOWS_INVALID')


class _Body(httpx.AsyncByteStream):
    def __init__(self, raw):
        self.raw = raw

    async def __aiter__(self):
        yield self.raw


def _synthetic_request(request):
    _require(request.method == 'GET' and request.url.host == 'eutils.ncbi.nlm.nih.gov')
    if request.url.path == '/entrez/eutils/esearch.fcgi':
        raw = b'{"esearchresult":{"idlist":["123"]}}'
        media = 'application/json'
    elif request.url.path == '/entrez/eutils/efetch.fcgi':
        raw = (b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article>'
               b'<ArticleTitle>Synthetic development source, not a real paper</ArticleTitle><Abstract>'
               b'<AbstractText>Synthetic bounded excerpt for testing citation structure only.</AbstractText>'
               b'</Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>')
        media = 'application/xml'
    else:
        raise ValueError('DEVELOPMENT_WORKFLOWS_INVALID')
    return httpx.Response(200, headers={'content-type': media}, stream=_Body(raw))


def registration_refs(owner):
    _require(owner in OWNERS)
    return {'source': 'development-synthetic-source-' + owner, 'model': 'development-scientific-fixture-' + owner}


def comparison_targets():
    return {choice: 'development-comparison-' + choice for choice in CHOICES}


@contextmanager
def controlled_workflow_settings(base: Settings):
    """Keep provider SQL custody alive for the server; never delete supplied data."""
    _require(sys.platform == 'linux' and base.demo is True and base.development_mock_login is True
             and base.temporary_policy == 'admin-review' and not base.remote_targets
             and not base.runtime_adapters and not base.trusted_connections
             and not base.handoff_targets and not base.handoff_origins and not base.remote_binding_mappings
             and base.development_profile == 'disabled')
    root = base.workspace / 'controlled-workflows'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700)
    bindings = {}
    for owner in OWNERS:
        refs = registration_refs(owner)
        provider = pubmed_profile.PubMedProvider(owner, httpx.MockTransport(_synthetic_request))
        bindings[refs['source']] = TrustedConnectionBinding(owner, 'orx', pubmed_profile.ADAPTER_ID,
            frozenset({pubmed_profile.CAPABILITY}), PROFILE, available=True,
            opaque_handle=provider, handle_ref=PROFILE)
        bindings[refs['model']] = trusted_model_binding(owner)
    settings = replace(base, source_synthesis_enabled=True, max_workers=1, max_tool_calls=8,
        experiment_timeout_seconds=30, experiment_output_bytes=65536,
        runtime_tool_contract=PROFILE, policy_revision=PROFILE, material_policy_revision=PROFILE,
        material_review_mode='separate-admin', trusted_connections=bindings,
        runtime_adapters=[*pubmed_profile.registrations(), *comparison_profile.registrations()],
        usage_pricing=(PricingRevision(pubmed_profile.MODEL_ID, '1', 'local-deterministic',
            pubmed_profile.MODEL_ID, 'zero-local-v1', local_model_type=pubmed_profile.PubMedEvidenceModel),
            comparison_profile.pricing_registration()))
    bootstrap = Store(settings.db_url, settings)
    try:
        executable = Path(sys.executable).resolve()
        executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        pool = ComputePool('development-comparison-pool', 1, 128, 1, max_leases=1, max_owner_leases=1)
        targets = {}
        for choice, target in comparison_targets().items():
            directory = root / choice
            directory.mkdir(mode=0o700, exist_ok=True)
            provider = ProcessResourceProvider(bootstrap, directory,
                fixture_spec(str(executable), executable_hash, choice), fixture_limits())
            targets[target] = RemoteTarget('Controlled synthetic paired evaluator', 'compute', frozenset(OWNERS),
                provider=provider, synthetic_fixture=True, max_cpu=1, max_memory_mb=128,
                max_disk_mb=1, max_seconds=5, capacity_pool=pool)
        settings.remote_targets = targets
        yield settings
    finally:
        bootstrap.engine.dispose()


def _publish_materials(state, definitions):
    governance = state['material_governance']
    materials = []
    for definition in definitions:
        key = PROFILE + ':material:' + digest(definition)
        material = governance.create_draft('manager', definition, key + ':draft')
        review = governance.request_publication('manager', material['id'], material['version'], key + ':review')
        governance.decide_publication('manager2', review['id'], True, key + ':approve')
        # A replay never reactivates withdrawn material or replaces its version.
        current = governance.inspect_version('manager', material['id'], material['version'])
        _require(current['material']['published'] is True and not current['material'].get('archived')
                 and current.get('governance', {}).get('state') == 'published')
        materials.append(current['material'])
    return materials


def _publish_application(state, definition):
    applications = state['applications']
    key = PROFILE + ':application:' + digest(definition)
    application = applications.create_draft('manager', definition, key + ':draft')
    review = applications.request_publication('manager', application['id'], application['version'], key + ':review')
    applications.decide_publication('manager2', review['id'], True, key + ':approve')
    current = applications.inspect('manager', application['id'], application['version'])
    _require(current['governance']['state'] == 'published')
    return current['application']


def _source_definitions():
    rows = []
    for kind, adapter, revision in (('model', pubmed_profile.MODEL_ID, '1'),
            ('environment', pubmed_profile.ENVIRONMENT_ID, '1'), ('tool', pubmed_profile.ADAPTER_ID, pubmed_profile.REVISION)):
        rows.append({'id': PROFILE + '-source-' + kind, 'kind': kind, 'name': '开发合成来源 · ' + kind,
            'description': '仅内存合成 PubMed 协议响应，不连接真实文献服务。',
            'content': pubmed_profile.TOOL if kind == 'tool' else 'Controlled synthetic source fixture',
            'license': 'MIT', 'compatibility': ['agno:3.1.0'], 'dependencies': [],
            'permissions': [pubmed_profile.CAPABILITY] if kind == 'tool' else [],
            'runtimeBinding': {'adapterId': adapter, 'revision': revision,
                'config': {'connectionName': pubmed_profile.CONNECTION_NAME, **pubmed_profile.CONFIG} if kind == 'tool' else {}},
            'provenance': {'kind': 'original', 'notice': 'Synthetic development source records; not real PubMed retrieval.'}})
    return rows


def initialize_controlled_fixtures(state):
    """Explicit operator bootstrap through existing separate-review services."""
    settings = state['store'].settings
    _require(settings.demo is True and settings.development_mock_login is True
             and settings.runtime_tool_contract == PROFILE and settings.source_synthesis_enabled is True
             and settings.temporary_policy == 'admin-review' and settings.material_review_mode == 'separate-admin')
    state['auth'].require('manager', 'components:write')
    state['auth'].require('manager2', 'agent_os:admin')
    sources = _publish_materials(state, _source_definitions())
    source_app = _publish_application(state, {'id': pubmed_profile.APPLICATION_ID,
        'name': '开发合成文献来源（无外网）', 'description': '内存合成数据，不是实际检索或科研证据。',
        'defaultMode': 'bibliography', 'discoveryKeywords': ['合成来源', '开发来源'],
        'modes': {'bibliography': {'materialRefs': [{key: row[key] for key in ('id', 'version', 'sha256')} for row in sources],
            'capabilities': [pubmed_profile.CAPABILITY], 'toolOrder': [pubmed_profile.TOOL], 'config': {},
            'connectionRequirements': [{'name': pubmed_profile.CONNECTION_NAME, 'kind': 'orx',
                'requiredCapabilities': [pubmed_profile.CAPABILITY], 'required': True}],
            'budget': {'toolCalls': 1, 'maxDepth': 1, 'maxChildren': 1, 'experimentSeconds': 30, 'outputBytes': 65536}}}})
    synthesis_app = _publish_application(state, synthesis_runtime.application_definition(
        _publish_materials(state, synthesis_runtime.material_drafts())))
    compared = {choice: _publish_materials(state, comparison_profile.material_drafts(choice, target))
                for choice, target in comparison_targets().items()}
    comparison_app = _publish_application(state, comparison_profile.application_definition(compared))
    for owner in OWNERS:
        refs = registration_refs(owner)
        for kind, capabilities in (('source', [pubmed_profile.CAPABILITY]), ('model', [SCIENTIFIC_CAPABILITY])):
            # Stable command identity returns an existing revoked reference as
            # revoked; it cannot silently mint a replacement on restart.
            state['connections'].bind(owner, refs[kind], PROFILE + ':bind:' + owner + ':' + kind,
                                      capabilities=capabilities)
    return {'profile': PROFILE, 'applications': [source_app['id'], synthesis_app['id'], comparison_app['id']],
            'planApprovalGranted': False, 'syntheticOnly': True}
