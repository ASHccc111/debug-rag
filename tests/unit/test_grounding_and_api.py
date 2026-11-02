import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from debug_rag.errors import RagError
from debug_rag.generation.grounding import context, validate_answer
from debug_rag.main import create_app
from debug_rag.retrieval.embedding import LocalEmbedder
from debug_rag.retrieval.service import RagService


def example():
    return {
        "chunk_id": "example-child",
        "kind": "child",
        "metadata": {
            "title": "模拟相机",
            "app_snapshot": "demo-v1",
            "data_kind": "simulated",
            "feature_status": "delivered",
            "external_processing_allowed": True,
        },
        "section_path": ["接入"],
        "text": "退出页面时解除订阅。",
        "evidence_id": "E1",
    }


@pytest.mark.parametrize(
    "content",
    [
        '{"status":"answered","statements":[{"text":"假步骤","citations":["E99"]}]}',
        '{"status":"answered","statements":[{"text":"未引用步骤","citations":[]}]}',
        '{"status":"answered","statements":[],"message":"绕过引用的事实"}',
        '{"status":"answered","statements":[{"text":"见 E99","citations":["E1"]}]}',
        '{"status":"answered","status":"out_of_scope","statements":[],"message":"x"}',
    ],
)
def test_invalid_or_invented_citations_are_rejected(content):
    with pytest.raises(RagError):
        validate_answer(content, [example()])


def test_context_checks_permission_of_actual_sent_evidence():
    candidate = example()
    candidate["metadata"]["external_processing_allowed"] = False
    with pytest.raises(RagError) as caught:
        context("相机", [candidate], 6000)
    assert caught.value.code == "external_processing_not_allowed"


def test_embedding_windows_preserve_long_source_without_silent_truncation(monkeypatch):
    class Tokenizer:
        def __call__(self, text, add_special_tokens=True, **kwargs):
            return {
                "input_ids": list(range(len(text) + (2 if add_special_tokens else 0))),
                "offset_mapping": [(i, i + 1) for i in range(len(text))],
            }

        def num_special_tokens_to_add(self, pair):
            return 2

    model = LocalEmbedder(None)
    monkeypatch.setattr(model, "_load", lambda: None)
    model.tokenizer, model.max_tokens = Tokenizer(), 512
    text = "状态" * 700
    spans = model.windows(text)
    assert len(spans) == 3
    assert "".join(text[a:b] for a, b in spans) == text
    assert all(len(model.tokenizer(text[a:b])["input_ids"]) <= 512 for a, b in spans)


def test_bad_generation_has_one_repair_then_only_sources_are_shown(environment):
    settings, engine, _, _, embedder, vectors, builder = environment
    builder.build("demo")
    calls = []

    def complete(messages, purpose):
        calls.append(purpose)
        return {
            "content": (
                '{"status":"answered","statements":['
                '{"text":"不可展示的错误回答","citations":["E99"]}]}'
            ),
            "call_id": str(len(calls)),
            "served_model": "fake",
            "usage": {},
        }

    service = RagService(settings, engine, embedder, vectors, SimpleNamespace(complete=complete))
    result = service.answer("demo", "相机退出如何清理？")
    assert calls == ["answer", "citation_repair"]
    assert result["generation_validation"] == "failed"
    assert "不可展示的错误回答" not in json.dumps(result, ensure_ascii=False)
    assert result["context"] and not result["citations"]


def test_valid_answer_uses_server_source_ranges(environment):
    settings, engine, _, _, embedder, vectors, builder = environment
    builder.build("demo")
    content = {
        "status": "answered",
        "statements": [{"text": "按模拟规范退出页面时解除订阅。", "citations": ["E1"]}],
    }
    generator = SimpleNamespace(
        complete=lambda *a, **k: {
            "content": json.dumps(content, ensure_ascii=False),
            "call_id": "fake",
            "served_model": "fake",
            "usage": {},
        }
    )
    result = RagService(settings, engine, embedder, vectors, generator).answer("demo", "相机退出")
    assert result["status"] == "answered"
    assert result["citations"][0]["evidence_id"] == "E1"
    assert result["citations"][0]["revision_id"]
    assert result["citations"][0]["start_line"] > 1


def test_api_search_source_isolation_and_disabled_generator(environment):
    settings, engine, _, _, embedder, vectors, builder = environment
    published = builder.build("demo")
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        app.state.rag.embedder, app.state.rag.vectors = embedder, vectors
        page = client.get("/")
        assert page.status_code == 200 and "仅检索原文" in page.text
        state = client.get("/api/v1/status?kb_id=demo").json()
        assert state["index_published"] is True
        assert state["generation_configured"] is False
        result = client.post(
            "/api/v1/search", json={"kb_id": "demo", "question": "文件导出如何取消？"}
        )
        assert result.status_code == 200
        row = result.json()["candidates"][0]
        path = f"/api/v1/sources/{published['generation_id']}/{row['chunk_id']}"
        assert client.get(path + "?kb_id=demo").json()["text"] == row["text"]
        assert client.get(path + "?kb_id=other").status_code == 404
        answer = client.post(
            "/api/v1/chat", json={"kb_id": "demo", "question": "文件导出如何取消？"}
        )
        assert answer.status_code == 503
        assert answer.json()["error"]["code"] == "external_calls_disabled"
        extra = client.post(
            "/api/v1/search", json={"kb_id": "demo", "question": "相机", "generation_id": "foreign"}
        )
        assert extra.status_code == 422
