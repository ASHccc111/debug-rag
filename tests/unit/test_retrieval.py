import pytest
from filelock import FileLock
from p2_support import FakeEmbedder
from sqlalchemy import select
from sqlalchemy.orm import Session

from debug_rag.errors import RagError
from debug_rag.ingestion.service import prepare_documents
from debug_rag.retrieval.indexing import artifact_path
from debug_rag.retrieval.lexical import fuse, tokenize
from debug_rag.retrieval.service import RagService
from debug_rag.storage.sqlite import IndexGeneration, active_generation, create_database


def test_tokenizer_preserves_identifiers_and_chinese_bigrams():
    tokens = tokenize("相机状态 camera_state phase.error CODE_500")
    assert tokens == ["相机", "机状", "状态", "camera_state", "phase.error", "code_500"]


def test_rrf_is_rank_based_within_route_deduplication():
    fused = fuse(
        {
            "dense": [
                {"chunk_id": "a", "score": 0.7},
                {"chunk_id": "a", "score": 0.6},
                {"chunk_id": "b", "score": 0.5},
            ],
            "bm25": [{"chunk_id": "b", "score": 999}],
        }
    )
    assert fused[0]["chunk_id"] == "b"
    assert fused[0]["rrf_score"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1]["rrf_score"] == pytest.approx(1 / 61)


def test_publish_and_search_deduplicate_windows_filter_plans_and_preserve_sources(environment):
    settings, engine, _, prepared, embedder, vectors, builder = environment
    published = builder.build("demo")
    assert published["generation_id"] != prepared["generation_id"]
    assert published["vector_windows"] > published["source_chunks"]
    with Session(engine) as session:
        assert session.get(IndexGeneration, prepared["generation_id"]).status == "prepared"
    result = RagService(settings, engine, embedder, vectors, None).search(
        "demo", "相机退出如何清理？"
    )
    ids = [c["chunk_id"] for c in result["candidates"]]
    assert len(ids) == len(set(ids))
    assert all(c["metadata"]["feature_status"] == "delivered" for c in result["candidates"])
    assert result["trace"]["rerank_enabled"] is False
    assert result["trace"]["external_calls_executed"] == 0


def test_failed_build_never_replaces_old_pointer_and_marks_failed(environment):
    _, engine, _, _, _, vectors, builder = environment
    old = builder.build("demo")
    vectors.fail_validation = True
    with pytest.raises(RuntimeError):
        builder.build("demo")
    assert active_generation(engine, "demo") == old["generation_id"]
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


def test_inflight_prepared_change_prevents_publication(environment, monkeypatch):
    _, engine, source, _, _, vectors, builder = environment
    old = builder.build("demo")
    validate = vectors.validate

    def change_input(*args):
        validate(*args)
        path = source / "file.md"
        path.write_text(path.read_text(encoding="utf-8") + "新增段落。", encoding="utf-8")
        prepare_documents(engine, "demo", source)

    monkeypatch.setattr(vectors, "validate", change_input)
    with pytest.raises(RagError) as caught:
        builder.build("demo")
    assert caught.value.code == "prepared_input_changed"
    assert active_generation(engine, "demo") == old["generation_id"]


def test_corrupt_artifact_foreign_hit_and_changed_model_are_service_errors(environment):
    settings, engine, _, _, embedder, vectors, builder = environment
    published = builder.build("demo")
    service = RagService(settings, engine, embedder, vectors, None)
    vectors.foreign_hit = True
    with pytest.raises(RagError) as caught:
        service.search("demo", "相机")
    assert caught.value.code == "retrieval_mapping_invalid"
    vectors.foreign_hit = False
    embedder.identity = {**embedder.identity, "revision": "different"}
    with pytest.raises(RagError) as caught:
        service.search("demo", "相机")
    assert caught.value.code == "embedding_identity_mismatch"
    embedder.identity = FakeEmbedder.identity
    artifact_path(settings.runtime_dir, published["generation_id"]).write_text(
        "{}", encoding="utf-8"
    )
    with pytest.raises(RagError) as caught:
        service.search("demo", "相机")
    assert caught.value.code == "index_artifact_unavailable"


def test_build_lock_reports_busy(environment):
    import hashlib

    settings, _, _, _, _, _, builder = environment
    directory = settings.runtime_dir / "locks"
    directory.mkdir()
    with FileLock(directory / (hashlib.sha256(b"demo").hexdigest() + ".lock")):
        with pytest.raises(RagError) as caught:
            builder.build("demo")
        assert caught.value.code == "index_build_busy"


def test_index_survives_database_restart(environment):
    settings, engine, _, _, embedder, vectors, builder = environment
    published = builder.build("demo")
    engine.dispose()
    restarted = create_database(settings.sqlite_path)
    try:
        result = RagService(settings, restarted, embedder, vectors, None).search("demo", "文件保存")
        assert result["generation_id"] == published["generation_id"]
        assert any(c["source_key"] == "file" for c in result["candidates"])
    finally:
        restarted.dispose()
