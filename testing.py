from __future__ import annotations

import io
import os
from uuid import uuid4
from typing import Any, Dict, List

import pytest
import httpx


def _require_api_host() -> str:
    api_host = os.getenv("API_HOST")
    if not api_host:
        pytest.fail(
            "Set API_HOST to run API integration tests (e.g. http://rhyolite-api:8000)."
        )
    if not (api_host.startswith("http://") or api_host.startswith("https://")):
        api_host = "http://" + api_host
    return api_host.rstrip("/")


def _complex_kinds(name_suffix: str) -> List[Dict[str, Any]]:
    # Draft 2020-12 compatible, deliberately complex (nested, arrays, pattern, enums, oneOf).
    return [
        {
            "name": f"person_{name_suffix}",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "email": {"type": "string", "format": "email"},
                    "age": {"type": "integer", "minimum": 0},
                    "is_active": {"type": "boolean"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "profile": {
                        "type": "object",
                        "properties": {
                            "bio": {"type": "string"},
                            "skills": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "level": {
                                            "type": "string",
                                            "enum": [
                                                "beginner",
                                                "intermediate",
                                                "expert",
                                            ],
                                        },
                                    },
                                    "required": ["name", "level"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["bio"],
                        "additionalProperties": True,
                    },
                    "metadata": {
                        "type": "object",
                        "patternProperties": {
                            "^[a-z0-9_]{1,32}$": {
                                "type": ["string", "number", "boolean"]
                            }
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["name", "is_active"],
                "additionalProperties": True,
            },
        },
        {
            "name": f"document_{name_suffix}",
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "published": {"type": "boolean"},
                    "version": {"type": "integer", "minimum": 1},
                    "metrics": {
                        "type": "object",
                        "properties": {
                            "views": {"type": "integer", "minimum": 0},
                            "rating": {"type": "number", "minimum": 0, "maximum": 5},
                        },
                        "required": ["views"],
                        "additionalProperties": False,
                    },
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "content": {"type": "string"},
                                "order": {"type": "integer"},
                            },
                            "required": ["heading", "content", "order"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "version"],
                "additionalProperties": True,
            },
        },
        {
            "name": f"event_{name_suffix}",
            "schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "timestamp": {"type": "string", "format": "date-time"},
                    "payload": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {"const": "click"},
                                    "x": {"type": "number"},
                                    "y": {"type": "number"},
                                },
                                "required": ["kind", "x", "y"],
                                "additionalProperties": False,
                            },
                            {
                                "type": "object",
                                "properties": {
                                    "kind": {"const": "view"},
                                    "duration_ms": {"type": "integer", "minimum": 0},
                                },
                                "required": ["kind", "duration_ms"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                },
                "required": ["name", "timestamp", "payload"],
                "additionalProperties": False,
            },
        },
        {
            "name": f"asset_{name_suffix}",
            "schema": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "checksum": {"type": "string", "minLength": 8},
                    "content_type": {"type": "string"},
                    "size": {"type": "integer", "minimum": 0},
                    "extras": {"type": "object"},
                },
                "required": ["filename", "size"],
                "additionalProperties": True,
            },
        },
    ]


def _complex_edges_kinds(kinds: Dict[str, str]) -> List[Dict[str, Any]]:
    return [
        {
            "from_kind": kinds["person"],
            "to_kind": kinds["document"],
            "relation": "authored",
        },
        {
            "from_kind": kinds["person"],
            "to_kind": kinds["document"],
            "relation": "reviewed",
        },
        {
            "from_kind": kinds["person"],
            "to_kind": kinds["asset"],
            "relation": "uploaded",
        },
        {
            "from_kind": kinds["document"],
            "to_kind": kinds["document"],
            "relation": "related_to",
        },
        {
            "from_kind": kinds["document"],
            "to_kind": kinds["asset"],
            "relation": "has_asset",
        },
        {"from_kind": kinds["event"], "to_kind": kinds["person"], "relation": "actor"},
        {
            "from_kind": kinds["event"],
            "to_kind": kinds["document"],
            "relation": "target",
        },
        {"from_kind": kinds["event"], "to_kind": kinds["asset"], "relation": "touches"},
    ]


def _client(api_host: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=api_host, timeout=httpx.Timeout(30.0))


