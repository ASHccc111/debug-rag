"""Hybrid publication uses simulated vectors; never calls an embedding endpoint."""

import copy
import hashlib
import json
from contextlib import contextmanager

import pytest
from p2_support import FakeEmbedder, FakeVectors
from sqlalchemy import select
from sqlalchemy.orm import Session

from debug_rag.errors import RagError
from debug_rag.ingestion.service import prepare_documents
from debug_rag.retrieval.indexing import (
    IndexBuilder,
    activate_generation,
    artifact_path,
    load_artifact,
    snapshot,
)
from debug_rag.storage.milvus import MilvusVectors
from debug_rag.storage.sqlite import IndexGeneration, active_generation


class HybridEmbedder(FakeEmbedder):
    identity = {"provider": "viking", "model": "fake-hybrid-test", "dimension": 3, "revision": "1"}

    def __init__(self):
        self.calls = 0
        self.last_calls = []
        self.bad_sparse = False

    def encode_hybrid(self, texts, query=False):
        self.calls += 1
        self.last_calls = [{"call_id": "mock-only", "status": "unknown"}]
        dense = self.encode(texts, query=query)
        return [
            {
                "dense": vector,
                "sparse": {
                    "词项": 0.5,
                    "103": 0.25,
                    "word": float("nan") if self.bad_sparse else 1.0,
                },
            }
            for vector in dense
        ]


class HybridVectors(FakeVectors):
    fail_sparse = False
    corrupt_sparse = False

    def build_hybrid(self, name, rows, dimension):
        self.collections[name] = copy.deepcopy(rows)

    def validate_hybrid(self, name, rows, dimension):
        if self.corrupt_sparse:
            raise RagError("index_vector_payload_mismatch", "injected corruption", 409)
        self.validate(name, rows, dimension)

    def validate_existing(self, name, rows, dimension, hybrid=False):
        assert {
            row["id"]: {key: row[key] for key in rows[0]} for row in self.collections[name]
        } == {row["id"]: row for row in rows}

    def search_sparse(self, name, vector, generation_id, kb_id, limit=5, delivered_only=True):
        if self.fail_sparse:
            return []
        rows = [
            row
            for row in self.collections[name]
            if not delivered_only or row["feature_status"] == "delivered"
        ]
        rows.sort(
            key=lambda row: -sum(value * row["sparse"].get(key, 0) for key, value in vector.items())
        )
        return [
            {
                "representation_id": row["id"],
                "chunk_id": row["chunk_id"],
                "revision_id": row["revision_id"],
                "kb_id": row["kb_id"],
                "generation_id": row["generation_id"],
                "score": sum(value * row["sparse"].get(key, 0) for key, value in vector.items()),
            }
            for row in rows[:limit]
        ]


def hybrid_builder(environment):
    settings, engine, *_ = environment
    embedder, vectors = HybridEmbedder(), HybridVectors()
    return IndexBuilder(settings, engine, embedder, vectors), embedder, vectors


def test_hybrid_publish_has_independent_collection_and_collision_free_vocabulary(environment):
    settings, engine, _, _, _, _, baseline = environment
    local = baseline.build("demo")
    builder, embedder, vectors = hybrid_builder(environment)
    progress = []
    result = builder.build(
        "demo", progress=lambda stage, generation=None: progress.append((stage, generation))
    )
    manifest, chunks = snapshot(engine, "demo", result["generation_id"])
    data = load_artifact(settings.runtime_dir, result["generation_id"], manifest)
    assert manifest["collection"].startswith("rag_hybrid_")
    assert manifest["pipeline"]["profile"] == "hybrid"
    assert data["sparse_vocabulary"] == {"103": 0, "word": 1, "词项": 2}
    assert result["external_calls_executed"] == 1
    assert embedder.calls == 1
    assert all(
        row["sparse"] == {2: 0.5, 0: 0.25, 1: 1.0}
        for row in vectors.collections[manifest["collection"]]
    )
    assert [stage for stage, _ in progress] == [
        "preparing",
        "encoding",
        "vector_write",
        "validating",
        "publishing",
    ]
    assert all(generation == result["generation_id"] for _, generation in progress[1:])
    with Session(engine) as session:
        assert session.get(IndexGeneration, local["generation_id"]).status == "ready"
    assert len(chunks) == result["source_chunks"]


