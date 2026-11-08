"""Workspace search preserves accessible results when another entry cannot be read."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research import session_tools


class SearchResults(unittest.TestCase):
    def test_inaccessible_and_disappearing_entries_do_not_hide_matches(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            line = 'needle ' + '完整内容' * 100
            (root / 'good.txt').write_text(line, encoding='utf-8')
            (root / 'blocked').mkdir()
            (root / 'blocked' / 'inside.txt').write_text('needle', encoding='utf-8')
            (root / 'vanished.txt').write_text('needle', encoding='utf-8')
            child, entry_stat = session_tools._child_directory, session_tools._entry_stat

            @contextmanager
            def inaccessible(parent, name):
                if name == 'blocked':
                    raise PermissionError('fixture directory is unreadable')
                with child(parent, name) as descriptor:
                    yield descriptor

            def disappeared(parent, name):
                if name == 'vanished.txt':
                    raise FileNotFoundError('fixture entry disappeared during search')
                return entry_stat(parent, name)

            tools = session_tools.ResearchSessionTools()
            with patch.object(session_tools, '_child_directory', inaccessible), patch.object(session_tools, '_entry_stat', disappeared):
                partial = tools._files(root, 'research_search', {'query': 'needle'})
            self.assertEqual(partial['matches'], [{'path': 'good.txt', 'line': 1, 'text': line}])
            self.assertEqual({item['path'] for item in partial['errors']}, {'blocked', 'vanished.txt'})
            restored = tools._files(root, 'research_search', {'query': 'needle'})
            self.assertEqual({item['path'] for item in restored['matches']}, {'good.txt', 'blocked/inside.txt', 'vanished.txt'})
            self.assertEqual(restored['errors'], [])
