"""Read-only synthetic interpreter identities; no interpreter or ML execution."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_factory.research_interpreter import capture_interpreter_contract, open_interpreter, recheck_interpreter, validate_interpreter_contract


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'POSIX nofollow required')
class InterpreterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project'; self.project.mkdir()
        self.venv = self.project / '.venv'; self.venv.mkdir()
        (self.venv / 'bin').mkdir()
        self.approved = self.root / 'approved'; self.approved.mkdir()
        self.target = self.approved / 'python-real'
        self.target.write_bytes(b'synthetic executable bytes; NEVER EXECUTED'); self.target.chmod(0o755)
        self.sha = hashlib.sha256(self.target.read_bytes()).hexdigest()
        self.link = self.venv / 'bin' / 'python'; self.link.symlink_to(self.target)
        self.cfg = self.venv / 'pyvenv.cfg'; self.cfg.write_text('home = synthetic\nuv = 0.12.19\n')
        self.project_file = self.project / 'pyproject.toml'; self.project_file.write_text('[project]\nname="synthetic"\n')
        self.lock = self.project / 'uv.lock'; self.lock.write_text('version = 1\n')
        self.inventory = self.project / 'inventory.json'; self.inventory.write_text('{"synthetic":true}')
        self.package = self.venv / 'empty.py'; self.package.touch()

    def capture(self, **kwargs):
        return capture_interpreter_contract(executable=str(self.link), sha256=self.sha,
            project_root=self.project, venv_root=self.venv, approved_interpreter_roots=[self.approved],
            pyvenv_cfg=self.cfg, pyproject_toml=self.project_file, uv_lock=self.lock,
            package_inventory=self.inventory, package_files=[self.package], **kwargs)

    def test_same_fd_and_zero_byte_package_are_verified_without_execution(self):
        raw = self.capture()
        value = validate_interpreter_contract(raw, str(self.link), self.sha)
        self.assertEqual(value['packageFiles'][0]['sizeBytes'], 0)
        self.assertEqual(value['target']['path'], str(self.target))
        self.assertEqual(value['links'][0]['target'], str(self.target))
        fd = open_interpreter(raw, str(self.link), self.sha)
        try:
            self.assertEqual(os.read(fd, 4096), self.target.read_bytes())
            recheck_interpreter(raw, str(self.link), self.sha, fd)
            self.assertEqual(os.lseek(fd, 0, os.SEEK_CUR), 0)
        finally:
            os.close(fd)

    def test_shape_validation_is_no_filesystem_and_rejects_noncanonical_duplicate_unknown(self):
        raw = self.capture()
        with patch('os.open', side_effect=AssertionError('NO_FILESYSTEM')):
            validate_interpreter_contract(raw, str(self.link), self.sha)
        invalid = [raw + ' ', raw[:-1] + ',"schema":1}', canonical(json.loads(raw) | {'unknown': 1}),
            raw.replace('"schema":1', '"schema":true'), raw.replace('"schema":1', '"schema":NaN')]
        for item in invalid:
            with self.subTest(item=invalid.index(item)), self.assertRaisesRegex(ValueError, '^RESEARCH_INTERPRETER_INVALID$'):
                validate_interpreter_contract(item, str(self.link), self.sha)

    def test_relative_link_chain_only_and_cycle_escape_rejected(self):
        self.link.unlink(); self.link.symlink_to('python3')
        middle = self.link.with_name('python3'); middle.symlink_to(self.target)
        raw = self.capture(); self.assertEqual(len(json.loads(raw)['links']), 2)
        middle.unlink(); middle.symlink_to('python')
        with self.assertRaises(ValueError): self.capture()
        middle.unlink(); middle.symlink_to(self.root / 'outside')
        (self.root / 'outside').write_bytes(self.target.read_bytes()); (self.root / 'outside').chmod(0o755)
        with self.assertRaises(ValueError): self.capture()

    def test_more_than_eight_links_are_rejected(self):
        self.link.unlink()
        previous = self.link
        for index in range(8):
            nxt = self.link.with_name('link' + str(index)); previous.symlink_to(nxt); previous = nxt
        previous.symlink_to(self.target)
        with self.assertRaises(ValueError): self.capture()

    def test_intermediate_directory_symlink_is_not_approved_link(self):
        directory = self.venv / 'bin'; directory.rename(self.venv / 'real-bin')
        directory.symlink_to(self.venv / 'real-bin', target_is_directory=True)
        with self.assertRaises(ValueError): self.capture()

    def test_same_content_target_replacement_denies_even_with_held_original_fd(self):
        raw = self.capture(); fd = open_interpreter(raw, str(self.link), self.sha)
        try:
            old = self.target.read_bytes(); self.target.rename(self.approved / 'old')
            self.target.write_bytes(old); self.target.chmod(0o755)
            self.assertEqual(os.read(fd, 4096), old)
            with self.assertRaises(ValueError): recheck_interpreter(raw, str(self.link), self.sha, fd)
        finally: os.close(fd)

    def test_link_replacement_same_literal_and_parent_replacement_deny(self):
        raw = self.capture(); self.link.unlink(); self.link.symlink_to(self.target)
        with self.assertRaises(ValueError): open_interpreter(raw, str(self.link), self.sha)
        raw = self.capture()
        self.venv.rename(self.project / 'old-venv'); self.venv.mkdir(); (self.venv / 'bin').mkdir()
        self.link.symlink_to(self.target)
        with self.assertRaises(ValueError): open_interpreter(raw, str(self.link), self.sha)

    def test_every_configuration_or_package_change_denies(self):
        for path in (self.cfg, self.project_file, self.lock, self.inventory, self.package):
            with self.subTest(path=path.name):
                raw = self.capture(); prior = path.read_bytes(); path.write_bytes(prior + b'x')
                with self.assertRaises(ValueError): open_interpreter(raw, str(self.link), self.sha)
                path.write_bytes(prior)

    def test_hardlink_writable_target_and_fifo_denied(self):
        other = self.approved / 'alias'; os.link(self.target, other)
        with self.assertRaises(ValueError): self.capture()
        other.unlink(); self.target.chmod(0o777)
        with self.assertRaises(ValueError): self.capture()
        self.target.unlink(); getattr(os, "mkfifo")(self.target)
        with self.assertRaises(ValueError): self.capture()

    def test_missing_posix_capability_denies_without_follow_fallback(self):
        raw = self.capture()
        for flag in ('O_NOFOLLOW', 'O_DIRECTORY', 'O_NONBLOCK'):
            with self.subTest(flag=flag), patch.object(os, flag, 0), self.assertRaises(ValueError):
                open_interpreter(raw, str(self.link), self.sha)

    def test_swap_during_evidence_scan_is_detected_by_final_recheck(self):
        import agent_factory.research_interpreter as module
        raw = self.capture(); original = module._hash_fd; swapped = False
        def swap(fd, size):
            nonlocal swapped
            result = original(fd, size)
            if not swapped and size == self.target.stat().st_size:
                swapped = True; self.cfg.write_bytes(self.cfg.read_bytes() + b'x')
            return result
        with patch.object(module, '_hash_fd', side_effect=swap), self.assertRaises(ValueError):
            open_interpreter(raw, str(self.link), self.sha)

    def test_boundaries_wrong_arguments_and_forged_path_denied(self):
        raw = self.capture()
        for executable, sha in ((str(self.target), self.sha), (str(self.link), '0' * 64)):
            with self.assertRaises(ValueError): validate_interpreter_contract(raw, executable, sha)
        value = json.loads(raw); value['target']['path'] = str(self.root / 'escape')
        with self.assertRaises(ValueError): validate_interpreter_contract(canonical(value), str(self.link), self.sha)
        with self.assertRaises(ValueError): validate_interpreter_contract('x' * (2 * 1024 * 1024 + 1), str(self.link), self.sha)
        value = json.loads(raw); value['packageFiles'][0]['sizeBytes'] = 1024**3 + 1
        with self.assertRaises(ValueError): validate_interpreter_contract(canonical(value), str(self.link), self.sha)

    def test_package_count_above_256_and_total_bounds_are_shape_checked(self):
        value = json.loads(self.capture()); original = value['packageFiles'][0]
        value['packageFiles'] = [{**original, 'path': str(self.venv / ('package' + str(index)))} for index in range(300)]
        validate_interpreter_contract(canonical(value), str(self.link), self.sha)
        value['packageFiles'] = value['packageFiles'][:9]
        for pin in value['packageFiles']:
            pin['sizeBytes'] = 1024**3
        with self.assertRaises(ValueError): validate_interpreter_contract(canonical(value), str(self.link), self.sha)

    def test_wrong_held_fd_and_post_scan_link_swap_deny(self):
        import agent_factory.research_interpreter as module
        raw = self.capture(); fd = os.open(self.cfg, os.O_RDONLY)
        try:
            with self.assertRaises(ValueError): recheck_interpreter(raw, str(self.link), self.sha, fd)
        finally: os.close(fd)
        original = module._read_pin
        def swap(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == str(self.target):
                self.link.unlink(); self.link.symlink_to(self.target)
            return result
        with patch.object(module, '_read_pin', side_effect=swap), self.assertRaises(ValueError):
            open_interpreter(raw, str(self.link), self.sha)

    def test_dotdot_cannot_skip_unverified_symlink_or_real_parent_component(self):
        raw = self.capture()
        outside = self.root / 'outside'; outside.mkdir()
        nested = outside / 'nested'; nested.mkdir()
        escaped_target = outside / self.target.name
        escaped_target.write_bytes(b'different outside bytes'); escaped_target.chmod(0o755)
        escape = self.approved / 'escape'; escape.symlink_to(nested, target_is_directory=True)
        literal = str(escape) + '/../' + self.target.name
        # The OS path resolves outside, while lexical normalization would point
        # at the approved target. Both shape validation and capture must deny.
        self.assertEqual(Path(literal).read_bytes(), b'different outside bytes')
        value = json.loads(raw); value['links'][0]['target'] = literal
        with self.assertRaises(ValueError): validate_interpreter_contract(canonical(value), str(self.link), self.sha)
        self.link.unlink(); self.link.symlink_to(literal)
        with self.assertRaises(ValueError): self.capture()
        escape.unlink(); escape.mkdir()
        with self.assertRaises(ValueError): self.capture()
        value['links'][0]['target'] = '../bin/python'
        with self.assertRaises(ValueError): validate_interpreter_contract(canonical(value), str(self.link), self.sha)

    def test_trailing_directory_syntax_rejected_but_leading_dot_relative_supported(self):
        raw = self.capture()
        for suffix in ('/', '/.'):
            value = json.loads(raw); value['links'][0]['target'] = str(self.target) + suffix
            with self.assertRaises(ValueError): validate_interpreter_contract(canonical(value), str(self.link), self.sha)
            self.link.unlink(); self.link.symlink_to(str(self.target) + suffix)
            with self.assertRaises(ValueError): self.capture()
        self.link.unlink(); self.link.symlink_to('./python3')
        self.link.with_name('python3').symlink_to(self.target)
        self.assertEqual(len(json.loads(self.capture())['links']), 2)

    def test_namespace_rejects_new_inert_pth_shadow_module_and_directory(self):
        for name, directory in (('evil.pth', False), ('shadow.so', False), ('new-package', True)):
            with self.subTest(name=name):
                raw = self.capture(); addition = self.venv / name
                if directory: addition.mkdir()
                else: addition.write_text('# inert fixture, never imported')
                with self.assertRaises(ValueError): open_interpreter(raw, str(self.link), self.sha)
                if directory: addition.rmdir()
                else: addition.unlink()

    def test_namespace_existing_unselected_comment_pth_change_and_replacement_deny(self):
        startup = self.venv / 'comments.pth'; startup.write_text('# original comment')
        raw = self.capture(); startup.write_text('# replaced comment')
        with self.assertRaises(ValueError): open_interpreter(raw, str(self.link), self.sha)
        raw = self.capture(); saved = startup.read_bytes(); startup.unlink(); startup.write_bytes(saved)
        with self.assertRaises(ValueError): open_interpreter(raw, str(self.link), self.sha)

    def test_namespace_is_exact_pinned_venv_scope_not_general_ancestor(self):
        raw = self.capture(); value = json.loads(raw)
        paths = [pin['path'] for pin in value['namespaces']]
        self.assertEqual(paths, sorted([str(self.venv), str(self.venv / 'bin')]))
        (self.project / 'outside-venv-cache').mkdir()
        fd = open_interpreter(raw, str(self.link), self.sha); os.close(fd)
        for mutation in ('missing', 'extra', 'count', 'hash'):
            broken = json.loads(raw)
            if mutation == 'missing': broken['namespaces'].pop()
            elif mutation == 'extra': broken['namespaces'].append({'path': str(self.project), 'entryCount': 0, 'entriesSha256': '0'*64})
            elif mutation == 'count': broken['namespaces'][0]['entryCount'] = 32769
            else: broken['namespaces'][0]['entriesSha256'] = True
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_interpreter_contract(canonical(broken), str(self.link), self.sha)

    def test_namespace_late_addition_after_file_scan_is_rejected(self):
        import agent_factory.research_interpreter as module
        raw = self.capture(); original = module._read_pin
        def mutate(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == str(self.target): (self.venv / 'late.pth').write_text('# inert')
            return result
        with patch.object(module, '_read_pin', side_effect=mutate), self.assertRaises(ValueError):
            open_interpreter(raw, str(self.link), self.sha)

    def test_namespace_post_gate_held_fd_recheck_rejects_shadow_addition(self):
        raw = self.capture(); fd = open_interpreter(raw, str(self.link), self.sha)
        try:
            (self.venv / 'shadow.py').write_text('# never imported')
            with self.assertRaises(ValueError): recheck_interpreter(raw, str(self.link), self.sha, fd)
        finally: os.close(fd)

    def test_namespace_entry_count_bound_fails_closed_without_full_enumeration(self):
        import agent_factory.research_interpreter as module
        value = json.loads(self.capture()); directories = {pin['path']: pin for pin in value['directories']}
        with self.assertRaises(ValueError): module._namespace_pin(str(self.venv), directories, 1)

    def test_namespace_removed_original_entry_is_rejected(self):
        extra = self.venv / 'optional.py'; extra.write_text('# inert existing file')
        raw = self.capture(); extra.unlink()
        with self.assertRaises(ValueError): open_interpreter(raw, str(self.link), self.sha)
