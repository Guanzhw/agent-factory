"""Original scientific bytes remain pinned independently of control-plane imports.

Only disposable Python source bytes are copied/hashed; none are imported/executed.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_factory import research_local_driver as subject
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.research_staging import RootIdentity, pin_bytes
import test_research_local_driver as fixture  # pyright: ignore[reportMissingImports]


@unittest.skipUnless(os.name == 'posix', 'Descriptor-pinned POSIX scientific package')
class ScientificRuntimePinTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.LocalDriverTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.package = self.fixture.root / 'sealed-venv' / 'site-packages' / 'agent_factory'
        self.package.mkdir(mode=0o700, parents=True)
        source = Path(subject.__file__).parent
        pins = []
        for name in subject._RUNTIME_FILES:
            raw = (source / name).read_bytes()
            if name == 'store.py':
                raw = b'# synthetic previously sealed store; never imported\n'
            path = self.package / name
            path.write_bytes(raw); path.chmod(0o600)
            pins.append(pin_bytes(name, raw))
        self.pin = subject.ScientificRuntimePin(str(self.package), RootIdentity(**fixture.identity(self.package)), tuple(pins))

    def adopt_science_manifest(self):
        values = subject.derive_local_identities({}, {}, scientific_runtime=self.pin)['identities']
        f = self.fixture
        f.variant = values['baseline']['sha256']
        f.manifest['baselineSourceManifestSha256'] = f.variant
        f.manifest['evaluator']['code'] = f.artifact(values['evaluatorCode'])
        f.manifest['evaluator']['configuration'] = f.artifact(values['evaluatorConfiguration'])
        f.record['binding']['executionGuard'] = {'manifestSha256': manifest_fingerprint(f.manifest),
                                                'variantSha256': f.variant}
        return values

    def test_explicit_pin_roundtrip_and_legacy_none_fingerprint_unchanged(self):
        self.assertEqual(subject.ScientificRuntimePin.from_dict(self.pin.to_dict()), self.pin)
        self.assertEqual(subject._runtime_pins(self.pin), self.pin.files)
        self.assertEqual(self.fixture.driver().configuration_fingerprint,
                         self.fixture.driver(scientific_runtime=None).configuration_fingerprint)
        self.adopt_science_manifest()
        selected = self.fixture.driver(scientific_runtime=self.pin)
        self.assertEqual(selected._runtime, self.pin.files)
        with self.assertRaises(ValueError):
            self.fixture.driver()  # New control-plane source cannot impersonate old science.

    def test_declared_commitments_equal_separately_verified_sealed_runtime(self):
        verified = subject.derive_local_identities({}, {}, scientific_runtime=self.pin)
        with patch.object(subject, '_runtime_pins', side_effect=AssertionError('no file access')):
            declared = subject.derive_declared_local_identities({}, {}, runtime_file_pins=self.pin.files)
        self.assertEqual(declared['identities'], verified['identities'])
        self.assertEqual(declared['adaptationReceipt'], verified['adaptationReceipt'])
        self.assertFalse(declared['runtimeBytesVerified'])
        self.assertFalse(declared['executionVerified'])

    def test_original_installed_driver_identity_survives_new_controller_location(self):
        self.adopt_science_manifest()
        # Historical default resolved its own installed package. Reopening that
        # same science via an explicit pin must not change lease/provider identity.
        with patch.object(subject, '__file__', str(self.package / 'research_local_driver.py')):
            original = self.fixture.driver()
        restored = self.fixture.driver(scientific_runtime=self.pin)
        self.assertEqual(restored.configuration_fingerprint, original.configuration_fingerprint)
        self.assertEqual(restored._runtime, original._runtime)
        self.assertEqual(restored._runtime_package, original._runtime_package)

    def test_selected_science_identity_and_observer_request_use_same_old_package(self):
        values = self.adopt_science_manifest()
        observed = []
        class Observer(fixture.FixtureObserver):
            def __call__(self, request):
                observed.append(deepcopy(request))
                return super().__call__(request)
        driver = self.fixture.driver(scientific_runtime=self.pin, environment_verifier=Observer())
        result = driver(self.fixture.record)
        self.assertEqual(result['variantSha256'], values['baseline']['sha256'])
        self.assertEqual(observed[0]['trustedRuntimePackage'], str(self.package))
        self.assertEqual(observed[0]['trustedRuntimeFiles'], self.pin.to_dict()['files'])
        # Changing the executing module's location cannot redirect explicit science.
        with patch.object(subject, '__file__', str(self.fixture.root / 'other-control' / 'research_local_driver.py')):
            self.assertEqual(subject.derive_local_identities({}, {}, scientific_runtime=self.pin)['identities'], values)

    def test_runtime_bytes_drift_stops_before_reservation_and_does_not_repin(self):
        self.adopt_science_manifest()
        driver = self.fixture.driver(scientific_runtime=self.pin)
        original = self.pin.to_dict()
        (self.package / 'store.py').write_bytes(b'# changed bytes\n')
        with self.assertRaises(subject.ResearchDriverFailure) as caught:
            driver(self.fixture.record)
        self.assertEqual(caught.exception.phase, 'binding-validation')
        self.assertEqual(self.fixture.reservation.bindings, [])
        self.assertEqual(self.pin.to_dict(), original)

    def test_new_control_plane_generator_cannot_reinterpret_old_baseline(self):
        self.adopt_science_manifest()
        bundle = self.fixture.bundle
        bundle['generatedFiles']['train_baseline.py'] = b'# changed generator output; never executed\n'
        bundle['receipt']['generatedSha256']['train_baseline.py'] = hashlib.sha256(
            bundle['generatedFiles']['train_baseline.py']).hexdigest()
        with self.assertRaises(ValueError):
            self.fixture.driver(scientific_runtime=self.pin)
        self.assertEqual(self.fixture.reservation.bindings, [])

    def test_replaced_directory_symlink_and_hardlink_are_not_adopted(self):
        original = self.package / 'store.py'
        original.rename(self.package / 'retained-original')
        original.symlink_to(self.package / 'retained-original')
        with self.assertRaises((ValueError, OSError)):
            subject._runtime_pins(self.pin)
        original.unlink()
        os.link(self.package / 'retained-original', original)
        with self.assertRaises((ValueError, OSError)):
            subject._runtime_pins(self.pin)
        original.unlink()
        (self.package / 'retained-original').rename(original)
        wrong_root = replace(self.pin, root_identity=RootIdentity(self.pin.root_identity.device,
                                                                self.pin.root_identity.inode + 1))
        with self.assertRaises(ValueError):
            subject._runtime_pins(wrong_root)

    def test_snapshot_schema_and_exact_file_closure_are_strict(self):
        for field, value in (('schema', True), ('kind', 'arbitrary'), ('packageRoot', '/tmp/other'),
                             ('files', self.pin.to_dict()['files'][:-1])):
            snapshot = self.pin.to_dict(); snapshot[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                subject.ScientificRuntimePin.from_dict(snapshot)
        with self.assertRaises(ValueError):
            replace(self.pin, files=tuple(reversed(self.pin.files)))
        with self.assertRaises(ValueError):
            replace(self.pin, root_identity=RootIdentity(True, 1))
        different = replace(self.pin, files=(replace(self.pin.files[0], sha256='0' * 64), *self.pin.files[1:]))
        with self.assertRaises(ValueError):
            subject._runtime_pins(different)


class DeclaredRuntimePinTests(unittest.TestCase):
    def test_invalid_or_incomplete_pin_declarations_fail_before_source_generation(self):
        pins = tuple(pin_bytes(name, b'synthetic') for name in subject._RUNTIME_FILES)
        forged = object.__new__(subject.FilePin)
        object.__setattr__(forged, 'basename', pins[0].basename)
        object.__setattr__(forged, 'sha256', 'not-a-sha256')
        object.__setattr__(forged, 'size_bytes', 9)
        invalid = (pins[:-1], pins + (pins[-1],), tuple(reversed(pins)), list(pins),
                   (forged, *pins[1:]), (replace(pins[0], size_bytes=4 * 1024**2 + 1), *pins[1:]),
                   (replace(pins[0], basename='unapproved.py'), *pins[1:]))
        with patch.object(subject, 'build_training_bundle') as build, \
             patch.object(subject, '_runtime_pins', side_effect=AssertionError('no file access')):
            for value in invalid:
                with self.subTest(value_type=type(value).__name__), self.assertRaisesRegex(ValueError, subject.ERROR):
                    subject.derive_declared_local_identities({}, {}, runtime_file_pins=value)
            build.assert_not_called()
