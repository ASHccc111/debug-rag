import os

import pytest

from debug_rag.diagnostics import milvus_smoke, probe_milvus
from debug_rag.settings import Settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RAG_RUN_MILVUS_TESTS") != "1",
        reason="Set RAG_RUN_MILVUS_TESTS=1 after starting the local Milvus service",
    ),
]


def test_real_dense_sparse_and_delete():
    settings = Settings()
    assert probe_milvus(settings).status == "ok"
    assert milvus_smoke(settings) == {
        "dense": "passed",
        "sparse": "passed",
        "delete": "passed",
        "cleanup": "passed",
    }


def test_hybrid_storage_checks_payload_and_separate_routes():
    """Handmade vectors verify the DB adapter, not remote BGE-M3 inference."""
    from uuid import uuid4

    from debug_rag.diagnostics import new_milvus_client
    from debug_rag.storage.milvus import MilvusVectors

    settings = Settings()
    name = "p0_smoke_" + uuid4().hex
    vectors = MilvusVectors(settings)
    shared = {
        "kb_id": "hybrid-test",
        "generation_id": "test-generation",
        "app_snapshot": "test-v1",
        "feature_status": "delivered",
        "data_kind": "simulated",
    }
    rows = [
        {
            **shared,
            "id": "a",
            "chunk_id": "c-a",
            "revision_id": "r-a",
            "dense": [1.0, 0.0],
            "sparse": {0: 0.5, 2: 0.25},
        },
        {
            **shared,
            "id": "b",
            "chunk_id": "c-b",
            "revision_id": "r-b",
            "dense": [0.0, 1.0],
            "sparse": {1: 1.0},
        },
    ]
    try:
        vectors.build_hybrid(name, rows, 2)
        vectors.validate_hybrid(name, rows, 2)
        assert (
            vectors.search(name, [1.0, 0.0], "test-generation", "hybrid-test")[0]["chunk_id"]
            == "c-a"
        )
        assert (
            vectors.search_sparse(name, {1: 1.0}, "test-generation", "hybrid-test")[0]["chunk_id"]
            == "c-b"
        )
        assert not vectors.search_sparse(name, {1: 1.0}, "other-generation", "hybrid-test")
    finally:
        client = new_milvus_client(settings)
        try:
            if client.has_collection(name):
                client.drop_collection(name)
        finally:
            client.close()