@pytest.mark.anyio
async def test_server_endpoints_full_lifecycle_single_file_httpx():
    api_host = _require_api_host()
    run_id = uuid4().hex[:10]

    kinds = _complex_kinds(run_id)
    kind_by_base = {k["name"].split("_")[0]: k["name"] for k in kinds}
    edges_kinds = _complex_edges_kinds(kind_by_base)

    async with _client(api_host) as client:
        # Health check (API up + DB schema ready)
        r = await client.get("/healty")
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # -------------------------
        # Seed Kinds + Edge-Kinds
        # -------------------------
        for k in kinds:
            r = await client.post("/kind", json=k)
            assert r.status_code == 200, r.text
            assert r.json()["name"] == k["name"]

        # Duplicate kind -> 409
        r = await client.post("/kind", json=kinds[0])
        assert r.status_code == 409

        # Read/list kinds
        r = await client.get(f"/kind/{kinds[0]['name']}")
        assert r.status_code == 200
        assert r.json()["name"] == kinds[0]["name"]

        r = await client.get("/kinds")
        assert r.status_code == 200
        listed_kinds = {x["name"] for x in r.json()}
        assert {k["name"] for k in kinds}.issubset(listed_kinds)

        for ek in edges_kinds:
            r = await client.post("/edges-kind", json=ek)
            assert r.status_code == 200, r.text
            assert r.json()["relation"] == ek["relation"]

        # Duplicate edges-kind -> 409
        r = await client.post("/edges-kind", json=edges_kinds[0])
        assert r.status_code == 409

        # Read/list edge-kinds
        r = await client.get("/edges-kinds")
        assert r.status_code == 200
        assert len(r.json()) >= len(edges_kinds)

        r = await client.get(f"/edges-kinds/{edges_kinds[0]['from_kind']}")
        assert r.status_code == 200
        assert all(x["from_kind"] == edges_kinds[0]["from_kind"] for x in r.json())

        r = await client.get(
            f"/edges-kinds/{edges_kinds[0]['from_kind']}/{edges_kinds[0]['to_kind']}"
        )
        assert r.status_code == 200
        assert all(
            x["from_kind"] == edges_kinds[0]["from_kind"]
            and x["to_kind"] == edges_kinds[0]["to_kind"]
            for x in r.json()
        )

        r = await client.get(
            f"/edges-kinds/{edges_kinds[0]['from_kind']}/{edges_kinds[0]['to_kind']}/{edges_kinds[0]['relation']}"
        )
        assert r.status_code == 200
        assert r.json()["relation"] == edges_kinds[0]["relation"]

        # -------------------------
        # Schema endpoint (kinds + edges_kinds)
        # -------------------------
        r = await client.get("/schema")
        assert r.status_code == 200, r.text
        j = r.json()
        assert "kinds" in j and "edges_kinds" in j
        assert isinstance(j["kinds"], list) and isinstance(j["edges_kinds"], list)
        listed_names = {x["name"] for x in j["kinds"]}
        assert {k["name"] for k in kinds}.issubset(listed_names)
        assert any(
            x["relation"] == edges_kinds[0]["relation"] for x in j["edges_kinds"]
        )

        # -------------------------
        # Create Nodes (CRUD)
        # -------------------------
        # Unknown kind -> 400
        r = await client.post("/node", json={"kind": "unknown", "payload": {}})
        assert r.status_code == 400

        person_payload = {
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "age": 36,
            "is_active": True,
            "tags": ["math", "computing"],
            "profile": {
                "bio": "First programmer.",
                "skills": [
                    {"name": "analysis", "level": "expert"},
                    {"name": "writing", "level": "intermediate"},
                ],
            },
            "metadata": {"team": "rhyolite", "rank": 1, "admin": True},
        }
        doc_payload = {
            "title": "Graph data warehouse",
            "body": "Rhyolite spec...",
            "published": False,
            "version": 1,
            "metrics": {"views": 12, "rating": 4.5},
            "sections": [
                {"heading": "Intro", "content": "...", "order": 1},
                {"heading": "Details", "content": "...", "order": 2},
            ],
        }
        asset_payload = {
            "filename": "blob.bin",
            "checksum": "deadbeefcafebabe",
            "content_type": "application/octet-stream",
            "size": 123,
            "extras": {"nested": {"ok": True}},
        }
        event_payload = {
            "name": "doc_view",
            "timestamp": "2025-12-29T10:11:12Z",
            "payload": {"kind": "view", "duration_ms": 321},
        }

        # Invalid payload (person missing required is_active) -> 400
        r = await client.post(
            "/node",
            json={"kind": kind_by_base["person"], "payload": {"name": "X"}},
        )
        assert r.status_code == 400

        r = await client.post(
            "/node",
            json={"kind": kind_by_base["person"], "payload": person_payload},
        )
        assert r.status_code == 200, r.text
        person = r.json()

        r = await client.post(
            "/node",
            json={"kind": kind_by_base["document"], "payload": doc_payload},
        )
        assert r.status_code == 200, r.text
        doc = r.json()

        r = await client.post(
            "/node",
            json={"kind": kind_by_base["asset"], "payload": asset_payload},
        )
        assert r.status_code == 200, r.text
        asset = r.json()

        r = await client.post(
            "/node",
            json={"kind": kind_by_base["event"], "payload": event_payload},
        )
        assert r.status_code == 200, r.text
        event = r.json()

        # Read node
        r = await client.get(f"/node/{person['id']}")
        assert r.status_code == 200
        assert r.json()["payload"]["name"] == "Ada Lovelace"

        # Update node
        old_updated_at = doc["updated_at"]
        doc_payload_updated = {**doc_payload, "published": True, "version": 2}
        r = await client.put(
            f"/node/{doc['id']}", json={"payload": doc_payload_updated}
        )
        assert r.status_code == 200
        doc2 = r.json()
        assert doc2["payload"]["published"] is True
        assert doc2["payload"]["version"] == 2
        assert doc2["updated_at"] != old_updated_at

        # Search nodes
        r = await client.post(
            "/nodes/search",
            json={
                "kinds": [kind_by_base["person"]],
                "query": {"name": "*Ada*", "is_active": True, "age": 36},
                "limit": 50,
            },
        )
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["id"] == person["id"]

        r = await client.post(
            "/nodes/search",
            json={
                "query": {"title": "*warehouse*"},
                "limit": 50,
            },
        )
        assert r.status_code == 200
        assert any(x["id"] == doc2["id"] for x in r.json())

        # Additional search tests with kinds and inner queries
        # Search documents with specific version and kinds filter
        r = await client.post(
            "/nodes/search",
            json={
                "kinds": [kind_by_base["document"]],
                "query": {"version": 2, "published": True},
                "limit": 50,
            },
        )
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["id"] == doc2["id"]

        # Search events with nested payload and kinds filter
        r = await client.post(
            "/nodes/search",
            json={
                "kinds": [kind_by_base["event"]],
                "query": {"payload.kind": "view", "payload.duration_ms": 321},
                "limit": 50,
            },
        )
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["id"] == event["id"]

        # Search assets with nested extras and kinds filter
        r = await client.post(
            "/nodes/search",
            json={
                "kinds": [kind_by_base["asset"]],
                "query": {"extras.nested.ok": True, "filename": "*blob*"},
                "limit": 50,
            },
        )
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["id"] == asset["id"]

        # Search with multiple kinds (person and document)
        r = await client.post(
            "/nodes/search",
            json={
                "kinds": [kind_by_base["person"], kind_by_base["document"]],
                "query": {"is_active": True},  # Only person has this field
                "limit": 50,
            },
        )
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["id"] == person["id"]

        # Search with kinds filter but empty query (should return all of that kind)
        r = await client.post(
            "/nodes/search",
            json={
                "kinds": [kind_by_base["event"]],
                "query": {},
                "limit": 50,
            },
        )
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["id"] == event["id"]

        # Search with kinds filter and wildcard in nested field
        r = await client.post(
            "/nodes/search",
            json={
                "kinds": [kind_by_base["person"]],
                "query": {"profile.bio": "*programmer*"},
                "limit": 50,
            },
        )
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["id"] == person["id"]

        # Search with kinds filter and array field match
        r = await client.post(
            "/nodes/search",
            json={
                "kinds": [kind_by_base["person"]],
                "query": {"tags": ["math", "computing"]},  # Exact array match
                "limit": 50,
            },
        )
        assert r.status_code == 200
        results = r.json()
        assert len(results) == 1
        assert results[0]["id"] == person["id"]

        # -------------------------
        # Create Edges (CRUD)
        # -------------------------
        # Forbidden relation -> 400
        r = await client.post(
            "/edge",
            json={
                "from_id": person["id"],
                "to_id": doc2["id"],
                "relation": "not_allowed",
            },
        )
        assert r.status_code == 400

        # Allowed edges
        r = await client.post(
            "/edge",
            json={
                "from_id": person["id"],
                "to_id": doc2["id"],
                "relation": "authored",
            },
        )
        assert r.status_code == 200
        edge_authored = r.json()

        # Duplicate edge -> 409
        r = await client.post(
            "/edge",
            json={
                "from_id": person["id"],
                "to_id": doc2["id"],
                "relation": "authored",
            },
        )
        assert r.status_code == 409

        r = await client.post(
            "/edge",
            json={
                "from_id": doc2["id"],
                "to_id": doc2["id"],
                "relation": "related_to",
            },
        )
        assert r.status_code == 200
        edge_self = r.json()

        r = await client.post(
            "/edge",
            json={
                "from_id": doc2["id"],
                "to_id": asset["id"],
                "relation": "has_asset",
            },
        )
        assert r.status_code == 200
        edge_has_asset = r.json()

        r = await client.post(
            "/edge",
            json={
                "from_id": event["id"],
                "to_id": person["id"],
                "relation": "actor",
            },
        )
        assert r.status_code == 200
        edge_actor = r.json()

        r = await client.post(
            "/edge",
            json={
                "from_id": event["id"],
                "to_id": doc2["id"],
                "relation": "target",
            },
        )
        assert r.status_code == 200
        edge_target = r.json()

        # List outgoing/incoming
        r = await client.get(f"/outgoing-edges/{person['id']}")
        assert r.status_code == 200
        outgoing_person = r.json()
        assert any(e["relation"] == "authored" for e in outgoing_person)

        r = await client.get(f"/incoming-edges/{doc2['id']}")
        assert r.status_code == 200
        incoming_doc = r.json()
        assert any(e["relation"] == "authored" for e in incoming_doc)

        r = await client.get(f"/edges/{person['id']}/{doc2['id']}")
        assert r.status_code == 200
        between = r.json()
        assert len(between) == 1
        assert between[0]["relation"] == "authored"

        # -------------------------
        # Attachments (CRUD)
        # -------------------------
        def make_random_file(size: int) -> bytes:
            return os.urandom(size)

        # Attach to person node (with query param name)
        person_file_bytes = make_random_file(1024)
        r = await client.post(
            "/attachment",
            params={"name": "profile.bin"},
            data={"node_id": person["id"]},
            files={
                "file": (
                    "ignored.bin",
                    io.BytesIO(person_file_bytes),
                    "application/octet-stream",
                )
            },
        )
        assert r.status_code == 200, r.text
        att_person = r.json()
        assert att_person["node_id"] == person["id"]
        assert att_person["name"] == "profile.bin"

        # Attach to doc node (no name param, uses filename)
        doc_file_bytes = make_random_file(2048)
        r = await client.post(
            "/attachment",
            data={"node_id": doc2["id"]},
            files={"file": ("doc.txt", io.BytesIO(doc_file_bytes), "text/plain")},
        )
        assert r.status_code == 200, r.text
        att_doc = r.json()
        assert att_doc["node_id"] == doc2["id"]
        assert att_doc["name"] == "doc.txt"

        # List attachments
        r = await client.get(f"/attachments/{person['id']}")
        assert r.status_code == 200
        assert len(r.json()) == 1

        r = await client.get(f"/attachments/{doc2['id']}")
        assert r.status_code == 200
        assert len(r.json()) == 1

        # Get attachment content
        r = await client.get(f"/attachment/{att_person['id']}")
        assert r.status_code == 200
        assert r.content == person_file_bytes

        r = await client.get(f"/attachment/{att_doc['id']}")
        assert r.status_code == 200
        assert r.content == doc_file_bytes

        # Delete attachment (and confirm file disappears)
        r = await client.delete(f"/attachment/{att_person['id']}")
        assert r.status_code == 200

        r = await client.get(f"/attachment/{att_person['id']}")
        assert r.status_code == 404

        # -------------------------
        # Negative deletions
        # -------------------------
        # Can't delete kind while nodes exist
        r = await client.delete(f"/kind/{kind_by_base['person']}")
        assert r.status_code == 400

        # Can't delete edge-kind while edges exist
        r = await client.delete(
            f"/edges-kind/{kind_by_base['person']}/{kind_by_base['document']}/authored"
        )
        assert r.status_code == 400

        # -------------------------
        # Delete everything one by one
        # -------------------------
        # Delete edges
        for e in [
            edge_authored,
            edge_self,
            edge_has_asset,
            edge_actor,
            edge_target,
        ]:
            r = await client.delete(
                f"/edge/{e['from_id']}/{e['to_id']}/{e['relation']}"
            )
            assert r.status_code == 200, r.text

        # After delete, between should be empty
        r = await client.get(f"/edges/{person['id']}/{doc2['id']}")
        assert r.status_code == 200
        assert r.json() == []

        # Now edges-kind deletions should succeed
        for ek in edges_kinds:
            r = await client.delete(
                f"/edges-kind/{ek['from_kind']}/{ek['to_kind']}/{ek['relation']}"
            )
            assert r.status_code == 200, r.text

        r = await client.get("/edges-kinds")
        assert r.status_code == 200
        assert r.json() == []

        # Verify /schema reflects deleted edges_kinds
        r = await client.get("/schema")
        assert r.status_code == 200, r.text
        j = r.json()
        assert isinstance(j.get("edges_kinds"), list)
        assert j.get("edges_kinds") == []

        # Create an attachment to verify node delete cleans it up
        extra_bytes = make_random_file(333)
        r = await client.post(
            "/attachment",
            data={"node_id": asset["id"]},
            files={
                "file": (
                    "asset.bin",
                    io.BytesIO(extra_bytes),
                    "application/octet-stream",
                )
            },
        )
        assert r.status_code == 200
        att_asset = r.json()

        # Verify download of uploaded attachment to ensure byte-to-byte equality
        r = await client.get(f"/attachment/{att_asset['id']}")
        assert r.status_code == 200
        assert r.content == extra_bytes

        # Delete nodes (should cascade delete attachments/edges and delete files)
        for n in [event, asset, doc2, person]:
            r = await client.delete(f"/node/{n['id']}")
            assert r.status_code == 200

        # Attachment should now be gone (row + file)
        r = await client.get(f"/attachment/{att_asset['id']}")
        assert r.status_code == 404

        # Search all nodes -> empty
        r = await client.post(
            "/nodes/search",
            json={
                "kinds": list(kind_by_base.values()),
                "query": {},
                "limit": 1000,
            },
        )
        assert r.status_code == 200
        assert r.json() == []

        # Now kind deletions should succeed
        for k in kinds:
            r = await client.delete(f"/kind/{k['name']}")
            assert r.status_code == 200

        r = await client.get("/kinds")
        assert r.status_code == 200
        # Shared cluster note: other kinds may exist.
        assert kind_by_base["person"] not in {x["name"] for x in r.json()}

        # -------------------------
        # Reset endpoint: create temp resources, reset and verify cleared
        # -------------------------
        temp_kind_name = f"temp_kind_{run_id}"
        r = await client.post(
            "/kind", json={"name": temp_kind_name, "schema": {"type": "object"}}
        )
        assert r.status_code == 200

        r = await client.post("/node", json={"kind": temp_kind_name, "payload": {}})
        assert r.status_code == 200
        temp_node = r.json()

        extra_bytes = make_random_file(16)
        r = await client.post(
            "/attachment",
            data={"node_id": temp_node["id"]},
            files={
                "file": ("tmp.bin", io.BytesIO(extra_bytes), "application/octet-stream")
            },
        )
        assert r.status_code == 200
        temp_att = r.json()

        # Call reset
        r = await client.post("/reset")
        assert r.status_code == 200, r.text
        assert r.json().get("ok") is True

        # Verify cleared
        r = await client.get("/kinds")
        assert r.status_code == 200
        assert temp_kind_name not in {x["name"] for x in r.json()}

        r = await client.get("/edges-kinds")
        assert r.status_code == 200
        assert r.json() == []

        r = await client.post(
            "/nodes/search",
            json={"kinds": [], "query": {}, "limit": 10},
        )
        assert r.status_code == 200
        assert r.json() == []

        r = await client.get(f"/attachment/{temp_att['id']}")
        assert r.status_code == 404
