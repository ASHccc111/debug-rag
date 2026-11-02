import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from debug_rag import budget
from debug_rag.budget import SHANGHAI, BudgetLedger
from debug_rag.errors import RagError
from debug_rag.generation.provider import DeepSeekGenerator
from debug_rag.main import create_app
from debug_rag.retrieval.lexical import fuse
from debug_rag.retrieval.rerank import BailianReranker
from debug_rag.retrieval.rewrite import QueryRewriter
from debug_rag.retrieval.service import RagService
from debug_rag.storage.sqlite import ApiCall

ENDPOINT = "https://unit-workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"


@pytest.fixture
def enhanced(environment, monkeypatch):
    settings, engine, _, _, embedder, vectors, builder = environment
    monkeypatch.setitem(budget.PRICING, "verified_on", "2026-11-01")
    monkeypatch.setitem(budget.PRICING, "valid_through", "2026-11-02")
    monkeypatch.setattr(budget, "now_shanghai", lambda: datetime(2026, 11, 1, 12, tzinfo=SHANGHAI))
    settings.allow_external_calls = True
    settings.query_rewrite_enabled = settings.rerank_enabled = True
    settings = type(settings)(
        **{
            **settings.model_dump(),
            "deepseek_api_key": "mock-key-deepseek",
            "rerank_api_key": "mock-key-bailian",
            "rerank_endpoint": ENDPOINT,
            "rerank_input_cny_per_million": "1.5",  # Fictional test rate, not a vendor quote.
            "rerank_price_verified_on": "2026-11-01",
            "rerank_price_valid_through": "2026-11-02",
        },
        _env_file=None,
    )
    ledger = BudgetLedger(engine, Decimal("50"))
    published = builder.build("demo")
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        if request.url.host == "api.deepseek.com":
            if body["max_tokens"] == 300:
                content = json.dumps(
                    {"query": "文件导出取消后如何清理临时文件？"}, ensure_ascii=False
                )
            else:
                assert body["max_tokens"] == 1500
                evidence = json.loads(body["messages"][1]["content"])["evidence"]
                assert evidence and evidence[0]["id"] == "E1"
                content = json.dumps(
                    {
                        "status": "answered",
                        "statements": [
                            {"text": "模拟规范要求取消后清理临时文件。", "citations": ["E1"]}
                        ],
                    },
                    ensure_ascii=False,
                )
            return httpx.Response(
                200,
                json={
                    "model": "deepseek-test",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 30},
                    "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                },
            )
        assert str(request.url) == ENDPOINT
        assert body["model"] == "qwen3-rerank"
        assert body["input"]["query"] == "导出取消后咋处理？"
        docs = body["input"]["documents"]
        assert body["parameters"]["top_n"] == len(docs)
        assert body["parameters"]["return_documents"] is False
        assert any("清理临时文件" in d for d in docs)
        # Force the last RRF candidate to the top, so actual reorder is observable.
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": i, "relevance_score": (i + 1) / len(docs)}
                        for i in reversed(range(len(docs)))
                    ]
                },
                "usage": {"total_tokens": 100},
                "request_id": "mock-request",
            },
        )

    transport = httpx.MockTransport(handler)
    generator = DeepSeekGenerator(settings, ledger, transport)
    service = RagService(
        settings,
        engine,
        embedder,
        vectors,
        generator,
        rewriter=QueryRewriter(generator),
        reranker=BailianReranker(settings, ledger, transport),
    )
    return service, ledger, requests, published


def test_four_routes_single_rrf_rerank_mapping_and_shared_ledger(enhanced):
    service, ledger, requests, published = enhanced
    result = service.search("demo", "导出取消后咋处理？", enhanced=True)
    trace = result["trace"]
    names = ("dense", "bm25", "dense_rewrite", "bm25_rewrite")
    before = fuse({name: trace[name] for name in names})
    assert all(len(trace[name]) <= 5 for name in names)
    assert len(result["candidates"]) == len(before) <= 20
    assert result["candidates"][0]["chunk_id"] == before[-1]["chunk_id"]
    original_scores = {row["chunk_id"]: row["rrf_score"] for row in before}
    assert all(row["rrf_score"] == original_scores[row["chunk_id"]] for row in result["candidates"])
    assert result["generation_id"] == published["generation_id"]
    assert trace["rerank_applied"] and trace["query_rewrite_applied"]
    assert not trace["degraded"]
    assert trace["external_calls_executed"] == len(requests) == len(result["api_calls"]) == 2
    with Session(service.engine) as session:
        rows = list(session.scalars(select(ApiCall).order_by(ApiCall.purpose)))
        assert {r.provider for r in rows} == {"deepseek", "bailian"}
        assert {r.purpose for r in rows} == {"query_rewrite", "rerank"}
        assert all(r.status == "settled_upper_bound" for r in rows)
        # Rerank uses its stored rate, not the DeepSeek generation rate.
        assert next(r for r in rows if r.purpose == "rerank").charged_units == 150
    assert Decimal(ledger.summary()["accounted_upper_bound_cny"]) == Decimal("0.00059")


