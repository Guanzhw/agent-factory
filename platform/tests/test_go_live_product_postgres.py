# pyright: reportMissingImports=false
"""Actual Factory/PG live-gate route with mock HTTP only, not live account proof."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from uuid import uuid4

import httpx
from agno.models.message import Message

from agent_factory.config import Settings
from agent_factory.go_development import (CAPABILITY, REGISTRATION_REF, GoDevelopmentHandle,
    application_definition, publish_go_development_models, trusted_model_binding)
from agent_factory.go_live import GoLiveCampaign, MODELS
from agent_factory.opencode_go import BASE_URL, USER_AGENT, GoDevelopmentModel
from agent_factory.usage_ledger import UsagePolicy
from pg_fixture import IsolatedPostgres
import test_go_product_postgres as product_helpers


class SyntheticCampaignPeer:
    """Exact mock transport; records only public request contracts and native session IDs."""
    def __init__(self):
        self.requests = []
        self.lock = threading.Lock()
        self.transport = httpx.MockTransport(self.reply)

    def reply(self, request):
        body = json.loads(request.content)
        model = body["model"]
        responses = model == "gpt-6-luna"
        messages = body["input" if responses else "messages"]
        returned = any(item.get("type") == "function_call_output" or item.get("role") == "tool" for item in messages)
        product = bool(body.get("tools")) or returned
        with self.lock:
            self.requests.append({"url": str(request.url), "model": model,
                "session": request.headers["x-opencode-session"], "userAgent": request.headers["User-Agent"],
                "stream": body["stream"], "returnedTool": returned, "product": product})
        call = {"id": "synthetic_checksum_call", "type": "function", "function": {
            "name": "checksum", "arguments": json.dumps({"text": "synthetic Go development"})}}
        tool = product and not returned
        if responses:
            output = ([{"type": "function_call", "call_id": call["id"], **call["function"]}] if tool else
                      [{"type": "message", "content": [{"type": "output_text", "text": "Synthetic coding check complete."}]}])
            result = {"model": model, "status": "completed", "output": output,
                      "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}}
            events = [{"type": "response.created", "response": {"model": model, "status": "in_progress"}},
                      {"type": "response.completed", "response": result}]
        else:
            delta = {"tool_calls": [{"index": 0, **call}]} if tool else {"content": "Synthetic coding check complete."}
            events = [{"model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                      {"model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if tool else "stop"}]},
                      {"model": model, "choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}]
        payload = b"".join(b"data: " + json.dumps(event).encode() + b"\n\n" for event in events)
        if not responses:
            payload += b"data: [DONE]\n\n"
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, content=payload)


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class GoLiveProductPostgresTests(unittest.TestCase):
    # Reuse the API helpers, without inheriting the unrelated fixture-only tests.
    open_application = product_helpers.GoProductPostgresTests.open_application
    login = product_helpers.GoProductPostgresTests.login
    post = product_helpers.GoProductPostgresTests.post
    plan = product_helpers.GoProductPostgresTests.plan
    submit = product_helpers.GoProductPostgresTests.submit
    wait = product_helpers.GoProductPostgresTests.wait
    usage = product_helpers.GoProductPostgresTests.usage

    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.workspace = tempfile.TemporaryDirectory(prefix="go-live-product-mock-")
        self.addCleanup(self.workspace.cleanup)
        self.campaign = GoLiveCampaign.create(Path(self.workspace.name) / "synthetic-campaign.sqlite",
            campaign_id="synthetic-campaign", owner_id="alice", confirmation_id="synthetic-not-account-proof",
            use_balance_disabled=True, auto_reload_disabled=True, expires_at=time.time() + 600)
        self.peer = SyntheticCampaignPeer()
        self.credential = mock.Mock(return_value="offline-only-synthetic-value")
        handle = GoDevelopmentHandle(mode="subscription", credential=self.credential,
            live_campaign=self.campaign, wire_stream=True, native_retries=0)
        self.assertIsNone(handle.async_transport)
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.workspace.name) / "factory",
            development_profile="opencode-go", development_live_validation=True, max_workers=1, max_tool_calls=1,
            temporary_policy="read-only-auto", policy_revision="go-live-mock-policy-v1",
            material_policy_revision="go-live-mock-material-v1", runtime_tool_contract="registered-runtime-v1",
            usage_policy=UsagePolicy(revision="go-live-mock-usage-v1", task_amount_micros=1_000_000,
                user_amount_micros=10_000_000, task_token_limit=500_000, user_token_limit=2_000_000),
            trusted_connections={REGISTRATION_REF: trusted_model_binding("alice", handle)})
        def offline_model(**kwargs):
            self.assertIsNone(kwargs.pop("async_transport"))
            self.assertIs(kwargs["live_campaign"], self.campaign)
            self.assertEqual(kwargs["native_retries"], 0)
            return GoDevelopmentModel(**kwargs, async_transport=self.peer.transport)
        self.enterContext(mock.patch("agent_factory.go_development.GoDevelopmentModel", side_effect=offline_model))
        self.open_application()
        auth = self.state["auth"]
        auth.authorization.unassign("bob", "factory-user")
        auth.authorization.assign("bob", "factory-manager")
        models = publish_go_development_models(self.state, author="manager", reviewer="bob")
        seeds = self.store.materials(published_only=True)
        checksum = next(row for row in seeds if row["kind"] == "tool" and row["content"] == "checksum")
        environment = next(row for row in seeds if row["id"] == "local-environment")
        definition = application_definition(models, checksum, environment)
        for mode in definition["modes"].values():
            mode["budget"]["toolCalls"] = 1
        self.login("bob")
        application = self.post("/api/factory/applications/drafts", {"definition": definition, "requestId": str(uuid4())}, 201)
        review = self.post(f"/api/factory/applications/{application['id']}/versions/{application['version']}/review",
                           {"requestId": str(uuid4())}, 201)
        self.login("manager")
        self.post(f"/api/factory/applications/reviews/{review['id']}/decision",
                  {"approved": True, "requestId": str(uuid4())}, 200)
        self.app_ref = {key: application[key] for key in ("id", "version", "sha256")}
        self.connection = self.state["connections"].bind("alice", REGISTRATION_REF, str(uuid4()), capabilities=[CAPABILITY])
        self.login("alice")
        self.assertEqual(self.peer.requests, [])
        self.credential.assert_not_called()

    def test_two_exact_models_each_smoke_then_native_checksum_product(self):
        for model in MODELS:
            with self.subTest(model=model):
                start = len(self.peer.requests)
                session = "synthetic-smoke-" + model.replace(".", "-")
                self.campaign.authorize(session, model, purpose="smoke", owner_id="alice")
                smoke = GoDevelopmentModel(model_id=model, session_id=session, credential=self.credential,
                    wire_stream=True, native_retries=0, timeout_seconds=60, live_campaign=self.campaign,
                    async_transport=self.peer.transport)
                result = asyncio.run(smoke.ainvoke([Message(role="user", content="Explain what a checksum validates in a coding test.")]))
                self.assertEqual(result.response_usage.total_tokens, 18)
                self.assertEqual(len(self.peer.requests) - start, 1)
                task = self.submit(model)
                detail = self.wait(task)
                self.assertEqual(detail["job"]["status"], "completed", detail)
                native_task = self.store.task(task, "alice")
                ticket = self.store.native_db.get_job(native_task["run_id"], strict=True)
                self.assertEqual(ticket["max_attempts"], 1)
                self.assertEqual(ticket["attempt"], 1)
                requests = self.peer.requests[start:]
                self.assertEqual(len(requests), 3)
                self.assertEqual([row["session"] for row in requests], [session, task, task])
                self.assertEqual([row["returnedTool"] for row in requests], [False, False, True])
                self.assertTrue(all(row["stream"] is True and row["userAgent"] == USER_AGENT for row in requests))
                endpoint = "responses" if model == "gpt-6-luna" else "chat/completions"
                self.assertEqual({row["url"] for row in requests}, {BASE_URL + "/" + endpoint})
                artifacts = [row for row in detail["artifacts"] if row["name"] == "checksum.json"]
                self.assertEqual(len(artifacts), 1)
                artifact = artifacts[0]
                response = self.client.get(f"/api/factory/jobs/{task}/artifacts/{artifact['id']}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(hashlib.sha256(response.content).hexdigest(), artifact["sha256"])
                self.assertIn(hashlib.sha256(b"synthetic Go development").hexdigest(), json.dumps(response.json()))
                usage = self.usage(task)
                self.assertEqual([row["state"] for row in usage["attempts"]], ["SETTLED", "SETTLED"])
                self.assertEqual(len({row["id"] for row in usage["attempts"]}), 2)
                scope = next(row for row in usage["scopes"] if row["scope"] == "task")
                self.assertEqual(scope["settledTokens"], 36)
                self.assertEqual(scope["heldTokens"], 0)
                self.assertGreater(scope["settledAmountMicros"], 0)
                campaign_tickets = [row for row in self.campaign.inspect()["tickets"] if row["model"] == model]
                self.assertEqual([(row["purpose"], row["state"], row["actual_model"]) for row in campaign_tickets],
                    [("smoke", "SETTLED", model), ("product", "SETTLED", model), ("product", "SETTLED", model)])
                self.campaign.complete_model(model, artifact["sha256"])
        proof = self.campaign.inspect()
        self.assertEqual(proof["status"], "DONE")
        self.assertEqual(proof["requestCount"], 6)
        self.assertEqual(proof["modelCounts"], dict.fromkeys(MODELS, 3))
        self.assertEqual(self.credential.call_count, 6)
        self.assertEqual(len(proof["completions"]), 2)


if __name__ == "__main__":
    unittest.main()
