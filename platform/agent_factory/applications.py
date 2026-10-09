"""Governed immutable application configurations, separate from task approvals.

Applications select approved exact material versions and bounded variants; they
never register code, credentials, adapter factories or permissions themselves.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError
from sqlalchemy import Boolean, Column, Integer, JSON, MetaData, String, Table, func, select, text

from .input_schema import validate_input_values
from .material_governance import MaterialGovernance, PinnedRef
from .plan_policy import application_tool_catalog
from .store import canonical, digest, now

APPLICATION_POLICY = digest({"schema": 1, "separateAdministrator": True, "taskApprovalSeparate": True})
MATERIAL_KINDS = {"skill", "tool", "prompt", "knowledge", "model", "environment"}


# Compatibility exports preserve existing application profile imports.
from .application_schema import (ApplicationDefinition, ApplicationDefinitionV2, ModeDefinition,
    ModeDefinitionV2, LegacyBudget as Budget, LegacyTaskConfig as TaskConfig,  # noqa: F401
    MaterialChoice as MaterialChoice, ConnectionRequirement as ConnectionRequirement,
    definition_model, budget_limits, task_config)


class GovernedStorage:
    def __init__(self, store, namespace):
        self.store, self.namespace = store, namespace

    @contextmanager
    def read(self):
        shared = getattr(self.store, "_connection", None)
        conn = shared.get() if shared is not None else None
        if conn is not None:
            yield conn
        else:
            with self.store.engine.connect() as conn:
                yield conn

    @contextmanager
    def write(self):
        shared = getattr(self.store, "_connection", None)
        conn = shared.get() if shared is not None else None
        if conn is not None:
            if self.store.engine.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": self.namespace})
            yield conn
            return
        with self.store.engine.begin() as conn:
            if self.store.engine.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": self.namespace})
            token = shared.set(conn) if shared is not None else None
            try:
                yield conn
            finally:
                if shared is not None and token is not None:
                    shared.reset(token)

    @staticmethod
    def command_table(name, metadata):
        return Table(name, metadata, Column("actor_id", String, primary_key=True),
            Column("request_id", String, primary_key=True), Column("fingerprint", String, nullable=False),
            Column("action", String, nullable=False), Column("result", JSON, nullable=False), Column("created_at", String, nullable=False))

    @staticmethod
    def old(conn, table, actor, key, fingerprint):
        MaterialGovernance._key(key)
        row = conn.execute(select(table).where(table.c.actor_id == actor, table.c.request_id == key)).mappings().first()
        if row and row["fingerprint"] != fingerprint:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT: governed intent changed")
        return row["result"] if row else None

    @staticmethod
    def record(conn, table, actor, key, fingerprint, action, result):
        conn.execute(table.insert().values(actor_id=actor, request_id=key, fingerprint=fingerprint,
                     action=action, result=result, created_at=now()))
        return result


class ApplicationService:
    def __init__(self, store: Any, auth: Any):
        self.store, self.auth = store, auth
        self.db = GovernedStorage(store, "af_application_governance_v1")
        metadata = MetaData()
        self.versions = Table("af_applications", metadata, Column("id", String, primary_key=True),
            Column("version", Integer, primary_key=True), Column("body", JSON, nullable=False), Column("sha", String, nullable=False))
        self.states = Table("af_application_states", metadata, Column("id", String, primary_key=True),
            Column("version", Integer, primary_key=True), Column("author_id", String, nullable=False),
            Column("state", String, nullable=False), Column("bootstrap", Boolean, nullable=False),
            Column("review_id", String), Column("reason", String), Column("updated_at", String, nullable=False))
        self.reviews = Table("af_application_reviews", metadata, Column("id", String, primary_key=True),
            Column("application_id", String, nullable=False), Column("version", Integer, nullable=False),
            Column("author_id", String, nullable=False), Column("sha", String, nullable=False),
            Column("policy_hash", String, nullable=False), Column("decision", String, nullable=False),
            Column("reviewer_id", String), Column("created_at", String, nullable=False), Column("decided_at", String))
        self.commands = self.db.command_table("af_application_commands", metadata)
        self.legacy = Table("af_legacy_application_pins", metadata, Column("plan_id", String, primary_key=True),
            Column("plan_hash", String, nullable=False), Column("application_ref", JSON, nullable=False), Column("created_at", String, nullable=False))
        metadata.create_all(store.engine)

    @staticmethod
    def pin(body):
        return {key: body[key] for key in ("id", "version", "sha256")}

    def _admin(self, actor):
        try:
            self.auth.require(actor, "agent_os:admin")
            return True
        except HTTPException as error:
            if error.status_code != 403:
                raise
            return False

    def _row(self, conn, identifier, version):
        row = conn.execute(select(self.versions).where(self.versions.c.id == identifier, self.versions.c.version == version)).mappings().first()
        state = conn.execute(select(self.states).where(self.states.c.id == identifier, self.states.c.version == version)).mappings().first()
        if not row or not state:
            raise HTTPException(404, "Application version not found")
        body = row["body"]
        actual = digest({key: value for key, value in body.items() if key != "sha256"})
        if body.get("id") != identifier or body.get("version") != version or row["sha"] != actual or body.get("sha256") != actual:
            raise HTTPException(409, "Immutable application integrity mismatch")
        return body, dict(state)

    def _scoped(self, actor, state):
        self.auth.require(actor, "components:read")
        if state["state"] != "published" and actor != state["author_id"] and not self._admin(actor):
            raise HTTPException(404, "Scoped application version not found")

    def _active(self, conn, body, state):
        if state["state"] != "published":
            raise HTTPException(409, "INACTIVE_APPLICATION: exact version is not published")
        if state["bootstrap"]:
            if not self.store.settings.demo:
                raise HTTPException(409, "Demo application approval cannot authorize production")
        else:
            review = conn.execute(select(self.reviews).where(self.reviews.c.id == state["review_id"])).mappings().first()
            if not review or review["decision"] != "approved" or review["sha"] != body["sha256"] or review["policy_hash"] != APPLICATION_POLICY or review["reviewer_id"] == state["author_id"]:
                raise HTTPException(409, "Application lacks exact separate administrator publication review")

    def closure(self, refs):
        governance = getattr(self.store, "material_governance", None)
        if governance is None:
            raise HTTPException(503, "Material governance is not configured")
        pins = [PinnedRef.model_validate(ref).model_dump() for ref in refs]
        # Build the candidate graph from published rows, then validate the
        # entire selected closure below. Checking every unrelated catalog item
        # here repeats governance work at each execution/remote boundary.
        # The final current check remains mandatory on every invocation.
        known = {(item["id"], item["version"], item["sha256"]): item
                 for item in self.store.materials(published_only=False) if item.get("published")}
        chosen, visiting = {}, set()

        def visit(ref, depth):
            key = (ref["id"], ref["version"], ref["sha256"])
            if key in visiting:
                raise HTTPException(409, "Pinned application dependency cycle")
            if key in chosen:
                return
            if depth > 8 or len(chosen) + len(visiting) >= 30:
                raise HTTPException(409, "Application material closure exceeds depth/count bounds")
            item = known.get(key)
            if item is None or item.get("kind") not in MATERIAL_KINDS or item.get("archived") or "agno:3.1.0" not in item.get("compatibility", []):
                raise HTTPException(409, "Approved pinned application material is unavailable or incompatible")
            actual = digest({name: value for name, value in item.items() if name not in {"sha256", "published", "createdAt"}})
            if actual != ref["sha256"]:
                raise HTTPException(409, "Pinned application material integrity differs")
            visiting.add(key)
            for dependency in item.get("dependencies", []):
                visit(PinnedRef.model_validate(dependency).model_dump(), depth + 1)
            visiting.remove(key)
            chosen[key] = item

        for pin in pins:
            visit(pin, 1)
        materials = list(chosen.values())
        governance.require_materials_current({"materialRefs": [self.pin(item) for item in materials]})
        return materials

    def chosen_refs(self, mode, choices=None):
        choices = choices or {}
        if not isinstance(choices, dict) or set(choices) - set(mode["materialChoices"]):
            raise HTTPException(422, "Material choices contain an unapproved application slot")
        refs = list(mode["materialRefs"])
        for name, slot in mode["materialChoices"].items():
            try:
                choice = PinnedRef.model_validate(choices.get(name, slot["defaultRef"])).model_dump()
            except ValidationError as error:
                raise HTTPException(422, "Material choices must pin exact approved versions") from error
            if choice not in slot["allowedRefs"]:
                raise HTTPException(422, "Exact material choice is outside the application's approved variants")
            refs[refs.index(slot["defaultRef"])] = choice
        return refs

    def validate_definition(self, definition, *, check_materials=True):
        known_tools = application_tool_catalog(self.store)
        MaterialGovernance._safe_data(definition)
        try:
            body = definition_model(definition).model_validate(definition).model_dump(exclude_none=True)
        except (ValidationError, ValueError, TypeError) as error:
            raise HTTPException(422, "Invalid structured application definition") from error
        if len(canonical(body).encode()) > 131072 or body["defaultMode"] not in body["modes"]:
            raise HTTPException(422, "Application default mode or bounded payload is invalid")
        if any(not word.strip() or len(word) > 100 for word in body["discoveryKeywords"]):
            raise HTTPException(422, "Discovery keywords must be bounded nonempty strings")
        for name, mode in body["modes"].items():
            if not name or len(name) > 100 or not all(char.isascii() and (char.isalnum() or char in "_.:-") for char in name):
                raise HTTPException(422, "Application mode must be a bounded identifier")
            if not set(mode["capabilities"]) <= set(known_tools.values()):
                raise HTTPException(422, "Application requests authority outside registered capabilities")
            native = mode.get("nativeComponent")
            if native is not None:
                workflows = getattr(self.store, "native_workflows", None)
                if workflows is None or workflows.pin(native["id"]) != native:
                    raise HTTPException(409, "Native workflow registration is unavailable or changed")
            defaults = []
            for slot_name, slot in mode["materialChoices"].items():
                if not slot_name or len(slot_name) > 100 or slot["defaultRef"] not in mode["materialRefs"] or slot["defaultRef"] not in slot["allowedRefs"] or slot["defaultRef"] in defaults:
                    raise HTTPException(422, "Application material choice default is invalid or overlaps")
                defaults.append(slot["defaultRef"])
                if not check_materials:
                    continue
                for pin in slot["allowedRefs"]:
                    variant = self.closure([pin])
                    material = variant[-1]
                    if material["kind"] != slot["kind"]:
                        raise HTTPException(422, "Approved material variant has the wrong kind")
                    if {cap for item in variant for cap in item["permissions"]} - set(mode["capabilities"]):
                        raise HTTPException(422, "Material variant exceeds its application mode authority")
            if not check_materials:
                continue
            materials = self.closure(mode["materialRefs"])
            caps = {cap for item in materials for cap in item["permissions"]}
            tools = [item["content"] for item in materials if item["kind"] == "tool"]
            if not tools or caps - set(mode["capabilities"]) or any(tool not in known_tools for tool in tools):
                raise HTTPException(422, "Application material/tool closure exceeds its approved capability scope")
            if mode["toolOrder"] and (len(set(mode["toolOrder"])) != len(mode["toolOrder"]) or set(mode["toolOrder"]) != set(tools)):
                raise HTTPException(422, "Application tool order must exactly match approved tools")
            names = [requirement["name"] for requirement in mode["connectionRequirements"]]
            if len(set(names)) != len(names) or any(set(requirement["requiredCapabilities"]) - set(mode["capabilities"]) for requirement in mode["connectionRequirements"]):
                raise HTTPException(422, "Application connection requirement exceeds the mode scope or duplicates a name")
        return body

    def create_draft(self, actor, definition, request_id, *, parent_ref=None):
        self.auth.require(actor, "components:write")
        body = self.validate_definition(definition, check_materials=False)
        fingerprint = digest({"action": "revise" if parent_ref else "draft", "definition": body, "parentRef": parent_ref})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, actor, request_id, fingerprint)
            if old is not None:
                return old
            self.validate_definition(body)
            identifier = body.get("id") or str(uuid4())
            latest = conn.execute(select(func.max(self.versions.c.version)).where(self.versions.c.id == identifier)).scalar() or 0
            if latest:
                _, previous = self._row(conn, identifier, latest)
                if previous["author_id"] != actor and not self._admin(actor):
                    raise HTTPException(403, "A manager cannot overwrite another author's application lineage")
            value = {**body, "id": identifier, "version": latest + 1, "createdAt": now(), "schema": 1, "origin": "manager-authored"}
            value["sha256"] = digest(value)
            self.auth.require(actor, "components:write")
            conn.execute(self.versions.insert().values(id=identifier, version=value["version"], body=value, sha=value["sha256"]))
            conn.execute(self.states.insert().values(id=identifier, version=value["version"], author_id=actor, state="draft", bootstrap=False, updated_at=now()))
            return self.db.record(conn, self.commands, actor, request_id, fingerprint, "application.draft", value)

    def import_snapshot(self, actor, snapshot, request_id):
        """Install an exact inert snapshot for a separate local publication review.

        This trusted operator method has no HTTP route. Source review decisions
        are deliberately absent from the snapshot schema; importing does not
        authorize execution or register runtime adapters.
        """
        self.auth.require(actor, "agent_os:admin")
        self.auth.require(actor, "components:write")
        MaterialGovernance._safe_data(snapshot)
        try:
            fields = set(definition_model(snapshot).model_fields)
        except (ValueError, TypeError) as error:
            raise HTTPException(422, "Unsupported application contract version") from error
        if not isinstance(snapshot, dict) or set(snapshot) != fields | {"version", "createdAt", "schema", "origin", "sha256"}:
            raise HTTPException(422, "Application snapshot requires the complete immutable schema")
        value = deepcopy(snapshot)
        definition = {key: value[key] for key in fields}
        try:
            normalized = self.validate_definition(definition, check_materials=False)
            canonical_snapshot = canonical(value)
            canonical_definition = canonical(definition)
            if len(canonical_snapshot.encode("utf-8")) > 131072:
                raise HTTPException(422, "Application snapshot exceeds its bounded payload")
            if canonical_definition != canonical(normalized):
                raise HTTPException(422, "Application snapshot definition must be complete and canonical")
        except (TypeError, ValueError, UnicodeError) as error:
            raise HTTPException(422, "Application snapshot requires bounded valid JSON") from error
        if (type(value["schema"]) is not int or value["schema"] != 1
                or type(value["version"]) is not int or not 1 <= value["version"] <= 2147483647
                or value["origin"] != "manager-authored"
                or not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"])):
            raise HTTPException(422, "Application snapshot schema, version, origin or digest is invalid")
        timestamp = value["createdAt"]
        if not isinstance(timestamp, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})", timestamp):
            raise HTTPException(422, "Application snapshot requires a timezone-aware source timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("Missing source timezone")
        except ValueError as error:
            raise HTTPException(422, "Application snapshot source timestamp is invalid") from error
        if value["sha256"] != digest({key: item for key, item in value.items() if key != "sha256"}):
            raise HTTPException(422, "Application snapshot digest differs from its exact immutable body")
        fingerprint = digest({"action": "application.import-snapshot", "snapshot": value})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, actor, request_id, fingerprint)
            if old is not None:
                return old
            existing = conn.execute(select(self.versions).where(
                self.versions.c.id == value["id"], self.versions.c.version == value["version"])).mappings().first()
            if existing:
                body, _ = self._row(conn, value["id"], value["version"])
                if canonical(body) != canonical_snapshot:
                    raise HTTPException(409, "Immutable application version conflicts with the imported snapshot")
            else:
                latest = conn.execute(select(func.max(self.versions.c.version)).where(self.versions.c.id == value["id"])).scalar() or 0
                if value["version"] <= latest:
                    raise HTTPException(409, "Application snapshot cannot insert an older immutable version")
            # Local material approval, bindings and dependency hashes are never
            # inherited from a source Factory's publication decision.
            self.validate_definition(normalized)
            self.auth.require(actor, "agent_os:admin")
            self.auth.require(actor, "components:write")
            if not existing:
                conn.execute(self.versions.insert().values(id=value["id"], version=value["version"], body=value, sha=value["sha256"]))
                conn.execute(self.states.insert().values(id=value["id"], version=value["version"],
                    author_id=actor, state="draft", bootstrap=False, updated_at=now()))
            # Observing an identical version never resets approval, author,
            # archive/withdrawal metadata or an existing publication review.
            return self.db.record(conn, self.commands, actor, request_id, fingerprint, "application.import-snapshot", value)

    def revise(self, actor, identifier, version, definition, request_id):
        self.auth.require(actor, "components:write")
        with self.db.read() as conn:
            parent, state = self._row(conn, identifier, version)
            if state["author_id"] != actor and not self._admin(actor):
                raise HTTPException(404, "Scoped application version not found")
        if definition.get("id", identifier) != identifier:
            raise HTTPException(422, "Application revision cannot change its lineage")
        # Versioned drafts retain all previous immutable bodies and review facts.
        return self.create_draft(actor, {**definition, "id": identifier}, request_id, parent_ref=self.pin(parent))

    def request_publication(self, actor, identifier, version, request_id):
        self.auth.require(actor, "components:write")
        with self.db.write() as conn:
            body, state = self._row(conn, identifier, version)
            if actor != state["author_id"] and not self._admin(actor):
                raise HTTPException(404, "Scoped application review not found")
            fingerprint = digest({"action": "review", "ref": self.pin(body), "policy": APPLICATION_POLICY})
            old = self.db.old(conn, self.commands, actor, request_id, fingerprint)
            if old is not None:
                return old
            if state["state"] in {"archived", "withdrawn"}:
                raise HTTPException(409, "Inactive application versions require a new draft")
            self.validate_definition({key: value for key, value in body.items() if key not in {"schema", "version", "createdAt", "sha256", "origin"}})
            row = {"id": str(uuid4()), "application_id": identifier, "version": version, "author_id": state["author_id"],
                   "sha": body["sha256"], "policy_hash": APPLICATION_POLICY, "decision": "pending", "created_at": now()}
            self.auth.require(actor, "components:write")
            conn.execute(self.reviews.insert().values(**row))
            result = self._review(conn, row)
            return self.db.record(conn, self.commands, actor, request_id, fingerprint, "application.review", result)

    def _review(self, conn, row):
        body, state = self._row(conn, row["application_id"], row["version"])
        return {"id": row["id"], "applicationRef": self.pin(body), "authorId": row["author_id"],
                "decision": row["decision"], "reviewerId": row.get("reviewer_id"), "createdAt": row["created_at"],
                "decidedAt": row.get("decided_at"), "policyHash": row["policy_hash"], "state": state["state"],
                "application": body, "separateAdministratorRequired": True, "taskApprovalSeparate": True}

    def decide_publication(self, actor, review_id, approved, request_id):
        self.auth.require(actor, "agent_os:admin")
        if type(approved) is not bool:
            raise HTTPException(422, "A typed publication decision is required")
        with self.db.write() as conn:
            row = conn.execute(select(self.reviews).where(self.reviews.c.id == review_id)).mappings().first()
            if not row:
                raise HTTPException(404, "Application publication review not found")
            row = dict(row)
            fingerprint = digest({"action": "decision", "reviewId": review_id, "approved": approved, "sha": row["sha"]})
            old = self.db.old(conn, self.commands, actor, request_id, fingerprint)
            if old is not None:
                return old
            body, state = self._row(conn, row["application_id"], row["version"])
            if actor == row["author_id"]:
                raise HTTPException(403, "A separate current native administrator must review the application")
            if row["decision"] != "pending" or row["policy_hash"] != APPLICATION_POLICY or row["sha"] != body["sha256"] or state["state"] in {"archived", "withdrawn"}:
                raise HTTPException(409, "Application review is stale, decided or inactive")
            if approved:
                self.validate_definition({key: value for key, value in body.items() if key not in {"schema", "version", "createdAt", "sha256", "origin"}})
            self.auth.require(actor, "agent_os:admin")
            row.update(decision="approved" if approved else "denied", reviewer_id=actor, decided_at=now())
            conn.execute(self.reviews.update().where(self.reviews.c.id == review_id).values(decision=row["decision"], reviewer_id=actor, decided_at=row["decided_at"]))
            if approved:
                conn.execute(self.states.update().where(self.states.c.id == body["id"], self.states.c.version == body["version"]).values(state="published", review_id=review_id, updated_at=now()))
            return self.db.record(conn, self.commands, actor, request_id, fingerprint, "application.decision", self._review(conn, row))

    def require_current(self, application_ref):
        try:
            ref = PinnedRef.model_validate(application_ref).model_dump()
        except ValidationError as error:
            raise HTTPException(409, "Exact immutable application reference is required") from error
        with self.db.read() as conn:
            body, state = self._row(conn, ref["id"], ref["version"])
            if body["sha256"] != ref["sha256"]:
                raise HTTPException(409, "Pinned application digest differs")
            self._active(conn, body, state)
            return body

    def require_plan_current(self, plan):
        ref = plan.get("applicationRef") or self.require_legacy_demo_plan(plan)
        application = self.require_current(ref)
        # Contract selection is governed by the immutable application, never a
        # caller-supplied plan marker. V1's absent marker is part of its format.
        marker = application.get("contractVersion")
        if ((marker is None and "contractVersion" in plan) or
                (marker is not None and (type(plan.get("contractVersion")) is not int
                                         or plan["contractVersion"] != marker))):
            raise HTTPException(403, "Plan contract version differs from its governed application")
        operator_limits = budget_limits(self.store.settings, marker or 1)
        if (type(plan.get("budget")) is not dict or
                set(plan["budget"]) != set(operator_limits) | {"depth"}):
            raise HTTPException(403, "Plan has fields outside its governed budget contract")
        if plan.get("application") != application["id"] or plan.get("mode") not in application["modes"]:
            raise HTTPException(409, "Plan differs from its published application/mode")
        mode = application["modes"][plan["mode"]]
        anchor = plan.get("bindingManifest")
        if (plan.get("nativeComponent") != mode.get("nativeComponent") or
                (anchor or {}).get("nativeComponent") != mode.get("nativeComponent")):
            raise HTTPException(409, "Native component differs from the approved application mode")
        schema = mode.get('inputSchema')
        if schema is None:
            if any(key in plan for key in ('inputSchema', 'inputValues')) or (anchor is not None and
                    any(key in anchor for key in ('inputSchemaSha256', 'inputValuesSha256'))):
                raise HTTPException(409, 'Application does not declare structured inputs')
        else:
            try:
                values = validate_input_values(schema, plan.get('inputValues'))
                if (plan.get('inputSchema') != schema or anchor is None
                        or anchor.get('inputSchemaSha256') != digest(schema)
                        or anchor.get('inputValuesSha256') != digest(values)):
                    raise ValueError('Input binding differs')
            except ValueError as error:
                raise HTTPException(409, 'Governed application input binding differs') from error
        if anchor is None:
            # Explicit proved legacy plans have no mutable reconstructed manifest.
            self.require_legacy_demo_plan(plan)
            choices = {}
        else:
            if anchor.get("sha256") != digest({key: value for key, value in anchor.items() if key != "sha256"}) or anchor.get("applicationRef") != ref or anchor.get("mode") != plan["mode"] or anchor.get("materialRefs") != plan.get("materialRefs"):
                raise HTTPException(409, "Composition binding anchor integrity differs")
            if anchor.get("sourceSnapshotRef") != plan.get("sourceSnapshotRef"):
                raise HTTPException(409, "Composition source snapshot binding differs")
            execution = plan.get("executionBindings") or {}
            if anchor.get("executionBindingsSha256") != execution.get("sha256"):
                raise HTTPException(409, "Composition execution binding anchor differs")
            choices = anchor.get("materialChoices", {})
        materials = self.closure(self.chosen_refs(mode, choices))
        refs = [self.pin(item) for item in materials]
        if {(item["id"], item["version"], item["sha256"]) for item in refs} != {(item["id"], item["version"], item["sha256"]) for item in plan.get("materialRefs", [])}:
            raise HTTPException(403, "Plan materials exceed or differ from the approved application choices")
        tools = {item["content"] for item in materials if item["kind"] == "tool"}
        caps = {cap for item in materials for cap in item["permissions"]}
        if set(plan.get("tools", [])) != tools or set(plan.get("capabilities", [])) != caps or caps - set(mode["capabilities"]):
            raise HTTPException(403, "Plan tool/capability scope differs from its governed application")
        if anchor is not None:
            order = mode["toolOrder"] or list(dict.fromkeys(item["content"] for item in materials if item["kind"] == "tool"))
            config = plan.get("config", {})
            if config.get("toolOrder") != order or config.get("sample") != plan.get("normalizedGoal"):
                raise HTTPException(403, "Plan task configuration differs from its governed application")
            if application.get("contractVersion", 1) == 2:
                expected = task_config(application, mode, plan["normalizedGoal"], order, plan["budget"])
                if config != expected or plan.get("contractVersion") != 2:
                    raise HTTPException(403, "Plan application configuration differs from its governed schema")
            else:
                duration = config.get("experimentDurationSeconds")
                if type(duration) is not int or not 1 <= duration <= min(mode["config"]["experimentDurationSeconds"], plan.get("budget", {}).get("experimentSeconds", 0)):
                    raise HTTPException(403, "Plan environment duration exceeds its governed ceiling")
        for key, ceiling in mode["budget"].items():
            ceiling = min(ceiling, operator_limits[key])
            if type(plan.get("budget", {}).get(key)) is not int or not 1 <= plan["budget"][key] <= ceiling:
                raise HTTPException(403, "Plan budget exceeds its application ceiling")
        return application

    def adopt_legacy_demo_plan(self, plan):
        """Trusted explicit migration proof; never exposed as a user/model route."""
        if not self.store.settings.demo or not plan.get("syntheticFixture") or plan.get("applicationRef") or plan.get("executionBindings"):
            raise HTTPException(409, "Only explicit historical synthetic plans may receive a legacy pin")
        stored = self.store.plan(plan["id"], plan["ownerId"])
        if digest(stored) != digest(plan):
            raise HTTPException(409, "Legacy plan must match its existing immutable stored body")
        with self.db.write() as conn:
            application, state = self._row(conn, plan["application"], 1)
            if not state["bootstrap"]:
                raise HTTPException(409, "Legacy application must be a proved demo bootstrap")
            self._active(conn, application, state)
            mode = application["modes"].get(plan["mode"])
            if mode is None:
                raise HTTPException(409, "Legacy plan has no seeded application mode")
            materials = self.closure(mode["materialRefs"])
            expected = {tuple(self.pin(item).values()) for item in materials}
            actual = {(item["id"], item["version"], item["sha256"]) for item in plan.get("materialRefs", [])}
            if expected != actual or set(plan.get("tools", [])) != {item["content"] for item in materials if item["kind"] == "tool"} or set(plan.get("capabilities", [])) != {cap for item in materials for cap in item["permissions"]}:
                raise HTTPException(409, "Legacy plan differs from exact seeded material/tool/capability scope")
            for key, ceiling in mode["budget"].items():
                if type(plan.get("budget", {}).get(key)) is not int or not 1 <= plan["budget"][key] <= ceiling:
                    raise HTTPException(409, "Legacy plan exceeds seeded application budget")
            reference = self.pin(application)
            old = conn.execute(select(self.legacy).where(self.legacy.c.plan_id == plan["id"])).mappings().first()
            if old and (old["plan_hash"] != digest(plan) or old["application_ref"] != reference):
                raise HTTPException(409, "Legacy application proof conflicts")
            if not old:
                conn.execute(self.legacy.insert().values(plan_id=plan["id"], plan_hash=digest(plan), application_ref=reference, created_at=now()))
            return {"applicationRef": reference, "planHash": digest(plan), "proofSource": "explicit-demo-legacy-pin", "productionAllowed": False}

    def require_legacy_demo_plan(self, plan):
        if not self.store.settings.demo:
            raise HTTPException(409, "Legacy execution bindings are forbidden in production")
        stored = self.store.plan(plan.get("id"), plan.get("ownerId"))
        projection = {key: value for key, value in plan.items() if key not in {"taskId", "runId"}}
        if projection != stored:
            raise HTTPException(409, "Legacy plan differs from its exact immutable stored body")
        if "taskId" in plan or "runId" in plan:
            if not plan.get("taskId") or not plan.get("runId"):
                raise HTTPException(409, "Legacy execution projection requires both bound task and run")
            task = self.store.task(plan["taskId"], plan["ownerId"])
            if task["id"] != plan["taskId"] or task["run_id"] != plan["runId"] or task["plan_id"] != stored["id"]:
                raise HTTPException(409, "Legacy execution projection differs from the persisted owner task/run binding")
        with self.db.read() as conn:
            row = conn.execute(select(self.legacy).where(self.legacy.c.plan_id == plan.get("id"))).mappings().first()
            if not row or row["plan_hash"] != digest(stored):
                raise HTTPException(409, "Explicit exact legacy demo application pin is required")
            return row["application_ref"]

    def inspect(self, actor, identifier, version):
        with self.db.read() as conn:
            body, state = self._row(conn, identifier, version)
            self._scoped(actor, state)
            return {"application": body, "governance": state, "immutableBodyPreserved": True}

    def inspect_review(self, actor, review_id):
        with self.db.read() as conn:
            row = conn.execute(select(self.reviews).where(self.reviews.c.id == review_id)).mappings().first()
            if not row:
                raise HTTPException(404, "Application review not found")
            _, state = self._row(conn, row["application_id"], row["version"])
            self.auth.require(actor, "components:read")
            if actor != state["author_id"] and not self._admin(actor):
                raise HTTPException(404, "Scoped application review not found")
            return self._review(conn, dict(row))

    def list_reviews(self, actor, *, all_authors=False):
        self.auth.require(actor, "agent_os:admin" if all_authors else "components:read")
        with self.db.read() as conn:
            query = select(self.reviews).order_by(self.reviews.c.created_at.desc()).limit(100)
            if not all_authors:
                query = query.where(self.reviews.c.author_id == actor)
            return [self._review(conn, dict(row)) for row in conn.execute(query).mappings()]

    def list_definitions(self, actor, *, all_authors=False):
        self.auth.require(actor, "agent_os:admin" if all_authors else "components:read")
        with self.db.read() as conn:
            query = select(self.states).order_by(self.states.c.id, self.states.c.version.desc()).limit(100)
            if not all_authors:
                query = query.where(self.states.c.author_id == actor)
            return [{"application": self._row(conn, row["id"], row["version"])[0], "governance": dict(row), "immutableBodyPreserved": True}
                    for row in conn.execute(query).mappings()]

    def list_active(self, actor):
        self.auth.require(actor, "components:read")
        result = []
        with self.db.read() as conn:
            for row in conn.execute(select(self.versions).order_by(self.versions.c.id, self.versions.c.version.desc()).limit(100)).mappings():
                try:
                    body, state = self._row(conn, row["id"], row["version"])
                    self._active(conn, body, state)
                    result.append(body)
                except HTTPException as error:
                    if error.status_code not in {404, 409}:
                        raise
        return result

    def _deactivate(self, actor, identifier, version, request_id, reason, state):
        self.auth.require(actor, "agent_os:admin" if state == "withdrawn" else "components:write")
        if not isinstance(reason, str) or len(reason) > 2000:
            raise HTTPException(422, "Bounded application status reason required")
        MaterialGovernance._safe_data(reason)
        with self.db.write() as conn:
            body, current = self._row(conn, identifier, version)
            if state == "archived" and actor != current["author_id"] and not self._admin(actor):
                raise HTTPException(404, "Scoped application version not found")
            fingerprint = digest({"action": state, "ref": self.pin(body), "reason": reason})
            old = self.db.old(conn, self.commands, actor, request_id, fingerprint)
            if old is not None:
                return old
            self.auth.require(actor, "agent_os:admin" if state == "withdrawn" else "components:write")
            conn.execute(self.states.update().where(self.states.c.id == identifier, self.states.c.version == version).values(state=state, reason=reason, updated_at=now()))
            return self.db.record(conn, self.commands, actor, request_id, fingerprint, "application." + state,
                                  {"applicationRef": self.pin(body), "state": state, "reason": reason, "immutableBodyPreserved": True})

    def archive(self, actor, identifier, version, request_id, reason=""):
        return self._deactivate(actor, identifier, version, request_id, reason, "archived")

    def withdraw(self, actor, identifier, version, request_id, reason=""):
        return self._deactivate(actor, identifier, version, request_id, reason, "withdrawn")

    def seed_demo(self):
        """Trusted startup only; two explicit configs over proved immutable seeds."""
        if not self.store.settings.demo:
            raise ValueError("Demo application seed approval is forbidden in production")
        governance = self.store.material_governance
        governance.adopt_demo_bootstrap()
        # Read historical seed bodies, including withdrawn versions. Bootstrap
        # proof above validates origin/hash/audit and never restores activation.
        seeds = {item["id"]: item for item in self.store.materials() if item["version"] == 1 and item.get("origin") == "factory synthetic fixture"}
        definitions = [*demo_definitions(seeds), *demo_v2_definitions(seeds)]
        with self.db.write() as conn:
            for definition in definitions:
                identifier = definition["id"]
                existing = conn.execute(select(self.versions).where(self.versions.c.id == identifier, self.versions.c.version == 1)).mappings().first()
                if existing:
                    body, state = self._row(conn, identifier, 1)
                    expected = {key: value for key, value in body.items() if key not in {"version", "createdAt", "sha256", "schema", "origin"}}
                    if expected != definition or not state["bootstrap"] or state["author_id"] != "demo-bootstrap":
                        raise HTTPException(409, "Demo application seed conflicts with existing immutable lineage")
                    continue  # Never restore withdrawal/archive on restart.
                body = {**definition, "version": 1, "createdAt": "1970-01-01T00:00:00+00:00", "schema": 1, "origin": "factory synthetic application fixture"}
                body["sha256"] = digest(body)
                conn.execute(self.versions.insert().values(id=identifier, version=1, body=body, sha=body["sha256"]))
                conn.execute(self.states.insert().values(id=identifier, version=1, author_id="demo-bootstrap", state="published", bootstrap=True, updated_at=now()))
        return {"seeded": [definition["id"] for definition in definitions], "approvalMode": "verified-demo-application-bootstrap", "productionAllowed": False}


def demo_definitions(seeds):
    """Configuration fixtures are the only place application IDs choose defaults."""
    def mode(ids, tools, caps, *, ask=0):
        return ModeDefinition.model_validate({"materialRefs": [ApplicationService.pin(seeds[mid]) for mid in ids],
            "capabilities": caps, "toolOrder": tools, "config": {"askScopeBelowLength": ask}})
    common = ["demo-model", "local-environment"]
    research = [*common, "research-skill", "research-prompt", "synthetic-knowledge", "literature-tool", "question-tool"]
    literature = mode(research, ["literature_search", "ask_scope"], ["research:read", "question:ask"], ask=12)
    experiment = mode([*research, "experiment-tool"], ["literature_search", "ask_scope", "run_experiment"],
                      ["research:read", "question:ask", "experiment:synthetic"], ask=12)
    checksum = mode([*common, "checksum-tool"], ["checksum"], ["checksum:read"])
    return [ApplicationDefinition(id="research", name="Auto-Research", defaultForDiscovery=True,
                discoveryKeywords=["research", "investigate", "literature", "研究", "调研"], modes={"literature": literature, "experiment": experiment}).model_dump(exclude_none=True),
            ApplicationDefinition(id="checksum", name="Checksum", discoveryKeywords=["checksum", "sha256", "校验"],
                modes={"literature": checksum, "experiment": checksum}).model_dump(exclude_none=True)]


def demo_v2_definitions(seeds):
    """Additive neutral fixture; historical checksum v1 remains untouched."""
    return [ApplicationDefinitionV2(contractVersion=2, id="checksum-neutral", name="Checksum (neutral contract)",
        defaultMode="execute", modes={"execute": ModeDefinitionV2(
            materialRefs=[PinnedRef.model_validate(ApplicationService.pin(seeds[mid])) for mid in ("demo-model", "local-environment", "checksum-tool")],
            capabilities=["checksum:read"], toolOrder=["checksum"])}).model_dump(exclude_none=True)]


class ApplicationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: str = Field(min_length=1, max_length=200)


class DraftApplication(ApplicationCommand):
    definition: dict[str, Any]


class ApplicationDecision(ApplicationCommand):
    approved: StrictBool


class ApplicationStatus(ApplicationCommand):
    reason: str = Field(default="", max_length=2000)


def application_router(auth, service):
    router = APIRouter(prefix="/api/factory/applications")
    def actor(request):
        return auth.user(request)["id"]
    @router.get("")
    def active(request: Request):
        return service.list_active(actor(request))
    @router.post("/drafts", status_code=201)
    def draft(body: DraftApplication, request: Request):
        return service.create_draft(actor(request), body.definition, body.requestId)
    @router.get("/definitions")
    def definitions(request: Request, allAuthors: bool = False):
        return service.list_definitions(actor(request), all_authors=allAuthors)
    @router.get("/reviews")
    def reviews(request: Request, allAuthors: bool = False):
        return service.list_reviews(actor(request), all_authors=allAuthors)
    @router.get("/reviews/{review_id}")
    def review(review_id: str, request: Request):
        return service.inspect_review(actor(request), review_id)
    @router.post("/reviews/{review_id}/decision")
    def decision(review_id: str, body: ApplicationDecision, request: Request):
        return service.decide_publication(actor(request), review_id, body.approved, body.requestId)
    @router.get("/{identifier}/versions/{version}")
    def inspect(identifier: str, version: int, request: Request):
        return service.inspect(actor(request), identifier, version)
    @router.post("/{identifier}/versions/{version}/revise", status_code=201)
    def revise(identifier: str, version: int, body: DraftApplication, request: Request):
        return service.revise(actor(request), identifier, version, body.definition, body.requestId)
    @router.post("/{identifier}/versions/{version}/review", status_code=201)
    def request_review(identifier: str, version: int, body: ApplicationCommand, request: Request):
        return service.request_publication(actor(request), identifier, version, body.requestId)
    @router.post("/{identifier}/versions/{version}/archive")
    def archive(identifier: str, version: int, body: ApplicationStatus, request: Request):
        return service.archive(actor(request), identifier, version, body.requestId, body.reason)
    @router.post("/{identifier}/versions/{version}/withdraw")
    def withdraw(identifier: str, version: int, body: ApplicationStatus, request: Request):
        return service.withdraw(actor(request), identifier, version, body.requestId, body.reason)
    return router