def test_local_search_and_context_never_call_remote_even_with_keys_and_flags(enhanced):
    service, ledger, requests, _ = enhanced
    result = service.search("demo", "文件导出")
    preview = service.prepare_context("demo", "文件导出")
    assert result["trace"]["external_calls_executed"] == 0
    assert preview["trace"]["external_calls_executed"] == 0
    assert not requests and ledger.summary()["recorded_calls"] == 0


def test_enhanced_context_keeps_calls_and_expands_only_after_rerank(enhanced):
    service, _, requests, _ = enhanced
    result = service.prepare_context("demo", "导出取消后咋处理？", enhanced=True)
    assert result["trace"]["rerank_applied"]
    assert result["trace"]["parent_expansion_applied"]
    assert (
        result["context"][0]["retrieved_child_chunk_ids"][0]
        == result["trace"]["rerank"]["ranking"][0]["chunk_id"]
    )
    assert len(result["api_calls"]) == len(requests) == 2


def test_enhanced_answer_keeps_three_stages_and_server_owned_citations(enhanced):
    service, ledger, requests, _ = enhanced
    result = service.answer("demo", "导出取消后咋处理？", enhanced=True)
    assert result["status"] == "answered"
    assert result["trace"]["external_calls_executed"] == len(requests) == 3
    assert len(result["api_calls"]) == ledger.summary()["recorded_calls"] == 3
    assert result["citations"][0]["evidence_id"] == "E1"
    assert result["citations"][0]["revision_id"]
    with Session(service.engine) as session:
        assert set(session.scalars(select(ApiCall.purpose))) == {
            "query_rewrite",
            "rerank",
            "answer",
        }


def test_rewrite_fallback_continues_rerank_and_retains_failed_call(enhanced):
    service, ledger, requests, _ = enhanced

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("provider-secret", request=request)

    service.rewriter.generator = DeepSeekGenerator(
        service.settings, ledger, httpx.MockTransport(timeout)
    )
    result = service.search("demo", "导出取消后咋处理？", enhanced=True)
    trace = result["trace"]
    assert trace["queries"] == ["导出取消后咋处理？"]
    assert trace["query_rewrite"]["reason"] == "generation_provider_unavailable"
    assert trace["degraded"] and trace["rerank_applied"]
    assert trace["external_calls_executed"] == len(requests) == 2
    assert Decimal(ledger.summary()["unresolved_reserved_cny"]) > 0
    assert "provider-secret" not in json.dumps(result)


def test_rerank_timeout_falls_back_to_exact_rrf_order(enhanced):
    service, ledger, requests, _ = enhanced

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("provider-secret", request=request)

    service.reranker = BailianReranker(service.settings, ledger, httpx.MockTransport(timeout))
    result = service.search("demo", "导出取消后咋处理？", enhanced=True)
    trace = result["trace"]
    before = fuse(
        {name: trace[name] for name in ("dense", "bm25", "dense_rewrite", "bm25_rewrite")}
    )
    assert [c["chunk_id"] for c in result["candidates"]] == [r["chunk_id"] for r in before]
    assert trace["degraded"] and not trace["rerank_applied"]
    assert trace["rerank_enabled"]
    assert trace["external_calls_executed"] == len(requests) == 2
    assert Decimal(ledger.summary()["unresolved_reserved_cny"]) > 0


@pytest.mark.parametrize("feature", ["external", "keys", "price", "budget"])
def test_unavailable_configuration_or_budget_does_not_send_requests(enhanced, feature):
    from pydantic import SecretStr

    service, ledger, requests, _ = enhanced
    if feature == "external":
        service.settings.allow_external_calls = False
    elif feature == "keys":
        service.settings.deepseek_api_key = service.settings.rerank_api_key = SecretStr("")
    elif feature == "price":
        service.settings.query_rewrite_enabled = False
        service.settings.rerank_input_cny_per_million = None
    else:
        ledger.limit = 1
    result = service.search("demo", "导出取消后咋处理？", enhanced=True)
    assert not requests
    assert result["candidates"] and result["trace"]["degraded"]
    assert result["trace"]["external_calls_executed"] == ledger.summary()["recorded_calls"] == 0


def test_restricted_kb_skips_rewrite_and_rerank_before_network(enhanced, monkeypatch):
    from debug_rag.retrieval import service as module

    service, ledger, requests, _ = enhanced
    original = module.published_snapshot

    def restricted(*args):
        generation, manifest, chunks = original(*args)
        for c in chunks:
            c["metadata"]["external_processing_allowed"] = False
        return generation, manifest, chunks

    monkeypatch.setattr(module, "published_snapshot", restricted)
    result = service.search("demo", "文件导出", enhanced=True)
    assert result["trace"]["query_rewrite"]["reason"] == "kb_external_processing_restricted"
    assert result["trace"]["rerank"]["reason"] == "external_processing_not_allowed"
    assert not requests and ledger.summary()["recorded_calls"] == 0


