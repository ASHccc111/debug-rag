import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from debug_rag.errors import RagError
from debug_rag.generation.grounding import context, messages
from debug_rag.generation.provider import input_upper_bound
from debug_rag.ingestion.chunking import ChunkConfig
from debug_rag.ingestion.service import prepare_documents
from debug_rag.main import create_app
from debug_rag.retrieval.indexing import snapshot
from debug_rag.retrieval.service import RagService


@pytest.fixture
def expanded(environment):
    settings, engine, source, _, embedder, vectors, builder = environment
    prepare_documents(engine, "demo", source, ChunkConfig(child_chars=100))
    published = builder.build("demo")
    _, rows = snapshot(engine, "demo", published["generation_id"], include_parents=True)
    parents = {r["chunk_id"]: r for r in rows if r["kind"] == "parent"}
    parent = next(p for p in parents.values() if p["source_key"] == "test-doc")
    children = [r for r in rows if r["parent_chunk_id"] == parent["chunk_id"]]
    assert len(children) > 1
    return settings, engine, embedder, vectors, published, parents, parent, children


def test_siblings_expand_once_and_keep_exact_parent_citation(expanded):
    _, _, _, _, _, parents, parent, children = expanded
    selected = context("相机退出如何清理", children[:2], 6000, parents)
    assert len(selected) == 1
    row = selected[0]
    assert row["chunk_id"] == parent["chunk_id"]
    assert row["text"] == parent["text"]
    assert row["start_char"] == parent["start_char"]
    assert row["end_char"] == parent["end_char"]
    assert row["context_expansion"] == "parent"
    assert row["retrieved_child_chunk_ids"] == [c["chunk_id"] for c in children[:2]]
    payload = json.loads(messages("相机退出如何清理", selected)[1]["content"])
    assert payload["evidence"][0]["text"] == parent["text"]


def test_parent_that_does_not_fit_falls_back_to_full_child(expanded):
    _, _, _, _, _, parents, _, children = expanded
    child = children[0]
    limit = input_upper_bound(messages("相机", [{**child, "evidence_id": "E1"}]))
    selected = context("相机", [child], limit, parents)
    assert selected[0]["chunk_id"] == child["chunk_id"]
    assert selected[0]["text"] == child["text"]
    assert selected[0]["context_expansion"] == "child_fallback"
    assert input_upper_bound(messages("相机", selected)) <= limit
    with pytest.raises(RagError) as caught:
        context("相机", [child], 10, parents)
    assert caught.value.code == "context_budget_exceeded"


@pytest.mark.parametrize("damage", ["missing", "revision", "range", "metadata", "text"])
def test_parent_cannot_cross_revision_or_corrupt_source_mapping(expanded, damage):
    _, _, _, _, _, parents, parent, children = expanded
    damaged = copy.deepcopy(parents)
    target = damaged[parent["chunk_id"]]
    if damage == "missing":
        damaged.clear()
    elif damage == "revision":
        target["revision_id"] = "foreign-revision"
    elif damage == "range":
        target["start_char"] = children[0]["start_char"] + 1
    elif damage == "metadata":
        target["metadata"]["app_snapshot"] = "another-snapshot"
    else:
        target["text"] = "x" * len(target["text"])
    with pytest.raises(RagError) as caught:
        context("相机", children[:1], 6000, damaged)
    assert caught.value.code == "parent_mapping_invalid"


def test_expansion_keeps_external_permission_and_can_be_disabled(expanded):
    _, _, _, _, _, parents, parent, children = expanded
    selected = context("相机", children[:1], 6000)
    assert selected[0]["chunk_id"] == children[0]["chunk_id"]
    assert selected[0]["context_expansion"] == "none"
    blocked_children = copy.deepcopy(children[:1])
    blocked_parents = copy.deepcopy(parents)
    blocked_children[0]["metadata"]["external_processing_allowed"] = False
    blocked_parents[parent["chunk_id"]]["metadata"]["external_processing_allowed"] = False
    with pytest.raises(RagError) as caught:
        context("相机", blocked_children, 6000, blocked_parents)
    assert caught.value.code == "external_processing_not_allowed"


def test_answer_and_api_return_actual_parent_ranges_and_trace(expanded):
    settings, engine, embedder, vectors, published, _, _, _ = expanded

    def complete(*args, **kwargs):
        return {
            "content": json.dumps(
                {
                    "status": "answered",
                    "statements": [{"text": "按模拟资料退出页面时解除订阅。", "citations": ["E1"]}],
                },
                ensure_ascii=False,
            ),
            "call_id": "mock",
            "served_model": "mock",
            "usage": {},
        }

    service = RagService(settings, engine, embedder, vectors, SimpleNamespace(complete=complete))
    result = service.answer("demo", "相机状态退出页面时如何解除订阅？")
    assert result["trace"]["parent_expansion_applied"] is True
    assert result["trace"]["selected_parent_count"] >= 1
    citation = result["citations"][0]
    assert citation["kind"] == "parent"
    assert citation["retrieved_child_chunk_ids"]
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as client:
        path = f"/api/v1/sources/{published['generation_id']}/{citation['chunk_id']}"
        response = client.get(path + "?kb_id=demo")
        assert response.status_code == 200
        original = response.json()
        for field in ("text", "start_char", "end_char", "start_line", "end_line", "revision_id"):
            assert original[field] == citation[field]
        assert client.get(path + "?kb_id=other").status_code == 404
    settings.parent_expansion_enabled = False
    no_expand = service.answer("demo", "相机状态退出页面时如何解除订阅？")
    assert no_expand["trace"]["parent_expansion_enabled"] is False
    assert no_expand["trace"]["parent_expansion_applied"] is False
    assert all(row["kind"] == "child" for row in no_expand["context"])


def test_local_context_preview_never_calls_generator(expanded):
    settings, engine, embedder, vectors, _, _, _, _ = expanded

    def unexpected(*args, **kwargs):
        raise AssertionError("Local preview must not call a generation provider")

    with TestClient(
        create_app(settings), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)
    ) as client:
        client.app.state.rag = RagService(
            settings,
            client.app.state.engine,
            embedder,
            vectors,
            SimpleNamespace(complete=unexpected),
        )
        response = client.post(
            "/api/v1/context",
            json={"kb_id": "demo", "question": "相机状态退出页面时如何解除订阅？"},
        )
        assert response.status_code == 200
        result = response.json()
        assert result["mode"] == "context_preview"
        assert result["trace"]["parent_expansion_applied"] is True
        assert result["trace"]["external_calls_executed"] == 0
        assert result["api_calls"] == []
        assert client.get("/api/v1/status?kb_id=demo").json()["budget"]["recorded_calls"] == 0


def test_private_material_can_be_previewed_but_never_sent_to_generator(environment):
    settings, engine, source, _, embedder, vectors, builder = environment
    for path in source.glob("*.md"):
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "external_processing_allowed: true", "external_processing_allowed: false"
            ),
            encoding="utf-8",
        )
    prepare_documents(engine, "demo", source, ChunkConfig(child_chars=100))
    builder.build("demo")

    def unexpected(*args, **kwargs):
        raise AssertionError("Private material must never reach a provider")

    service = RagService(settings, engine, embedder, vectors, SimpleNamespace(complete=unexpected))
    preview = service.prepare_context("demo", "相机退出页面如何清理？")
    assert preview["context"]
    assert all(not row["metadata"]["external_processing_allowed"] for row in preview["context"])
    with pytest.raises(RagError) as caught:
        service.answer("demo", "相机退出页面如何清理？")
    assert caught.value.code == "external_processing_not_allowed"
