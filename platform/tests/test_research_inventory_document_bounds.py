"""Serialization-bound checks use inert tiny trees, not a large installation."""
import os
import unittest
from unittest.mock import patch

from agent_factory import research_bootstrap_inventory as module
import test_research_bootstrap_inventory as fixture  # pyright: ignore[reportMissingImports]


@unittest.skipUnless(os.name == 'posix', 'Descriptor inventory fixture requires POSIX')
class InventoryDocumentBoundsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.BootstrapInventoryTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def serialization(self, target, size):
        canonical = module._canonical
        def serialize(value):
            chosen = value.get('schema') == 3 if target == 'inventory' else value.get('backend') == 'pytorch-sdpa'
            return b'x' * size if chosen else canonical(value)
        return patch.object(module, '_canonical', side_effect=serialize)

    def test_exact_existing_eight_mib_limit_is_accepted_without_output_write(self):
        self.assertEqual(module.MAX_DOCUMENT_BYTES, 8 * 1024**2)
        for target in ('inventory', 'kernel'):
            with self.subTest(target=target), self.serialization(target, module.MAX_DOCUMENT_BYTES):
                result = module.build_inventory(**self.fixture.kwargs)
                self.assertEqual(len(result[target + 'Bytes']), module.MAX_DOCUMENT_BYTES)
                self.assertFalse(self.fixture.kwargs['inventory_path'].exists())

    def test_each_oversized_document_is_rejected_before_return_or_write(self):
        for target in ('inventory', 'kernel'):
            with self.subTest(target=target), self.serialization(target, module.MAX_DOCUMENT_BYTES + 1):
                with self.assertRaisesRegex(ValueError, '^RESEARCH_BOOTSTRAP_INVENTORY_INVALID$'):
                    module.build_inventory(**self.fixture.kwargs)
                self.assertFalse(self.fixture.kwargs['inventory_path'].exists())

    def test_normal_serialized_documents_are_returned_unmodified(self):
        result = module.build_inventory(**self.fixture.kwargs)
        for target in ('inventory', 'kernel'):
            self.assertEqual(result[target + 'Bytes'], module._canonical(result[target]))
            self.assertLess(len(result[target + 'Bytes']), module.MAX_DOCUMENT_BYTES)
