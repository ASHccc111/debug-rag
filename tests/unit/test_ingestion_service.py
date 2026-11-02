import json
from pathlib import Path

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from test_ingestion_documents import markdown

from debug_rag import cli, diagnostics
from debug_rag.diagnostics import Check
from debug_rag.ingestion.chunking import ChunkConfig
from debug_rag.ingestion.documents import IngestError
from debug_rag.ingestion.service import inspect_generation, prepare_documents
from debug_rag.settings import Settings
from debug_rag.storage.sqlite import (
    Document,
    DocumentRevision,
    IndexGeneration,
    KnowledgeBase,
    SourceChunk,
    active_generation,
    create_database,
)


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "one.md").write_text(markdown("# 标题\n\n版本一正文。\n"), encoding="utf-8")
    engine = create_database(tmp_path / "runtime" / "metadata.sqlite3")
    yield source, engine
    engine.dispose()


def counts(engine):
    with Session(engine) as session:
        return tuple(
            session.scalar(select(func.count()).select_from(cls))
            for cls in (Document, DocumentRevision, SourceChunk, IndexGeneration)
        )


def test_idempotent_import_rename_and_restart(setup):
    source, engine = setup
    first = prepare_documents(engine, "demo", source)
    before = counts(engine)
    (source / "one.md").rename(source / "renamed.md")
    again = prepare_documents(engine, "demo", source)
    assert first["generation_id"] == again["generation_id"]
    assert again["reused_generation"] is True
    assert again["created_revisions"] == again["created_chunks"] == 0
    assert counts(engine) == before
    assert active_generation(engine, "demo") is None
    path = Path(engine.url.database)
    engine.dispose()
    restarted = create_database(path)
    try:
        info = inspect_generation(restarted, "demo", include_chunks=True)
        assert info["generation_id"] == first["generation_id"]
        assert info["documents"][0]["source_path_at_revision_creation"] == "one.md"
        assert info["documents"][0]["metadata"]["external_processing_allowed"] is False
    finally:
        restarted.dispose()


def test_revision_history_and_return_to_previous_prepared_generation(setup):
    source, engine = setup
    path = source / "one.md"
    original = path.read_text(encoding="utf-8")
    first = prepare_documents(engine, "demo", source)
    path.write_text(original + "新增说明。\n", encoding="utf-8")
    second = prepare_documents(engine, "demo", source)
    assert second["created_revisions"] == 1
    assert second["generation_id"] != first["generation_id"]
    old = inspect_generation(engine, "demo", first["generation_id"], True)
    assert "新增说明" not in old["documents"][0]["chunks"][0]["text"]
    assert counts(engine)[0:2] == (1, 2)
    path.write_text(original, encoding="utf-8")
    reverted = prepare_documents(engine, "demo", source)
    assert reverted["generation_id"] == first["generation_id"]
    assert inspect_generation(engine, "demo")["generation_id"] == first["generation_id"]


def test_config_change_reuses_revision_but_prepares_new_generation(setup):
    source, engine = setup
    first = prepare_documents(engine, "demo", source)
    second = prepare_documents(engine, "demo", source, ChunkConfig(child_chars=300))
    assert second["created_revisions"] == 0
    assert second["created_chunks"] > 0
    assert second["generation_id"] != first["generation_id"]
    assert counts(engine)[0:2] == (1, 1)


def test_invalid_batch_and_database_failure_leave_published_and_prepared_state(setup):
    source, engine = setup
    first = prepare_documents(engine, "demo", source)
    with Session(engine) as session, session.begin():
        session.add(IndexGeneration(generation_id="old-live", kb_id="demo", status="ready"))
        session.get(KnowledgeBase, "demo").active_generation_id = "old-live"
    before = counts(engine)
    (source / "invalid.md").write_text("没有元数据", encoding="utf-8")
    with pytest.raises(IngestError):
        prepare_documents(engine, "demo", source)
    assert counts(engine) == before
    (source / "invalid.md").unlink()
    (source / "new.md").write_text(markdown(source_key="another"), encoding="utf-8")

    def fail_insert(*_):
        raise RuntimeError("simulated disk write failure")

    event.listen(SourceChunk, "before_insert", fail_insert)
    try:
        with pytest.raises(RuntimeError):
            prepare_documents(engine, "demo", source)
    finally:
        event.remove(SourceChunk, "before_insert", fail_insert)
    assert counts(engine) == before
    assert active_generation(engine, "demo") == "old-live"
    assert inspect_generation(engine, "demo")["generation_id"] == first["generation_id"]


def test_snapshot_data_kind_and_knowledge_base_isolation(setup):
    source, engine = setup
    first = prepare_documents(engine, "demo", source)
    path = source / "one.md"
    path.write_text(markdown(app_snapshot="demo-v2"), encoding="utf-8")
    with pytest.raises(IngestError) as caught:
        prepare_documents(engine, "demo", source)
    assert caught.value.issues[0].code == "kb_snapshot_or_data_kind_conflict"
    other = prepare_documents(engine, "other", source)
    with pytest.raises(IngestError):
        inspect_generation(engine, "demo", other["generation_id"])
    path.write_text(markdown(data_kind="business"), encoding="utf-8")
    with pytest.raises(IngestError):
        prepare_documents(engine, "demo", source)
    assert inspect_generation(engine, "demo")["generation_id"] == first["generation_id"]


def test_real_simulated_fixture_batch_has_valid_exact_sources(tmp_path):
    source = Path(__file__).resolve().parents[2] / "fixtures" / "documents"
    engine = create_database(tmp_path / "metadata.sqlite3")
    try:
        first = prepare_documents(engine, "fixture", source)
        assert first["documents"] == 8
        assert first["published"] is False
        assert prepare_documents(engine, "fixture", source)["reused_generation"] is True
        with Session(engine) as session:
            revisions = {r.revision_id: r for r in session.scalars(select(DocumentRevision))}
            for c in session.scalars(select(SourceChunk)):
                assert c.text == revisions[c.revision_id].raw_text[c.start_char : c.end_char]
        result = inspect_generation(engine, "fixture", include_chunks=True)
        assert {d["metadata"]["feature_status"] for d in result["documents"]} == {
            "delivered",
            "planned",
        }
    finally:
        engine.dispose()


def test_cli_prepare_inspect_and_doctor_still_not_ready(setup, tmp_path, monkeypatch, capsys):
    source, engine = setup
    monkeypatch.setattr(
        cli, "Settings", lambda: Settings(_env_file=None, runtime_dir=tmp_path / "cli")
    )
    assert cli.main(["ingest", "--kb", "demo", "--source", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "prepared"
    assert cli.main(["inspect", "--kb", "demo", "--chunks"]) == 0
    assert len(json.loads(capsys.readouterr().out)["documents"]) == 1
    monkeypatch.setattr(diagnostics, "probe_milvus", lambda _: Check(status="ok", detail="test"))
    assert cli.main(["doctor", "--require-ready"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["ready"] is False
    assert result["external_calls_executed"] == 0
