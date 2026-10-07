# pyright: reportMissingImports=false
"""Deterministic read interleavings with real process/GPU validators, no effects."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from agent_factory.process_runtime import ProcessRuntimeService
from agent_factory.resources import PersistentResourceService
from test_remote_scientific_evidence import lease as scientific_lease


class ProcessRuntimeReadRaceTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, *, terminal=True, rotate=False, fresh_binding=False):
        initial = scientific_lease()
        fresh = scientific_lease(released=True) if terminal else deepcopy(initial)
        if fresh_binding:
            fresh['processBinding']['bindingFingerprint'] = 'e' * 64
        snapshot = deepcopy(initial)
        snapshot.update(leaseId=initial['id'], released=False)
        target = object()
        state = {'lease': initial, 'target': target}
        async def inspect(lease_id, owner):
            self.assertEqual((lease_id, owner), (initial['id'], initial['ownerId']))
            await asyncio.sleep(0)
            # Another observer commits before this older response returns.
            state.update(lease=fresh, target=object() if rotate else target)
            return snapshot
        update = Mock(return_value={'updated': True})
        resources = SimpleNamespace(_provider=lambda _: SimpleNamespace(inspect=inspect),
            process_snapshot=PersistentResourceService.process_snapshot, _update=update)
        service: Any = object.__new__(ProcessRuntimeService)
        service.resources = resources
        service._custody = lambda _: (state['lease'], state['target'], {}, {})
        return service, initial, fresh, snapshot, update

    async def test_stale_valid_held_snapshot_returns_original_reclaimed_without_write(self):
        service, initial, fresh, snapshot, update = self.fixture()
        # Reproduce the actual GPU monotonicity failure of applying an old
        # otherwise valid response directly to already released custody.
        PersistentResourceService.process_snapshot(initial, snapshot)
        with self.assertRaises(ValueError):
            PersistentResourceService.process_snapshot(fresh, snapshot)
        before = deepcopy(fresh)
        result = await service._read(initial['id'])
        self.assertIs(result, fresh)
        self.assertEqual(fresh, before)
        update.assert_not_called()

    async def test_terminal_race_does_not_hide_foreign_or_corrupt_snapshot(self):
        for field, value in (('providerJobId', 'foreign'), ('fingerprint', 'f' * 64),
                             ('gpuEvidence', {'state': 'HELD'})):
            with self.subTest(field=field):
                service, initial, _, snapshot, update = self.fixture()
                snapshot[field] = value
                with self.assertRaises(ValueError): await service._read(initial['id'])
                update.assert_not_called()

    async def test_terminal_race_does_not_hide_invalid_provider_state(self):
        service, initial, _, snapshot, update = self.fixture()
        snapshot['state'] = 'invented-state'
        with self.assertRaises((ValueError, HTTPException)):
            await service._read(initial['id'])
        update.assert_not_called()

    async def test_target_rotation_is_rejected_even_after_valid_release(self):
        service, initial, _, _, update = self.fixture(rotate=True)
        with self.assertRaises(HTTPException): await service._read(initial['id'])
        update.assert_not_called()

    async def test_active_fresh_identity_is_still_revalidated(self):
        service, initial, _, snapshot, update = self.fixture(terminal=False, fresh_binding=True)
        PersistentResourceService.process_snapshot(initial, snapshot)
        with self.assertRaises(ValueError): await service._read(initial['id'])
        update.assert_not_called()

    async def test_active_unchanged_custody_keeps_normal_update(self):
        service, initial, _, _, update = self.fixture(terminal=False)
        self.assertEqual(await service._read(initial['id']), {'updated': True})
        update.assert_called_once()
        self.assertEqual(update.call_args.args[:3], (initial['ownerId'], initial['id'], 'RUNNING'))
        self.assertEqual(update.call_args.args[3]['gpuEvidence']['state'], 'HELD')