@pytest.mark.parametrize(
    "content",
    [
        '{"query":""}',
        '{"query":"x","query":"y"}',
        '{"query":42}',
        '{"query":"状态","answer":"伪答案"}',
        '{"query":"状态"}',
        json.dumps({"query": "长" * 301}),
    ],
)
def test_rewrite_rejects_invalid_output_and_lost_identifier(content):
    rewriter = QueryRewriter(
        SimpleNamespace(
            complete=lambda *a, **k: {
                "content": content,
                "call_id": "mock",
                "served_model": "mock",
                "usage": {},
            }
        )
    )
    with pytest.raises(RagError) as caught:
        rewriter.rewrite("camera_state v2 取消如何处理？")
    assert caught.value.code == "invalid_query_rewrite"
    assert caught.value.api_call["status"] == "invalid_output"


def test_unchanged_rewrite_does_not_double_rrf_votes(enhanced):
    service, _, requests, _ = enhanced
    service.settings.rerank_enabled = False
    service.rewriter = QueryRewriter(
        SimpleNamespace(
            complete=lambda *a, **k: {
                "content": '{"query":"文件导出"}',
                "call_id": "mock",
                "usage": {},
                "served_model": "mock",
            }
        )
    )
    result = service.search("demo", "文件导出", enhanced=True)
    assert result["trace"]["query_rewrite"]["status"] == "unchanged"
    assert not result["trace"]["query_rewrite_applied"]
    assert "dense_rewrite" not in result["trace"] and not requests


@pytest.mark.parametrize(
    "kind",
    ["duplicate", "foreign", "boolean", "nan", "missing", "usage_missing", "overrun", "http_error"],
)
def test_reranker_rejects_invalid_mapping_and_never_retries(enhanced, kind):
    service, ledger, _, _ = enhanced
    candidates = service.search("demo", "文件导出")["candidates"]
    assert len(candidates) >= 2
    sent = []

    def handler(request):
        sent.append(request)
        if kind == "http_error":
            return httpx.Response(401, text="provider-secret")
        rows = [{"index": i, "relevance_score": 0.5} for i in range(len(candidates))]
        if kind == "duplicate":
            rows[1]["index"] = 0
        if kind == "foreign":
            rows[0]["index"] = 999
        if kind == "boolean":
            rows[0]["index"] = True
        if kind == "nan":
            rows[0]["relevance_score"] = "NaN"
        if kind == "missing":
            rows.pop()
        payload = {"output": {"results": rows}, "usage": {"total_tokens": 100}}
        if kind == "usage_missing":
            payload.pop("usage")
        if kind == "overrun":
            payload["usage"]["total_tokens"] = 10**6
        return httpx.Response(200, json=payload)

    reranker = BailianReranker(service.settings, ledger, httpx.MockTransport(handler))
    if kind == "usage_missing":
        reranker.rerank("文件导出", candidates)
        assert Decimal(ledger.summary()["unresolved_reserved_cny"]) > 0
    else:
        with pytest.raises(RagError) as caught:
            reranker.rerank("文件导出", candidates)
        assert "provider-secret" not in str(caught.value)
    assert len(sent) == 1
    assert Decimal(ledger.summary()["accounted_upper_bound_cny"]) > 0


def test_snapshot_stays_consistent_if_index_is_published_during_rewrite(enhanced, environment):
    service, _, _, published = enhanced
    builder = environment[-1]
    rewrite = service.rewriter.rewrite
    new_generation = []

    def republish(question):
        new_generation.append(builder.build("demo")["generation_id"])
        return rewrite(question)

    service.rewriter = SimpleNamespace(rewrite=republish)
    result = service.prepare_context("demo", "导出取消后咋处理？", enhanced=True)
    assert new_generation[0] != published["generation_id"]
    assert result["generation_id"] == published["generation_id"]
    assert result["context"] and result["trace"]["parent_expansion_applied"]


def test_api_exposes_advanced_mode_without_changing_local_endpoint(enhanced):
    service, _, requests, _ = enhanced
    app = create_app(service.settings)
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        app.state.rag = service
        local = client.post("/api/v1/search", json={"kb_id": "demo", "question": "文件导出"})
        assert local.status_code == 200 and not requests
        advanced = client.post(
            "/api/v1/search/advanced", json={"kb_id": "demo", "question": "导出取消后咋处理？"}
        )
        assert advanced.status_code == 200 and advanced.json()["trace"]["rerank_applied"]
        assert len(requests) == 2
        rejected = client.post(
            "/api/v1/search", json={"kb_id": "demo", "question": "文件导出", "enhanced": True}
        )
        assert rejected.status_code == 422
