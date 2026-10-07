"""Receiver-local runtime bindings proved against an exact immutable origin plan.

Mappings are operator-installed inert metadata. Proofs contain neither handles
nor credentials/endpoints and never rewrite the saved origin execution manifest.
Current source authority, application approval and receiver policy remain the
handoff/admission services' responsibility; every effective binding rechecks the
current operator map and exact receiver-owned connection before use.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from dataclasses import dataclass
import re
from typing import Any, Mapping
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, select, text

from .connections import KINDS as CONNECTION_KINDS
from .execution_bindings import KINDS, LEGACY_DEMO
from .material_governance import MaterialGovernance, PinnedRef, normalize_runtime_binding
from .store import digest

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_PIN = {"ref", "version", "fingerprint", "kind", "revision", "capabilities", "taskId"}


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("An exact bounded opaque identifier is required")
    return value


def _configuration(value):
    if not isinstance(value, dict) or set(value) != {"revision", "sha256"}:
        raise HTTPException(409, "REMOTE_BINDING_CONFIGURATION: exact configuration revision/hash is required")
    try:
        _identifier(value["revision"])
        if not isinstance(value["sha256"], str) or not _SHA.fullmatch(value["sha256"]):
            raise ValueError("Invalid configuration fingerprint")
    except ValueError as error:
        raise HTTPException(409, "REMOTE_BINDING_CONFIGURATION: exact configuration revision/hash is required") from error
    return copy.deepcopy(value)


def _spec(kind, value):
    if kind not in KINDS or not isinstance(value, dict) or set(value) - {"materialRef", "adapterId", "revision", "config", "connection", "toolName"}:
        raise ValueError("Invalid exact remote binding specification")
    required = {"materialRef", "adapterId", "revision", "config"} | ({"toolName"} if kind == "tool" else set())
    if not required <= set(value) or kind != "tool" and "toolName" in value:
        raise ValueError("Incomplete remote binding specification")
    MaterialGovernance._safe_data(value)
    result = copy.deepcopy(value)
    result["materialRef"] = PinnedRef.model_validate(result["materialRef"]).model_dump()
    for key in ("adapterId", "revision"):
        _identifier(result[key])
    raw = normalize_runtime_binding({key: result[key] for key in ("adapterId", "revision", "config")})
    if raw != {key: result[key] for key in raw}:
        raise ValueError("Binding configuration is not canonical inert data")
    if kind == "tool":
        _identifier(result["toolName"])
    pin = result.get("connection")
    if pin is not None:
        if not isinstance(pin, dict) or set(pin) != _PIN or type(pin["version"]) is not int or pin["version"] < 1:
            raise ValueError("An exact versioned connection pin is required")
        _identifier(pin["ref"])
        _identifier(pin["revision"])
        if not isinstance(pin["fingerprint"], str) or not _SHA.fullmatch(pin["fingerprint"]) or pin["kind"] not in CONNECTION_KINDS:
            raise ValueError("Invalid connection identity pin")
        if not isinstance(pin["capabilities"], list) or len(pin["capabilities"]) > 30 or len(set(pin["capabilities"])) != len(pin["capabilities"]):
            raise ValueError("Connection capabilities must be a bounded unique list")
        for cap in pin["capabilities"]:
            _identifier(cap)
        if pin["taskId"] is not None:
            UUID(pin["taskId"])
        _identifier(result["config"].get("connectionName"))
    elif result["config"].get("connectionName") is not None:
        raise ValueError("Logical connection configuration requires an exact pin")
    return result


@dataclass(frozen=True)
class TrustedRemoteBindingMapping:
    """Operator-only exact source-to-receiver mapping; never an HTTP body."""
    reference: str
    revision: str
    origin_ref: str
    origin_owner: str
    receiver_owner: str
    kind: str
    source_spec: Mapping[str, Any]
    effective_spec: Mapping[str, Any]

    def __post_init__(self):
        for value in (self.reference, self.revision, self.origin_ref):
            _identifier(value)
        for owner in (self.origin_owner, self.receiver_owner):
            if not isinstance(owner, str) or not 1 <= len(owner) <= 200 or any(ord(char) < 32 for char in owner):
                raise ValueError("An exact trusted owner is required")
        source, effective = _spec(self.kind, dict(self.source_spec)), _spec(self.kind, dict(self.effective_spec))
        if source["materialRef"] != effective["materialRef"] or source.get("toolName") != effective.get("toolName"):
            raise ValueError("Receiver mappings must preserve exact source material and native tool identity")
        source_pin, local_pin = source.get("connection"), effective.get("connection")
        if source_pin is None and local_pin is not None or source_pin is not None and local_pin is None:
            raise ValueError("Receiver mapping cannot add or discard a source connection requirement")
        if source_pin is not None and local_pin is not None and (source_pin["kind"] != local_pin["kind"] or not set(local_pin["capabilities"]) <= set(source_pin["capabilities"])):
            raise ValueError("Receiver connection scope must remain within the origin connection ceiling")
        object.__setattr__(self, "source_spec", source)
        object.__setattr__(self, "effective_spec", effective)

    def metadata(self):
        return {"reference": self.reference, "revision": self.revision, "originRef": self.origin_ref,
                "originOwner": self.origin_owner, "receiverOwner": self.receiver_owner, "kind": self.kind,
                "sourceSpec": copy.deepcopy(self.source_spec), "effectiveSpec": copy.deepcopy(self.effective_spec)}

    @property
    def fingerprint(self):
        return digest(self.metadata())


class RemoteBindingService:
    def __init__(self, store, auth, bindings, connections, mappings=None):
        self.store, self.auth, self.bindings, self.connections = store, auth, bindings, connections
        self.mappings = mappings if mappings is not None else {}
        metadata = MetaData()
        self.versions = Table("af_remote_binding_mapping_versions", metadata,
            Column("reference", String, primary_key=True), Column("revision", String, primary_key=True),
            Column("sha", String, nullable=False), Column("body", JSON, nullable=False))
        self.proofs = Table("af_remote_binding_proofs", metadata,
            Column("receipt_id", String, primary_key=True), Column("receiver_owner", String, nullable=False),
            Column("receiver_plan_id", String, nullable=False, unique=True), Column("sha", String, nullable=False),
            Column("body", JSON, nullable=False))
        metadata.create_all(store.engine)
        with self._write() as conn:
            for key, mapping in self.mappings.items():
                if not isinstance(mapping, TrustedRemoteBindingMapping) or key != mapping.reference:
                    raise ValueError("Only exact operator-installed remote binding mappings are accepted")
                row = conn.execute(select(self.versions).where(self.versions.c.reference == key,
                    self.versions.c.revision == mapping.revision)).mappings().first()
                if row and (row["sha"] != mapping.fingerprint or digest(row["body"]) != mapping.fingerprint):
                    raise ValueError("A remote binding mapping revision cannot be rebound")
                if not row:
                    conn.execute(self.versions.insert().values(reference=key, revision=mapping.revision,
                        sha=mapping.fingerprint, body=mapping.metadata()))

    @contextmanager
    def _read(self):
        shared = getattr(self.store, "_connection", None)
        existing = shared.get() if shared is not None else None
        if existing is not None:
            yield existing
            return
        with self.store.engine.connect() as conn:
            token = shared.set(conn) if shared is not None else None
            try:
                yield conn
            finally:
                if shared is not None and token is not None:
                    shared.reset(token)

    @contextmanager
    def _write(self):
        shared = getattr(self.store, "_connection", None)
        existing = shared.get() if shared is not None else None
        if existing is not None:
            conn = existing
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_remote_binding_proofs'))"))
            yield conn
            return
        with self.store.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_remote_binding_proofs'))"))
            token = shared.set(conn) if shared is not None else None
            try:
                yield conn
            finally:
                if shared is not None and token is not None:
                    shared.reset(token)

    def validate_source(self, plan):
        """Validate original material/config/connection pins without local lookup."""
        manifest = plan.get("executionBindings")
        if not isinstance(manifest, dict) or set(manifest) != {"schema", "model", "environment", "tools", "knowledge", "sha256"} or manifest["schema"] != 1:
            raise HTTPException(409, "REMOTE_BINDING_SOURCE: an exact modern source binding manifest is required")
        if digest({key: value for key, value in manifest.items() if key != "sha256"}) != manifest["sha256"]:
            raise HTTPException(409, "REMOTE_BINDING_SOURCE: original binding manifest changed")
        materials = plan.get("materials")
        if not isinstance(materials, list) or not 1 <= len(materials) <= 30 or not isinstance(manifest["tools"], list) or not isinstance(manifest["knowledge"], list):
            raise HTTPException(409, "REMOTE_BINDING_SOURCE: bounded source materials/bindings are required")
        by_ref = {}
        for material in materials:
            if not isinstance(material, dict) or digest({key: value for key, value in material.items() if key not in {"sha256", "published", "createdAt"}}) != material.get("sha256"):
                raise HTTPException(409, "REMOTE_BINDING_SOURCE: exact source material integrity differs")
            ref = {key: material[key] for key in ("id", "version", "sha256")}
            if digest(ref) in by_ref:
                raise HTTPException(409, "REMOTE_BINDING_SOURCE: source material reference is duplicated")
            by_ref[digest(ref)] = material
        visited, tools, connections = set(), [], {}
        try:
            for kind, raw in self.bindings._items(manifest):
                spec = _spec(kind, raw)
                key = digest(spec["materialRef"])
                material = by_ref.get(key)
                if material is None or material["kind"] != kind or key in visited:
                    raise ValueError("Source binding differs from its selected material")
                visited.add(key)
                raw_binding = material.get("runtimeBinding")
                if raw_binding is None:
                    from .catalog import SEEDS
                    legacy = LEGACY_DEMO.get(material["id"])
                    seed = next((item for item in SEEDS if item[0] == material["id"]), None)
                    if not self.store.settings.demo or legacy is None or legacy[0] != kind or seed is None or material.get("content") != seed[3]:
                        raise ValueError("Missing explicit source runtime binding")
                    raw_binding = {"adapterId": legacy[1], "revision": "1", "config": {}}
                if {key: spec[key] for key in ("adapterId", "revision", "config")} != normalize_runtime_binding(raw_binding):
                    raise ValueError("Original source adapter/config differs from its material")
                if kind == "tool":
                    if spec["toolName"] != material["content"]:
                        raise ValueError("Source native tool differs from its material")
                    tools.append(spec["toolName"])
                if spec.get("connection") is not None:
                    name = spec["config"]["connectionName"]
                    if name in connections and connections[name] != spec["connection"]:
                        raise ValueError("A logical source connection name has inconsistent pins")
                    connections[name] = spec["connection"]
            expected = {digest({key: item[key] for key in ("id", "version", "sha256")}) for item in materials if item["kind"] in KINDS}
            if visited != expected or len(set(tools)) != len(tools) or set(tools) != set(plan.get("tools", [])):
                raise ValueError("Source binding closure differs from selected tools/materials")
            if "bindingManifest" in plan:
                anchor = plan["bindingManifest"]
                if (not isinstance(anchor, dict) or anchor.get("sha256") != digest({key: value for key, value in anchor.items() if key != "sha256"})
                        or anchor.get("executionBindingsSha256") != manifest["sha256"] or anchor.get("connections") != connections
                        or anchor.get("materialRefs") != plan.get("materialRefs")):
                    raise ValueError("Source symbolic connection/material anchor differs from exact binding pins")
        except (ValueError, TypeError, KeyError, HTTPException) as error:
            raise HTTPException(409, "REMOTE_BINDING_SOURCE: original exact runtime specification differs") from error
        return copy.deepcopy(manifest)

    def _mapping(self, conn, reference, revision, fingerprint):
        value = self.mappings.get(reference)
        if not isinstance(value, TrustedRemoteBindingMapping) or value.revision != revision or value.fingerprint != fingerprint:
            raise HTTPException(409, "REMOTE_BINDING_CHANGED: current operator mapping changed or is unavailable")
        row = conn.execute(select(self.versions).where(self.versions.c.reference == reference,
            self.versions.c.revision == revision)).mappings().first()
        if not row or row["sha"] != fingerprint or digest(row["body"]) != fingerprint:
            raise HTTPException(409, "REMOTE_BINDING_INTEGRITY: immutable operator mapping changed")
        return value

    def _effective_check(self, kind, source, effective, material, owner, context=None):
        entry = self.bindings._entry(kind, effective)
        if source["materialRef"] != effective["materialRef"] or source.get("toolName") != effective.get("toolName") or not set(entry.permissions) <= set(material.get("permissions", [])):
            raise HTTPException(409, "REMOTE_BINDING_SCOPE: receiver adapter exceeds exact source material authority")
        source_pin, pin = source.get("connection"), effective.get("connection")
        if kind == "tool" and pin is not None and not set(pin["capabilities"]) <= set(material.get("permissions", [])):
            raise HTTPException(409, "REMOTE_BINDING_SCOPE: receiver tool connection exceeds exact source material permissions")
        if source_pin is not None:
            if pin is None or source_pin["kind"] != pin["kind"] or not set(pin["capabilities"]) <= set(source_pin["capabilities"]) or not set(entry.required_capabilities) <= set(source_pin["capabilities"]):
                raise HTTPException(409, "REMOTE_BINDING_SCOPE: receiver connection exceeds origin capability ceiling")
        elif pin is not None:
            raise HTTPException(409, "REMOTE_BINDING_SCOPE: mapping cannot add a connection grant")
        self.bindings._connection(owner, entry, effective, context, resolve=False)

    def prepare(self, origin, remote_owner, origin_task, receipt_id, manifest, *, receiver_plan_id, source_configuration):
        self.auth.require(remote_owner, "run")
        for value in (origin_task, receipt_id, receiver_plan_id):
            UUID(value)
        source = manifest.get("plan") if isinstance(manifest, dict) else None
        if not isinstance(source, dict) or set(manifest) != {"plan", "sha256"} or digest(source) != manifest["sha256"] or origin.identity_map.get(source.get("ownerId")) != remote_owner:
            raise HTTPException(409, "REMOTE_BINDING_IDENTITY: exact origin manifest/receiver owner mapping is required")
        source_manifest = self.validate_source(source)
        source_config = _configuration(source_configuration)
        receiver_config = _configuration({"revision": origin.configuration_revision, "sha256": origin.fingerprint})
        materials = {digest({key: value[key] for key in ("id", "version", "sha256")}): value for value in source["materials"]}
        entries = []
        with self._write() as conn:
            for kind, spec in self.bindings._items(source_manifest):
                candidates = [value for value in self.mappings.values() if isinstance(value, TrustedRemoteBindingMapping)
                    and value.origin_ref == origin.reference and value.origin_owner == source["ownerId"]
                    and value.receiver_owner == remote_owner and value.kind == kind and dict(value.source_spec) == spec]
                if len(candidates) > 1:
                    raise HTTPException(409, "REMOTE_BINDING_AMBIGUOUS: exact source has multiple receiver mappings")
                mapping = candidates[0] if candidates else None
                if mapping is None and spec.get("connection") is not None:
                    raise HTTPException(409, "REMOTE_BINDING_REQUIRED: source connection has no exact receiver mapping")
                effective = copy.deepcopy(dict(mapping.effective_spec) if mapping else spec)
                if mapping:
                    self._mapping(conn, mapping.reference, mapping.revision, mapping.fingerprint)
                self._effective_check(kind, spec, effective, materials[digest(spec["materialRef"])], remote_owner)
                entries.append({"kind": kind, "sourceSpec": spec, "effectiveSpec": effective,
                    "mappingReference": mapping.reference if mapping else None, "mappingRevision": mapping.revision if mapping else None,
                    "mappingSha256": mapping.fingerprint if mapping else None})
            body = {"schema": 1, "originRef": origin.reference, "receiptId": receipt_id,
                "originTaskId": origin_task, "originOwner": source["ownerId"], "receiverOwner": remote_owner,
                "receiverPlanId": receiver_plan_id, "manifestHash": manifest["sha256"], "sourceConfiguration": source_config,
                "receiverConfiguration": receiver_config, "sourcePlan": copy.deepcopy(source), "sourceBindings": source_manifest, "entries": entries}
            old = conn.execute(select(self.proofs).where(self.proofs.c.receipt_id == receipt_id)).mappings().first()
            if old:
                if old["body"] != body or old["sha"] != digest(body) or old["receiver_owner"] != remote_owner or old["receiver_plan_id"] != receiver_plan_id:
                    raise HTTPException(409, "REMOTE_BINDING_CONFLICT: original receiver proof intent changed")
            else:
                if conn.execute(select(self.proofs.c.receipt_id).where(self.proofs.c.receiver_plan_id == receiver_plan_id)).first():
                    raise HTTPException(409, "REMOTE_BINDING_CONFLICT: imported receiver plan already belongs to another receipt")
                conn.execute(self.proofs.insert().values(receipt_id=receipt_id, receiver_owner=remote_owner,
                    receiver_plan_id=receiver_plan_id, sha=digest(body), body=body))
            return {**copy.deepcopy(body), "sha256": digest(body)}

    def _proof(self, conn, root):
        handoff = root.get("remoteHandoff")
        if not isinstance(handoff, dict):
            raise HTTPException(409, "REMOTE_BINDING_UNBOUND: exact root handoff proof is required")
        row = conn.execute(select(self.proofs).where(self.proofs.c.receipt_id == handoff.get("receiptId"),
            self.proofs.c.receiver_owner == root.get("ownerId"))).mappings().first()
        if not row or row["receiver_plan_id"] != root.get("id") or row["sha"] != digest(row["body"]) or row["sha"] != handoff.get("bindingProofSha256"):
            raise HTTPException(409, "REMOTE_BINDING_INTEGRITY: exact receipt/owner/root proof differs")
        proof = row["body"]
        if proof["receiverOwner"] != root["ownerId"] or proof["receiptId"] != handoff.get("receiptId") or proof["originRef"] != handoff.get("originRef") or proof["originTaskId"] != handoff.get("originTaskId") or proof["manifestHash"] != handoff.get("manifestHash") or digest(proof["sourcePlan"]) != proof["manifestHash"]:
            raise HTTPException(409, "REMOTE_BINDING_IDENTITY: root origin manifest binding differs")
        ignored = {"id", "ownerId", "createdAt", "fingerprint"}
        if proof['sourcePlan'].get('delegation'):
            receiver = getattr(self.store, 'remote_scientific_receiver', None)
            if receiver is None:
                raise HTTPException(409, 'Scientific receiver service is unavailable')
            phase = conn.execute(text('SELECT body FROM af_remote_scientific_phases WHERE receipt_id=:id AND owner_id=:owner'),
                {'id': handoff['receiptId'], 'owner': root['ownerId']}).mappings().first()
            body = phase['body'] if phase else None
            if (body is None or digest(body['binding']) != body['bindingSha256']
                    or body['binding']['receiptId'] != handoff['receiptId']
                    or body['binding']['ownerId'] != root['ownerId']):
                raise HTTPException(409, 'Scientific receiver binding is unavailable')
            envelope = {'schema': 1, 'projectId': body['binding']['projectId'],
                'scope': body['binding']['scope'], 'candidate': body['candidate']}
            from .remote_scientific_origin import validate_source
            if receiver is None or envelope is None:
                raise HTTPException(409, 'Remote child has no scientific placement authority')
            validate_source(proof['sourcePlan'], envelope)
            if root.get('delegation') is not None or root.get('budget') != {**proof['sourcePlan']['budget'], 'depth': 0}:
                raise HTTPException(409, 'Receiver scientific phase must remain a local root')
            ignored |= {'delegation', 'budget'}
        if (set(root) - set(proof["sourcePlan"]) - {"remoteHandoff", "taskId", "runId"}
                or any(root.get(key) != value for key, value in proof["sourcePlan"].items() if key not in ignored)):
            raise HTTPException(409, "REMOTE_BINDING_SOURCE: imported root rewrote its immutable source plan")
        return proof

    @staticmethod
    def _material_subset(materials, root):
        known = {digest({key: item[key] for key in ("id", "version", "sha256")}): item for item in root["materials"]}
        def immutable(value):
            return {key: item for key, item in value.items() if key not in {"published", "createdAt"}}
        for material in materials:
            original = known.get(digest({key: material[key] for key in ("id", "version", "sha256")}))
            # Receiver publication timestamps are local provenance; the exact
            # content/config/permissions and pinned hash remain the root's.
            if original is None or immutable(material) != immutable(original):
                raise HTTPException(409, "REMOTE_BINDING_SCOPE: child selected material is outside exact root proof")

    def inspect(self, receipt_id, remote_owner):
        """Owner-scoped immutable proof evidence, including after revocation.

        Historical reads deliberately do not resolve a handle or check an
        execution mapping's current availability; cleanup/evidence must remain
        observable when an operator withdraws a map or user connection.
        """
        self.auth.require(remote_owner, "read")
        with self._read() as conn:
            row = conn.execute(select(self.proofs).where(self.proofs.c.receipt_id == receipt_id,
                self.proofs.c.receiver_owner == remote_owner)).mappings().first()
            if not row:
                raise HTTPException(404, "Owner-bound remote binding proof not found")
            body = row["body"]
            if digest(body) != row["sha"] or body.get("receiptId") != receipt_id or body.get("receiverOwner") != remote_owner or body.get("receiverPlanId") != row["receiver_plan_id"]:
                raise HTTPException(409, "REMOTE_BINDING_INTEGRITY: immutable receiver evidence changed")
            # Goals/prompts/material content are already present in scoped task
            # detail. This projection needs only exact binding/config provenance.
            return {key: copy.deepcopy(body[key]) for key in ("schema", "originRef", "receiptId", "originTaskId",
                "originOwner", "receiverOwner", "receiverPlanId", "manifestHash", "sourceConfiguration", "receiverConfiguration", "entries")} | {"sha256": row["sha"]}

    def _root(self, plan, context=None):
        if plan.get("remoteHandoff"):
            return plan
        binding = plan.get("delegation")
        if not isinstance(binding, dict):
            return None
        root_task = self.store.task(binding.get("rootTaskId"), plan["ownerId"])
        root = self.store.plan(root_task["plan_id"], plan["ownerId"])
        if not root.get("remoteHandoff"):
            return None
        rows = self.store.sql("SELECT * FROM af_delegation_links WHERE plan_id=:plan AND owner_id=:owner",
                              plan=plan.get("id"), owner=plan["ownerId"])
        if len(rows) != 1 or rows[0]["root_id"] != root_task["id"] or rows[0]["parent_id"] != binding.get("parentTaskId") or rows[0]["depth"] != binding.get("depth") or not rows[0]["child_id"]:
            raise HTTPException(409, "REMOTE_BINDING_ANCESTRY: exact persisted receiver child binding is required")
        child = self.store.task(rows[0]["child_id"], plan["ownerId"])
        if child["plan_id"] != plan["id"] or context is not None and (child["id"] != context.session_id or child["run_id"] != context.run_id):
            raise HTTPException(409, "REMOTE_BINDING_ANCESTRY: child native binding differs")
        # Existing native mandate/PlanPolicy independently enforce current scope,
        # budgets and every ancestor. Proof selection verifies the whole path too.
        cursor, seen = child, {child["id"]}
        while cursor["id"] != root_task["id"]:
            link = self.store.delegation._link(cursor["id"])
            if link is None or link["owner_id"] != plan["ownerId"] or link["root_id"] != root_task["id"]:
                raise HTTPException(409, "REMOTE_BINDING_ANCESTRY: receiver child path is unavailable")
            cursor = self.store.task(link["parent_id"], plan["ownerId"])
            if cursor["id"] in seen or len(seen) > 2:
                raise HTTPException(409, "REMOTE_BINDING_ANCESTRY: bounded receiver ancestry differs")
            seen.add(cursor["id"])
        return root

    def historical_spec(self, plan, kind, source, context=None):
        """Immutable receiver-local metadata for trusted cleanup, never execution.

        No current mapping/connection/run grant is renewed. The caller must
        independently prove its admitted effect and resolve only the originally
        recorded cleanup handle. Retired mappings remain evidence, not access.
        """
        root = self._root(plan, context)
        if root is None:
            return copy.deepcopy(source)
        manifest = self.validate_source(plan)
        if not any(item_kind == kind and item == source for item_kind, item in self.bindings._items(manifest)):
            raise HTTPException(409, "REMOTE_BINDING_SCOPE: cleanup source is outside the original plan")
        with self._read() as conn:
            proof = self._proof(conn, root)
            self._material_subset(plan["materials"], proof["sourcePlan"])
            entries = [entry for entry in proof["entries"] if entry["kind"] == kind and entry["sourceSpec"] == source]
            if len(entries) != 1:
                raise HTTPException(409, "REMOTE_BINDING_SCOPE: cleanup requires one exact admitted receiver specification")
            return copy.deepcopy(entries[0]["effectiveSpec"])

    def historical_manifest(self, plan, context=None):
        """Provenance-only manifest; resolves no executable handle or grant."""
        manifest = self.validate_source(plan)
        result = {"schema": 1, "tools": [], "knowledge": []}
        for kind, source in self.bindings._items(manifest):
            effective = self.historical_spec(plan, kind, source, context)
            if kind in {"tool", "knowledge"}:
                result[kind + ("s" if kind == "tool" else "")].append(effective)
            else:
                result[kind] = effective
        return {**result, "sha256": digest(result)}

    def effective(self, plan, source_manifest, context=None):
        root = self._root(plan, context)
        if root is None:
            return None
        self.auth.require(plan["ownerId"], "run")
        if source_manifest != self.validate_source(plan):
            raise HTTPException(409, "REMOTE_BINDING_SOURCE: requested source manifest differs")
        with self._read() as conn:
            proof = self._proof(conn, root)
            self._material_subset(plan["materials"], proof["sourcePlan"])
            known = {(entry["kind"], digest(entry["sourceSpec"])): entry for entry in proof["entries"]}
            materials = {digest({key: value[key] for key in ("id", "version", "sha256")}): value for value in plan["materials"]}
            result = {"schema": 1, "tools": [], "knowledge": []}
            for kind, source in self.bindings._items(source_manifest):
                entry = known.get((kind, digest(source)))
                if entry is None or entry["sourceSpec"] != source:
                    raise HTTPException(409, "REMOTE_BINDING_SCOPE: child/source specification is outside exact root proof")
                if entry["mappingReference"]:
                    mapping = self._mapping(conn, entry["mappingReference"], entry["mappingRevision"], entry["mappingSha256"])
                    if mapping.origin_ref != proof["originRef"] or mapping.origin_owner != proof["originOwner"] or mapping.receiver_owner != plan["ownerId"] or dict(mapping.source_spec) != source or dict(mapping.effective_spec) != entry["effectiveSpec"]:
                        raise HTTPException(409, "REMOTE_BINDING_IDENTITY: current mapping owner/source differs")
                effective = copy.deepcopy(entry["effectiveSpec"])
                self._effective_check(kind, source, effective, materials[digest(source["materialRef"])], plan["ownerId"], context)
                if kind in {"tool", "knowledge"}:
                    result[kind + ("s" if kind == "tool" else "")].append(effective)
                else:
                    result[kind] = effective
            return {**result, "sha256": digest(result)}

    def build_inherited(self, materials, owner, root_plan, connections=None):
        """Trusted child assembly: narrow exact source specs, never substitute pins."""
        if root_plan["ownerId"] != owner:
            raise HTTPException(409, "REMOTE_BINDING_IDENTITY: receiver child owner differs")
        root = self._root(root_plan)
        if root is None:
            raise HTTPException(409, "REMOTE_BINDING_UNBOUND: receiver ancestor proof is required")
        original = self.validate_source(root)
        self.effective(root, original)
        self._material_subset(materials, root)
        selected = {digest({key: item[key] for key in ("id", "version", "sha256")}): item for item in materials}
        result = {"schema": 1, "tools": [], "knowledge": []}
        for kind, spec in self.bindings._items(original):
            if digest(spec["materialRef"]) not in selected:
                continue
            if kind in {"tool", "knowledge"}:
                result[kind + ("s" if kind == "tool" else "")].append(copy.deepcopy(spec))
            else:
                result[kind] = copy.deepcopy(spec)
        if "model" not in result or "environment" not in result:
            raise HTTPException(409, "REMOTE_BINDING_SCOPE: child must retain exact root model/environment")
        manifest = {**result, "sha256": digest(result)}
        self.validate_source({"materials": materials, "tools": [value["toolName"] for value in result["tools"]], "executionBindings": manifest})
        if connections is not None:
            inherited = {spec["config"]["connectionName"]: spec["connection"] for _, spec in self.bindings._items(manifest) if spec.get("connection")}
            if dict(connections) != inherited:
                raise HTTPException(409, "REMOTE_BINDING_SCOPE: child cannot replace original symbolic connection pins")
        return manifest
