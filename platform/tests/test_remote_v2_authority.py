"""Explicit authority versions preserve v1 wire and never infer from time keys."""
from copy import deepcopy
import unittest
import json
from unittest.mock import patch
from pydantic import ValidationError
from agent_factory.remote_authority import AuthorityReply, AuthorityScope, AuthorityScopeV2, OriginAuthorityTransport


class RemoteV2AuthorityTests(unittest.TestCase):
    def reply(self, version=1):
        scope = {"capabilities": ["checksum:read"], "tools": ["checksum"],
                 "budget": {"toolCalls": 8, "maxDepth": 2, "maxChildren": 4,
                            "experimentSeconds" if version == 1 else "operationSeconds": 8,
                            "outputBytes": 65536}, "usageGrantSha256": None}
        if version == 2:
            scope["contractVersion"] = 2
        return {"schema": 1, "originRef": "origin", "targetRef": "target",
                "originOwner": "alice", "originTaskId": "00000000-0000-0000-0000-000000000001",
                "manifestSha256": "a" * 64, "tool": "checksum", "receiverIdentity": "receiver",
                "targetRevision": "1", "targetFingerprint": "b" * 64,
                "outcome": "authorized", "authority": scope}

    def test_legacy_reply_round_trip_has_no_version_or_operation_key(self):
        original = self.reply()
        parsed = AuthorityReply.model_validate(original)
        self.assertIsInstance(parsed.authority, AuthorityScope)
        self.assertEqual(parsed.model_dump(), original)
        self.assertEqual(list(parsed.model_dump()["authority"]), ["capabilities", "tools", "budget", "usageGrantSha256"])

    def test_v2_requires_explicit_version_and_retains_operation_ceiling(self):
        original = self.reply(2)
        parsed = AuthorityReply.model_validate(original)
        self.assertIsInstance(parsed.authority, AuthorityScopeV2)
        self.assertEqual(parsed.model_dump(), original)
        del original["authority"]["contractVersion"]
        with self.assertRaises(ValidationError):
            AuthorityReply.model_validate(original)

    def test_mixed_budget_wrong_version_and_boolean_versions_are_rejected(self):
        for version in (1, 2):
            original = self.reply(version)
            variants = []
            mixed = deepcopy(original)
            mixed["authority"]["budget"]["operationSeconds" if version == 1 else "experimentSeconds"] = 8
            variants.append(mixed)
            for wrong in (True, False, 1, 3, "2"):
                changed = deepcopy(original)
                changed["authority"]["contractVersion"] = wrong
                variants.append(changed)
            for changed in variants:
                with self.subTest(version=version, scope=changed["authority"]), self.assertRaises(ValidationError):
                    AuthorityReply.model_validate(changed)

    def test_v2_cancelled_reply_cannot_carry_execution_scope(self):
        reply = self.reply(2)
        reply["outcome"] = "cancelled"
        with self.assertRaises(ValidationError):
            AuthorityReply.model_validate(reply)

    def test_transport_preserves_explicit_version_and_budget_without_execution_retry(self):
        transport = OriginAuthorityTransport(base_url="http://127.0.0.1:1", origin_ref="origin",
            target_ref="target", target_revision="1", target_fingerprint="b" * 64,
            receiver_identity_map={"alice": "receiver"}, credential_provider=lambda _: "synthetic-fixture")
        for version in (1, 2):
            scope = self.reply(version)["authority"]
            def response(_transport, owner, path, body):
                return json.dumps({**body, "outcome": "authorized", "authority": scope}).encode()
            with patch.object(OriginAuthorityTransport, "_post", autospec=True, side_effect=response) as post:
                grant = transport("alice", "00000000-0000-0000-0000-000000000001", "a" * 64, "checksum")
            self.assertEqual(post.call_count, 1)
            self.assertEqual(grant.contract_version, version)
            self.assertEqual(dict(grant.budget), scope["budget"])
            self.assertEqual(grant.target_fingerprint, "b" * 64)
