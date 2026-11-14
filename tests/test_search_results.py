"""Native grep can inspect an absolute research directory outside its default cwd."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from agno.tools.coding import CodingTools


class SearchResults(unittest.TestCase):
    def test_external_file_search(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'session').mkdir()
            target = root / 'PROTOCOL.md'
            target.write_text('research needle', encoding='utf-8')
            tools = CodingTools(base_dir=root / 'session', restrict_to_base_dir=False, enable_grep=True)
            self.assertIn('research needle', tools.grep('needle', str(target)))
