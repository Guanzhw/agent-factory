"""Opt-in reviewed local toy iterations using the existing member publication path.

This profile is installed only by a trusted local toolchain configuration. It
uses no external model/account and keeps each native ORX launch confirmation.
"""
from dataclasses import replace

from agent_factory.store import digest
from .local_orx_profile import (CONNECTION_NAME, REGISTRATION_REF, local_profile_settings,
                               publish_local_orx_application)
from .orx_experiment_tools import READ_CAPABILITY, RUN_CAPABILITY
from .orx_local import TOY_FILES
from .research_iteration_driver import ActualORXRoundDriver, IterationRoundProvider
from .research_iterations import IterationPreset, ResearchIterations

PROFILE_ID = 'local-orx-toy-iterations-v1'
ITERATION_REGISTRATION = PROFILE_ID + ':provider'


def local_iteration_profile_settings(*, db_url, workspace, provider, owner='alice', port=3104):
    settings = local_profile_settings(db_url=db_url, workspace=workspace, provider=provider, owner=owner, port=port)

    def install(state, *, research):
        store, auth, connections = state['store'], state['auth'], state['connections']
        driver = ActualORXRoundDriver(store, auth, state['bridge'], state['factory_api'].commands, research=research)
        original = settings.trusted_connections[REGISTRATION_REF]
        handle = IterationRoundProvider(research=research, driver=driver,
            binary=provider.binary, source_archive=provider.source_archive,
            git_binary=provider.git_binary, python_binary=provider.python_binary)
        trusted = replace(original, opaque_handle=handle, revision=PROFILE_ID, handle_ref=PROFILE_ID)
        # This installation's handle belongs to its service graph. Do not add
        # it to the reusable settings dictionary and restore a stale graph.
        connections.trusted_bindings = dict(connections.trusted_bindings)
        connections.trusted_bindings[ITERATION_REGISTRATION] = trusted
        with connections._write() as conn:
            connections._register(conn, ITERATION_REGISTRATION, trusted)
        application = publish_local_orx_application(state, author=owner)
        connection = connections.bind(owner, ITERATION_REGISTRATION, PROFILE_ID + ':binding',
                                      capabilities=[READ_CAPABILITY, RUN_CAPABILITY])
        pins = {'applicationRef': {key: application[key] for key in ('id', 'version', 'sha256')},
                'mode': 'success', 'connectionRefs': {CONNECTION_NAME: connection['ref']}}
        baseline = {'kind': 'reviewedSeed', 'sha256': TOY_FILES['baseline.py'], 'metricValue': 16.0,
                    'datasetSha256': TOY_FILES['dataset.json'], 'evaluatorSha256': TOY_FILES['evaluator.py']}
        caps = {'rounds': 1, 'toolCalls': 8, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        fingerprint = digest({'id': PROFILE_ID, 'owner': owner, 'pins': pins, 'baseline': baseline,
                              'roundCaps': caps, 'roundSeconds': 90, 'policy': 'strict-improvement-v1'})
        preset = IterationPreset(PROFILE_ID, owner, fingerprint, pins, baseline, caps, 90)
        return ResearchIterations(store, auth, research=research, presets={PROFILE_ID: preset}, round_driver=driver)

    settings.research_iterations_factory = install
    return settings
