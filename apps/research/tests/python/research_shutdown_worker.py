"""Owned shutdown acceptance worker; invokes the real deployment entrypoint.

Only settings, the inert runtime and observations are fixture-specific. The
production fatal shutdown handler, native queue and lifespan remain unchanged.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import patch

from agent_factory_research.autoresearch import ResearchPreset
from agent_factory_research.config import ResearchSettings
from agent_factory_research.services import services_for
import agent_factory_research.assembly as assembly
import agent_factory_server.main as deployment


def main():
    config = json.loads(Path(os.environ['FACTORY_SHUTDOWN_FIXTURE']).read_text())
    root = Path(config['workspace'])
    generation = config['generation']
    events = root / f'events-{generation}.jsonl'

    def record(event, **details):
        with events.open('a') as output:
            output.write(json.dumps({'event': event, 'time': time.monotonic(), **details}) + '\n')

    source = Path(__file__).resolve().parents[4] / 'scripts/bootstrap_autoresearch.py'
    spec = importlib.util.spec_from_file_location('shutdown_bootstrap', source)
    assert spec and spec.loader
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)

    class Runtime:
        def __init__(self, ctx):
            self.ctx = ctx
            self.graph = services_for(ctx.store)
            self.identity = {'taskId': ctx.run_context.session_id,
                             'runId': ctx.run_context.run_id, 'ownerId': ctx.run_context.user_id}

        async def run(self):
            # The test parent owns this actual process across server restarts.
            # This command is its single business dispatch, not process creation.
            with (root / 'dispatches.jsonl').open('a') as output:
                output.write(json.dumps(self.identity) + '\n')
            (root / 'child-command.json').write_text(json.dumps(self.identity))
            deadline = time.monotonic() + 10
            while not (root / 'child-started.json').exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError('CONTROLLED_CHILD_START_TIMEOUT')
                await asyncio.sleep(.05)
            record('runtime-started', **self.identity)
            if config['scenario'] == 'active':
                # Cancellation through the real controller ends this wait.
                async with asyncio.timeout(120):
                    await asyncio.Event().wait()
            return {'evidenceMode': 'controlled-process', 'modelExecuted': False}

        async def stop(self):
            record('cleanup-entered', **self.identity)
            if config['scenario'] == 'slow':
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    # Exercise actual consumers throughout the 35s close wait.
                    same_graph = services_for(self.ctx.store) is self.graph
                    self.ctx.store.sql('SELECT 1')
                    record('cleanup-dependency-read', sameGraph=same_graph)
                    if not same_graph:
                        raise AssertionError('CLEANUP_GRAPH_REPLACED')
                    await asyncio.sleep(.5)
            (root / 'child-stop.json').write_text(json.dumps(self.identity))
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if (root / 'child-stopped.json').exists():
                    proof = json.loads((root / 'child-stopped.json').read_text())
                    if proof != self.identity:
                        raise AssertionError('CONTROLLED_CHILD_STOP_IDENTITY_CHANGED')
                    record('cleanup-confirmed', **self.identity)
                    return True
                await asyncio.sleep(.05)
            return False

        async def cancel(self):
            # Cancellation acknowledgment cannot stand in for stop proof.
            record('runtime-cancel-requested', **self.identity)

    async def forbidden_experiment(*_args):
        raise AssertionError('No model or scientific experiment is authorized')

    preset = ResearchPreset(id='shutdown-original-process', name='Controlled shutdown process',
        default_goal='Verify original process custody across service shutdown', owner_id='alice',
        instructions='Inert local process only; no inference or scientific conclusions.',
        manifest={'schema': 1, 'evidenceMode': 'controlled-process'},
        limits={'totalSeconds': 180, 'experimentSeconds': 30, 'maxExperiments': 1,
                'toolCalls': 32, 'outputBytes': 65536},
        runtime_factory=lambda ctx, _service: Runtime(ctx), context_reader=lambda: {},
        candidate_validator=lambda _: {}, experiment=forbidden_experiment, external_session=True)
    settings = bootstrap.settings(db_url=config['database'], workspace=root, preset=preset)
    # Same explicit controlled accounting seam as the external-session PG test.
    settings.fee_management_enabled = settings.platform_paid_models_enabled = True
    settings.port = config['port']
    settings.max_user_tasks = settings.max_total_tasks = 1
    settings.storage_low_water_bytes = 1
    original_create = deployment.create_app
    original_release = assembly.release_services

    def observe_app(*args, **kwargs):
        app = original_create(*args, **kwargs)
        state = deployment.factory_state(app)
        store = state['store']
        graph = services_for(store)
        published = bootstrap.publish_application(state, preset, author='alice')
        state['settings'].autoresearch_presets[published.id] = published
        graph.autoresearch.presets[published.id] = published
        # No scientific child is requested. Readiness requires this trusted seam,
        # as in the existing external-session native queue acceptance fixture.
        graph.autoresearch_children = SimpleNamespace()

        def pending():
            control = graph.autoresearch_session_control
            tasks = [*control.active.values(), *control.failures.values(),
                     *graph.autoresearch.executions.values(),
                     *graph.autoresearch.cleanups.values()]
            return sum(not task.done() for task in tasks)

        control = graph.autoresearch_session_control
        original_close = control.close

        async def observe_control_close(*close_args, **close_kwargs):
            record('shutdown-entered', pending=pending())
            result = await original_close(*close_args, **close_kwargs)
            record('controller-close-returned', complete=result, pending=pending())
            return result

        control.close = observe_control_close
        for owner, attribute, label in ((store, 'dispose_root_locks', 'root-locks'),
                (store.application_environments, 'close', 'application-environments'),
                (store.personal_ssh, 'close', 'personal-ssh')):
            if owner is None:
                continue
            original = getattr(owner, attribute)

            def observed(*close_args, _original=original, _label=label, **close_kwargs):
                record('dependency-close', dependency=_label, pending=pending())
                return _original(*close_args, **close_kwargs)

            setattr(owner, attribute, observed)

        def observe_release(released_store):
            record('graph-release', pending=pending(), sameGraph=services_for(released_store) is graph)
            return original_release(released_store)

        assembly.release_services = observe_release
        record('application-created')
        return app

    # Call the actual production main: do not supply a fixture fatal callback or
    # replace Uvicorn. Patching settings avoids access to host configuration.
    with patch.object(ResearchSettings, 'from_env', return_value=settings), \
            patch.object(deployment, 'create_app', side_effect=observe_app):
        deployment.main()
    record('production-main-returned')


if __name__ == '__main__':
    main()
