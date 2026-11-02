from sqlalchemy.orm import Session

from debug_rag.storage.sqlite import (
    IndexGeneration,
    KnowledgeBase,
    active_generation,
    check_database,
    create_database,
)


def test_initialization_and_restart_preserve_records(tmp_path):
    path = tmp_path / "metadata.sqlite3"
    engine = create_database(path)
    with Session(engine) as session:
        session.add(KnowledgeBase(kb_id="demo", title="Demo", active_generation_id="g1"))
        session.add(IndexGeneration(generation_id="g1", kb_id="demo", status="ready"))
        session.commit()
    engine.dispose()
    restarted = create_database(path)
    try:
        check_database(restarted)
        assert active_generation(restarted, "demo") == "g1"
    finally:
        restarted.dispose()


def test_missing_building_failed_or_foreign_generation_is_not_active(tmp_path):
    engine = create_database(tmp_path / "metadata.sqlite3")
    try:
        assert active_generation(engine, "demo") is None
        with Session(engine) as session:
            session.add(KnowledgeBase(kb_id="demo", title="Demo", active_generation_id="g1"))
            session.add(IndexGeneration(generation_id="g1", kb_id="demo", status="building"))
            session.commit()
        assert active_generation(engine, "demo") is None
        with Session(engine) as session:
            generation = session.get(IndexGeneration, "g1")
            generation.status = "ready"
            generation.kb_id = "another-kb"
            session.commit()
        assert active_generation(engine, "demo") is None
    finally:
        engine.dispose()