@pytest.mark.parametrize("failure", ["fail_sparse", "corrupt_sparse", "bad_sparse"])
def test_hybrid_failure_does_not_replace_baseline(environment, failure):
    _, engine, _, _, _, _, baseline = environment
    local = baseline.build("demo")
    builder, embedder, vectors = hybrid_builder(environment)
    setattr(embedder if failure == "bad_sparse" else vectors, failure, True)
    with pytest.raises(RagError):
        builder.build("demo")
    assert active_generation(engine, "demo") == local["generation_id"]
    with Session(engine) as session:
        assert (
            len(
                list(
                    session.scalars(
                        select(IndexGeneration).where(IndexGeneration.status == "failed")
                    )
                )
            )
            == 1
        )


def test_permission_and_stale_input_block_remote_before_encode(environment):
    _, engine, source, prepared, *_ = environment
    path = source / "file.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "external_processing_allowed: true", "external_processing_allowed: false"
        ),
        encoding="utf-8",
    )
    prepare_documents(engine, "demo", source)
    builder, embedder, _ = hybrid_builder(environment)
    with pytest.raises(RagError) as caught:
        builder.build("demo", expected_prepared_id=prepared["generation_id"])
    assert caught.value.code == "prepared_input_changed"
    with pytest.raises(RagError) as caught:
        builder.build("demo")
    assert caught.value.code == "external_processing_not_allowed"
    assert embedder.calls == 0


def test_hybrid_vocabulary_requires_exact_mapping_even_with_valid_artifact_digest(environment):
    settings, engine, *_ = environment
    builder, _, _ = hybrid_builder(environment)
    result = builder.build("demo")
    manifest, _ = snapshot(engine, "demo", result["generation_id"])
    path = artifact_path(settings.runtime_dir, result["generation_id"])
    data = json.loads(path.read_bytes())
    data["sparse_vocabulary"]["word"] = 0
    content = json.dumps(data).encode()
    path.write_bytes(content)
    manifest["artifact_sha256"] = hashlib.sha256(content).hexdigest()
    with pytest.raises(RagError) as caught:
        load_artifact(settings.runtime_dir, result["generation_id"], manifest)
    assert caught.value.code == "index_artifact_unavailable"


def test_activate_retained_baseline_without_embedding(environment):
    settings, engine, _, _, _, local_vectors, baseline = environment
    local = baseline.build("demo")
    builder, _, _ = hybrid_builder(environment)
    builder.build("demo")
    vectors = HybridVectors()
    vectors.collections = local_vectors.collections
    result = activate_generation(settings, engine, vectors, "demo", local["generation_id"])
    assert result["external_calls_executed"] == 0
    assert active_generation(engine, "demo") == local["generation_id"]
    with pytest.raises(RagError):
        activate_generation(settings, engine, vectors, "other-kb", local["generation_id"])


class StoredHybridClient:
    def __init__(self, rows):
        self.rows = rows

    def describe_collection(self, _):
        from pymilvus import DataType

        return {
            "fields": [
                {"name": "dense", "params": {"dim": 3}},
                {"name": "sparse", "type": DataType.SPARSE_FLOAT_VECTOR},
            ]
        }

    def query(self, **kwargs):
        return [{"count(*)": len(self.rows)}]

    def get(self, **kwargs):
        return copy.deepcopy(self.rows)


@pytest.mark.parametrize("damage", ["dense", "sparse", "negative", "mapping"])
def test_hybrid_storage_validates_actual_vector_payloads(environment, monkeypatch, damage):
    settings, *_ = environment
    expected = [
        {
            "id": "a",
            "chunk_id": "c",
            "revision_id": "r",
            "kb_id": "kb",
            "generation_id": "g",
            "app_snapshot": "v",
            "feature_status": "delivered",
            "data_kind": "simulated",
            "dense": [1.0, 0.0, 0.0],
            "sparse": {0: 0.5},
        }
    ]
    actual = copy.deepcopy(expected)
    if damage == "dense":
        actual[0]["dense"] = [0.0, 1.0, 0.0]
    elif damage == "sparse":
        actual[0]["sparse"] = {1: 0.5}
    elif damage == "negative":
        actual[0]["sparse"] = {0: -1.0}
    else:
        actual[0]["revision_id"] = "wrong"
    vectors = MilvusVectors(settings)

    @contextmanager
    def client():
        yield StoredHybridClient(actual)

    monkeypatch.setattr(vectors, "client", client)
    with pytest.raises(RagError):
        vectors.validate_hybrid("unused", expected, 3)


def test_empty_sparse_query_is_local_and_returns_no_hits(environment, monkeypatch):
    settings, *_ = environment
    vectors = MilvusVectors(settings)
    monkeypatch.setattr(vectors, "client", lambda: pytest.fail("empty sparse must not hit DB"))
    assert vectors.search_sparse("unused", {}, "g", "kb") == []
