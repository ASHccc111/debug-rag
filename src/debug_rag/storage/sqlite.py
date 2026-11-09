"""Metadata store. Additive P1 tables preserve P0 databases and published pointers."""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    select,
    text,
)
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    kb_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    active_generation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)


class IndexGeneration(Base):
    __tablename__ = "index_generations"
    generation_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30))
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("kb_id", "source_key"),)
    document_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.kb_id"), index=True)
    source_key: Mapped[str] = mapped_column(String(100))


class DocumentRevision(Base):
    __tablename__ = "document_revisions"
    __table_args__ = (UniqueConstraint("document_id", "fingerprint"),)
    revision_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.document_id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    source_path: Mapped[str] = mapped_column(Text)
    source_format: Mapped[str] = mapped_column(String(10))
    metadata_json: Mapped[dict] = mapped_column(JSON)
    # Original decoded text, including BOM and CRLF if present; never a model rewrite.
    raw_text: Mapped[str] = mapped_column(Text)
    body_start: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class DocumentOrigin(Base):
    """Additive table: preserved binary original + reviewed extraction mapping."""

    __tablename__ = "document_origins"
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("document_revisions.revision_id"), primary_key=True
    )
    original_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    manifest: Mapped[dict] = mapped_column(JSON)


class SourceChunk(Base):
    __tablename__ = "source_chunks"
    chunk_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("document_revisions.revision_id"), index=True
    )
    config_key: Mapped[str] = mapped_column(String(64), index=True)
    parent_chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_chunks.chunk_id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    ordinal: Mapped[int] = mapped_column(Integer)
    section_path: Mapped[list] = mapped_column(JSON)
    text: Mapped[str] = mapped_column(Text)
    start_char: Mapped[int] = mapped_column(Integer)
    end_char: Mapped[int] = mapped_column(Integer)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    continuation: Mapped[bool] = mapped_column(Boolean)


class GenerationDocument(Base):
    __tablename__ = "generation_documents"
    generation_id: Mapped[str] = mapped_column(
        ForeignKey("index_generations.generation_id"), primary_key=True
    )
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.document_id"), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("document_revisions.revision_id"))


class PreparedHead(Base):
    __tablename__ = "prepared_heads"
    kb_id: Mapped[str] = mapped_column(ForeignKey("knowledge_bases.kb_id"), primary_key=True)
    generation_id: Mapped[str] = mapped_column(ForeignKey("index_generations.generation_id"))


class ApiCall(Base):
    __tablename__ = "api_calls"
    call_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    purpose: Mapped[str] = mapped_column(String(30))
    requested_model: Mapped[str] = mapped_column(String(100))
    served_model: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    reserved_units: Mapped[int] = mapped_column(Integer)
    charged_units: Mapped[int] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pricing: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class IndexJob(Base):
    __tablename__ = "index_jobs"
    job_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30))
    stage: Mapped[str] = mapped_column(String(60))
    generation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def create_database(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite", database=str(path)),
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    with engine.connect() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
    Base.metadata.create_all(engine)
    return engine


def check_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def active_generation(engine: Engine, kb_id: str) -> str | None:
    with Session(engine) as session:
        kb = session.get(KnowledgeBase, kb_id)
        if not kb or not kb.active_generation_id:
            return None
        generation = session.scalar(
            select(IndexGeneration).where(
                IndexGeneration.generation_id == kb.active_generation_id,
                IndexGeneration.kb_id == kb_id,
                IndexGeneration.status == "ready",
            )
        )
        return generation.generation_id if generation else None
