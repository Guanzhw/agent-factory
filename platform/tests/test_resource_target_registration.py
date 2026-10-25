"""Rebuilt SSH targets retain original capacity and member boundaries."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from agent_factory.resources import ComputePool, PersistentResourceService, RemoteTarget


def provider(pin='a' * 64, namespace='b' * 64):
    return SimpleNamespace(configuration_fingerprint=pin, capacity_namespace=namespace)


def target(actor='alice', **changes):
    return replace(RemoteTarget('SSH training', 'compute', frozenset({actor}),
        provider=provider(), capacity_pool=ComputePool('same-host', 2, 2048, 1024)), **changes)


class TargetRegistrationTests(unittest.TestCase):
    def test_equivalent_rebuilt_provider_preserves_original_object(self):
        original = target()
        service = PersistentResourceService(Mock(), Mock(), {'original': original})
        self.assertIs(service.register_target('original', target()), original)
        self.assertIs(service._authorize('alice', 'original'), original)
        with self.assertRaises(HTTPException):
            service._authorize('bob', 'original')

    def test_original_target_cannot_change_owner_host_or_limits(self):
        service = PersistentResourceService(Mock(), Mock(), {'original': target()})
        for changed in (target(actor='bob'), target(provider=provider(pin='c' * 64)),
                        target(max_seconds=301), target(capacity_pool=ComputePool('other', 2, 2048, 1024))):
            with self.subTest(target=changed), self.assertRaises(ValueError):
                service.register_target('original', changed)

    def test_aliases_cannot_split_or_redefine_capacity(self):
        service = PersistentResourceService(Mock(), Mock(), {'alice': target()})
        service.register_target('bob', target(actor='bob'))
        for changed in (target(capacity_pool=ComputePool('split', 2, 2048, 1024)),
                        target(capacity_pool=ComputePool('same-host', 4, 2048, 1024)),
                        target(capacity_pool=None)):
            with self.subTest(target=changed), self.assertRaises(ValueError):
                service.register_target('alias', changed)
        self.assertEqual(set(service.targets), {'alice', 'bob'})

    def test_missing_target_restores_original_without_new_launch(self):
        service = PersistentResourceService(Mock(), Mock(), {})
        service.ssh_targets = Mock()
        service.ssh_targets.restore_target.side_effect = lambda owner, ref: service.register_target(ref, target())
        restored = service._authorize('alice', 'original')
        self.assertIs(restored, service.targets['original'])
        service.ssh_targets.restore_target.assert_called_once_with('alice', 'original')
        self.assertIs(service._authorize('alice', 'original'), restored)
        service.ssh_targets.restore_target.assert_called_once()

    def test_failed_reconstruction_does_not_register_or_authorize(self):
        service = PersistentResourceService(Mock(), Mock(), {})
        service.ssh_targets = Mock()
        service.ssh_targets.restore_target.side_effect = HTTPException(409, 'ORIGINAL_CONNECTION_CHANGED')
        with self.assertRaises(HTTPException) as caught:
            service._authorize('alice', 'original')
        self.assertEqual(caught.exception.detail, 'ORIGINAL_CONNECTION_CHANGED')
        self.assertEqual(service.targets, {})
