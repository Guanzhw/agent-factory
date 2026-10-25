"""Scientific completion requires real validated claims and physical stop."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agent_factory_research.handoff_compatibility import ResearchPreparedHandoffService
from agent_factory_research.remote_scientific_evidence import project_scientific_evidence
import test_remote_scientific_evidence as peer


class ScientificCompletionClaimTests(unittest.TestCase):
    def setUp(self):
        self.service = object.__new__(ResearchPreparedHandoffService)
        self.science = SimpleNamespace(_read=Mock(return_value={'state': 'COMPLETED'}))
        self.service._science = Mock(return_value=self.science)

    def receipt(self, phase, *, claims=True, released=True, native='completed'):
        if phase == 'preparation':
            value = peer.shell(phase)
            execution = {k: v for k, v in peer.contract()['training'].items()
                         if k not in {'checkpoint', 'variantSha256'}}
            prep = {'schema': 1, **execution, 'artifactId': 'prepared-artifact', 'artifactSha256': 'a' * 64}
            value['scientificEvidence'] = project_scientific_evidence(
                value, scope=peer.scope(phase), preparation=prep if claims else None)
        else:
            value = peer.receipt(phase, released=released, result=claims)
        value['native'] = {'run_id': value['remoteRunId'], 'session_id': value['remoteTaskId'],
            'user_id': value['remoteOwnerId'], 'agent_id': 'factory-executor', 'status': native,
            'queue': {'id': value['remoteRunId'], 'session_id': value['remoteTaskId'],
                      'user_id': value['remoteOwnerId'], 'component_id': 'factory-executor',
                      'component_type': 'agent', 'status': native}}
        return value

    def stopped(self, phase, value, *, cancel=False, raw='completed'):
        row = {'id': value['id'], 'state': 'ACCEPTED',
               'body': {'scientificEnvelope': {'scope': peer.scope(phase)}}}
        return self.service._placement_stopped(row, {'cancel_requested': cancel}, value, raw)

    def test_each_successful_phase_waits_for_its_verified_claim(self):
        for phase in ('preparation', 'training', 'evaluation'):
            with self.subTest(phase=phase):
                self.assertFalse(self.stopped(phase, self.receipt(phase, claims=False)))
                self.assertTrue(self.stopped(phase, self.receipt(phase)))

    def test_finalizing_and_unknown_cannot_bypass_success_claim_gate(self):
        for status in ('finalizing', 'unknown'):
            for phase in ('preparation', 'training', 'evaluation'):
                with self.subTest(status=status, phase=phase):
                    value = self.receipt(phase, claims=False)
                    value['applicationStatus'] = status
                    self.assertFalse(self.stopped(phase, value))

    def test_retained_complete_claims_keep_positive_stop(self):
        for phase in ('preparation', 'training', 'evaluation'):
            with self.subTest(phase=phase):
                value = self.receipt(phase)
                value['scientificClaimsRetained'] = True
                self.assertTrue(self.stopped(phase, value))

    def test_retained_claims_cannot_release_current_held_lease(self):
        for phase in ('training', 'evaluation'):
            with self.subTest(phase=phase):
                value = self.receipt(phase)
                held = self.receipt(phase, claims=False, released=False)
                value['scientificEvidence']['lease'] = held['scientificEvidence']['lease']
                value['scientificClaimsRetained'] = True
                with self.assertRaisesRegex(ValueError, 'REMOTE_SCIENTIFIC_EVIDENCE_INVALID'):
                    self.stopped(phase, value)

    def test_failed_and_canceled_native_keep_physical_stop_without_success_claims(self):
        for native, cancel in (('failed', False), ('cancelled', True), ('completed', True)):
            for phase in ('preparation', 'training', 'evaluation'):
                with self.subTest(native=native, phase=phase):
                    value = self.receipt(phase, claims=False, native=native)
                    self.assertTrue(self.stopped(phase, value, cancel=cancel, raw=native))
                    if phase != 'preparation':
                        held = self.receipt(phase, claims=False, released=False, native=native)
                        self.assertFalse(self.stopped(phase, held, cancel=cancel, raw=native))

    def test_corrupted_claim_still_rejected_with_retained_annotation(self):
        value = self.receipt('evaluation')
        original = deepcopy(value)
        value['scientificClaimsRetained'] = True
        value['scientificEvidence']['evaluation']['result']['checkpoint']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'REMOTE_SCIENTIFIC_EVIDENCE_INVALID'):
            self.stopped('evaluation', value)
        self.assertTrue(self.stopped('evaluation', original))

    def test_complete_claims_cannot_override_unfinished_phase_or_native_identity(self):
        value = self.receipt('evaluation')
        self.science._read.return_value = {'state': 'RUNNING'}
        self.assertFalse(self.stopped('evaluation', value))
        self.science._read.return_value = {'state': 'COMPLETED'}
        value['native']['queue']['id'] = 'foreign-run'
        self.assertFalse(self.stopped('evaluation', value))
