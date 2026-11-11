import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from debug_rag.errors import RagError
from debug_rag.generation.local_vision import LocalVision
from debug_rag.ingestion.readers import export_document, review_document
from debug_rag.ingestion.service import prepare_documents
from debug_rag.main import create_app
from debug_rag.settings import Settings

MODEL = "qwen3-vl:2b-instruct"


def test_visual_answer_uses_local_images_and_authorized_page(environment, tmp_path):
    pdf = pytest.importorskip("pymupdf")
    settings, engine, _, _, embedder, vectors, builder = environment
    settings.local_vision_model = MODEL
    path = tmp_path / "source.pdf"
    with pdf.open() as doc:
        doc.new_page().insert_text((72, 72), "Orbit report with simulated PDF evidence.")
        doc.save(path)
    path.with_suffix(".meta.json").write_text(
        json.dumps(
            {
                "source_key": "orbit",
                "title": "Orbit",
                "app_snapshot": "simulated-p3",
                "data_kind": "simulated",
                "feature_status": "delivered",
                "updated_at": "2026-11-10",
                "external_processing_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    artifact = Path(export_document(path, tmp_path / "parsed")["document"])
    review_document(artifact, accept_incomplete=True)
    prepare_documents(engine, "vision", artifact.parent)
    generation = builder.build("vision")["generation_id"]
    image_payloads = []
    repair_attempts = []
    forged = False

    def ollama(request):
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": MODEL, "digest": "a" * 64, "size": 1}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "vision"]})
        body = json.loads(request.content)
        assert request.url.path == "/api/chat" and body["model"] == MODEL
        user_message = body["messages"][-1]
        evidence = json.loads(user_message["content"])
        repair_attempts.append(evidence["repair_invalid_previous_output"])
        if "images" in user_message:
            image_payloads.append(base64.b64decode(user_message["images"][0]))
            citation = evidence["visual_evidence"][0]["id"]
        else:
            citation = evidence["evidence"][0]["id"]
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "done": True,
                "message": {
                    "content": json.dumps(
                        {
                            "status": "answered",
                            "statements": [
                                {
                                    "text": "Orbit report.",
                                    "citations": ["E999" if forged else citation],
                                }
                            ],
                        }
                    )
                },
            },
        )

    app = create_app(settings)
    question = {"kb_id": "vision", "question": "Orbit report"}
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 40000)) as client:
        app.state.rag.embedder, app.state.rag.vectors = embedder, vectors
        app.state.vision = LocalVision(settings, httpx.MockTransport(ollama))
        result = client.post("/api/v1/vision/chat", json=question)
        assert result.status_code == 200
        result = result.json()
        assert result["generation_id"] == generation
        assert result["trace"]["external_calls_executed"] == 0
        assert result["trace"]["local_vision_calls_executed"] == 1
        image = result["citations"][0]
        assert image["visual_page"] == 1
        source = f"/api/v1/sources/{generation}/{image['chunk_id']}/pages/"
        png = client.get(source + "1", params={"kb_id": "vision"})
        assert png.status_code == 200 and png.headers["content-type"] == "image/png"
        assert png.content == image_payloads[0]
        assert hashlib.sha256(png.content).hexdigest() == image["image_sha256"]
        assert client.get(source + "2", params={"kb_id": "vision"}).status_code == 404
        assert client.get(source + "1", params={"kb_id": "other"}).status_code == 404
        assert (
            client.get(
                source + "1", params={"kb_id": "vision"}, headers={"Origin": "https://example.test"}
            ).status_code
            == 403
        )
        text = client.post("/api/v1/vision/chat", json={**question, "include_images": False}).json()
        assert not text["image_evidence"] and len(image_payloads) == 1
        assert text["status"] == "answered" and "visual_page" not in text["citations"][0]
        forged = True
        rejected = client.post("/api/v1/vision/chat", json=question).json()
        assert rejected["status"] == "partial" and rejected["generation_validation"] == "failed"
        assert rejected["trace"]["local_vision_calls_executed"] == 2
        assert repair_attempts == [False, False, False, True]
        assert "E999" not in rejected["answer"]


def test_local_model_must_be_installed_before_prompt_is_sent():
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"models": []})

    provider = LocalVision(Settings(local_vision_model=MODEL), httpx.MockTransport(respond))
    with pytest.raises(RagError, match="未在本机安装"):
        provider.complete([{"role": "user", "content": "should never be sent"}])
    assert calls == ["/api/tags"]


def test_structured_top5_can_supply_a_page_omitted_by_text_budget(monkeypatch):
    from debug_rag.generation import visual_evidence

    def row(revision, page, **locator):
        return {
            "revision_id": revision,
            "chunk_id": revision,
            "metadata": {},
            "original_sha256": revision,
            "source_locations": [{"format": "pdf", "page": page, **locator}],
        }

    monkeypatch.setattr(
        visual_evidence, "render_page", lambda *_: visual_evidence.PageImage(b"image", 1, 1)
    )
    ordinary = row("first", 1)
    table = row("table", 6, table=1)
    selected = visual_evidence.select_images(None, [ordinary], [ordinary, table])
    assert [(item["visual_page"], item["selection_origin"]) for item, _ in selected] == [
        (6, "fusion_top5"),
        (1, "text_context"),
    ]
    assert selected[0][0]["fusion_rank"] == 2
    assert not visual_evidence.select_images(None, [], [table])
