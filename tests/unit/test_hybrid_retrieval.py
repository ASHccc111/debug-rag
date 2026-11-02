"""Four actual dense/sparse routes, one RRF, source mapping and billing opt-in."""

import pytest
from p2_support import FakeEmbedder, FakeVectors

from debug_rag.errors import RagError
from debug_rag.retrieval.indexing import IndexBuilder
from debug_rag.retrieval.service import RagService


class HybridEmbedder(FakeEmbedder):
    identity = {"provider": "viking", "model": "test-only", "dimension": 3, "revision": "1"}

    def __init__(self):
        self.queries = []
        self.last_calls = []

    def encode_hybrid(self, texts, query=False):
        if query:
            self.queries.extend(texts)
        return [
            {
                "dense": vector,
                "sparse": {
                    term: float(text.count(term)) + 0.01 for term in ("相机", "文件", "悬浮")
                },
            }
            for text, vector in zip(texts, self.encode(texts, query=query))
        ]


class HybridVectors(FakeVectors):
    def build_hybrid(self, name, rows, dimension):
        self.build(name, rows, dimension)

    def validate_hybrid(self, name, rows, dimension):
        self.validate(name, rows, dimension)

    def search_sparse(self, name, vector, generation_id, kb_id, limit=5, delivered_only=True):
        rows = [
            r
            for r in self.collections[name]
            if not delivered_only or r["feature_status"] == "delivered"
        ]

        def score(row):
            return sum(value * vector.get(key, 0) for key, value in row["sparse"].items())

        return [
            {
                "representation_id": r["id"],
                "chunk_id": r["chunk_id"],
                "revision_id": r["revision_id"],
                "kb_id": r["kb_id"],
                "generation_id": r["generation_id"],
                "score": score(r),
            }
            for r in sorted(rows, key=score, reverse=True)[:limit]
        ]


@pytest.fixture
def hybrid_service(environment):
    settings, engine, _, _, _, _, _ = environment
    settings.allow_external_calls = True
    settings.query_rewrite_enabled = True
    settings.embedding_backend = "viking"
    settings.dense_top_k = 2
    settings.sparse_top_k = 1
    embedder, vectors = HybridEmbedder(), HybridVectors()
    IndexBuilder(settings, engine, embedder, vectors).build("demo")

    class Rewriter:
        def rewrite(self, question):
            return {
                "query": "文件导出取消后如何清理？",
                "call_id": "test-rewrite",
                "served_model": "test-only",
                "usage": None,
            }

    return RagService(settings, engine, embedder, vectors, None, rewriter=Rewriter())


def test_hybrid_search_requires_explicit_paid_opt_in_before_encoding(hybrid_service):
    with pytest.raises(RagError) as caught:
        hybrid_service.search("demo", "文件取消")
    assert caught.value.code == "remote_embedding_opt_in_required"
    assert hybrid_service.embedder.queries == []


def test_each_query_dense_sparse_routes_then_single_global_rrf(hybrid_service):
    result = hybrid_service.search("demo", "文件取消", enhanced=True, allow_paid=True)
    trace = result["trace"]
    assert trace["profile"] == "hybrid_enhanced"
    assert trace["fusion"] == "single_global_rrf"
    assert trace["queries"] == ["文件取消", "文件导出取消后如何清理？"]
    assert trace["bm25_top_k"] is None and "bm25" not in trace
    for route in ("dense", "dense_rewrite", "sparse", "sparse_rewrite"):
        ids = [row["chunk_id"] for row in trace[route]]
        assert len(ids) == len(set(ids))
        assert len(ids) <= (2 if route.startswith("dense") else 1)
    for candidate in result["candidates"]:
        expected = sum(1 / (trace["rrf_k"] + r["rank"]) for r in candidate["routes"].values())
        assert candidate["rrf_score"] == pytest.approx(expected)


def test_hybrid_without_rewrite_still_runs_two_model_routes(hybrid_service):
    result = hybrid_service.search("demo", "文件取消", allow_paid=True)
    assert result["trace"]["queries"] == ["文件取消"]
    assert "sparse" in result["trace"] and "dense_rewrite" not in result["trace"]


def test_configurable_topk_remains_within_reranker_candidate_budget():
    from pydantic import ValidationError

    from debug_rag.settings import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None, sparse_top_k=6)
