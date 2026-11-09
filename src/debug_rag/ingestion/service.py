"""Atomic preparation of a complete input batch; never publishes a vector index."""

import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from debug_rag.ingestion.chunking import ChunkConfig, chunk_document
from debug_rag.ingestion.documents import IngestError, Issue, load_source
from debug_rag.storage.sqlite import (
    Document,
    DocumentOrigin,
    DocumentRevision,
    GenerationDocument,
    IndexGeneration,
    KnowledgeBase,
    PreparedHead,
    SourceChunk,
)


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def prepare_documents(
    engine: Engine, kb_id: str, source: Path, config: ChunkConfig | None = None
) -> dict:
    if not kb_id or len(kb_id) > 100:
        raise IngestError([Issue("", "invalid_kb_id")])
    config = config or ChunkConfig()
    docs = load_source(source)
    # Parse ALL inputs before opening a write transaction. One invalid file rejects the batch.
    parsed = [(doc, chunk_document(doc, config)) for doc in docs]
    if any(not chunks for _, chunks in parsed):
        raise IngestError([Issue("", "no_content_chunks")])
    snapshot = docs[0].metadata.app_snapshot
    data_kind = docs[0].metadata.data_kind
    config_key = fingerprint(config.model_dump())
    created_revisions = created_chunks = 0
    with Session(engine) as session, session.begin():
        existing = list(
            session.scalars(select(IndexGeneration).where(IndexGeneration.kb_id == kb_id))
        )
        for generation in existing:
            binding = generation.manifest
            if binding.get("app_snapshot") is not None and (
                binding["app_snapshot"] != snapshot or binding.get("data_kind") != data_kind
            ):
                raise IngestError([Issue("", "kb_snapshot_or_data_kind_conflict")])
        if session.get(KnowledgeBase, kb_id) is None:
            session.add(KnowledgeBase(kb_id=kb_id, title=kb_id, active_generation_id=None))
            session.flush()
        members = []
        counts = {"parent": 0, "child": 0}
        for doc, chunks in parsed:
            document = session.scalar(
                select(Document).where(
                    Document.kb_id == kb_id, Document.source_key == doc.metadata.source_key
                )
            )
            if document is None:
                document = Document(
                    document_id=uuid4().hex, kb_id=kb_id, source_key=doc.metadata.source_key
                )
                session.add(document)
                session.flush()
            meta = doc.metadata.model_dump(mode="json")
            identity = {"text": doc.raw_text, "metadata": meta, "format": doc.source_format}
            if doc.origin is not None:
                identity["origin"] = doc.origin["manifest"]
            digest = fingerprint(identity)
            revision = session.scalar(
                select(DocumentRevision).where(
                    DocumentRevision.document_id == document.document_id,
                    DocumentRevision.fingerprint == digest,
                )
            )
            if revision is None:
                revision = DocumentRevision(
                    revision_id=uuid4().hex,
                    document_id=document.document_id,
                    fingerprint=digest,
                    source_path=doc.source_path,
                    source_format=doc.source_format,
                    metadata_json=meta,
                    raw_text=doc.raw_text,
                    body_start=doc.body_start,
                )
                session.add(revision)
                session.flush()
                created_revisions += 1
                if doc.origin is not None:
                    session.add(
                        DocumentOrigin(
                            revision_id=revision.revision_id,
                            original_bytes=doc.origin["original"],
                            manifest=doc.origin["manifest"],
                        )
                    )
            ids = {
                c.ordinal: uuid5(
                    NAMESPACE_URL, f"debug-rag:{revision.revision_id}:{config_key}:{c.ordinal}"
                ).hex
                for c in chunks
            }
            for chunk in chunks:
                counts[chunk.kind] += 1
                if session.get(SourceChunk, ids[chunk.ordinal]) is None:
                    session.add(
                        SourceChunk(
                            chunk_id=ids[chunk.ordinal],
                            revision_id=revision.revision_id,
                            config_key=config_key,
                            parent_chunk_id=(
                                ids[chunk.parent_ordinal]
                                if chunk.parent_ordinal is not None
                                else None
                            ),
                            kind=chunk.kind,
                            ordinal=chunk.ordinal,
                            section_path=chunk.section_path,
                            text=chunk.text,
                            start_char=chunk.start_char,
                            end_char=chunk.end_char,
                            start_line=chunk.start_line,
                            end_line=chunk.end_line,
                            continuation=chunk.continuation,
                        )
                    )
                    # Ensure the self-referenced parent exists before writing its children.
                    session.flush()
                    created_chunks += 1
            members.append(
                {"document_id": document.document_id, "revision_id": revision.revision_id}
            )
        members.sort(key=lambda member: member["document_id"])
        manifest = {
            "stage": "P1",
            "app_snapshot": snapshot,
            "data_kind": data_kind,
            "config": config.model_dump(),
            "config_key": config_key,
            "members": members,
            "document_count": len(members),
            "chunk_counts": counts,
        }
        generation = next(
            (g for g in existing if g.status == "prepared" and g.manifest == manifest), None
        )
        reused = generation is not None
        if generation is None:
            generation = IndexGeneration(
                generation_id=uuid4().hex, kb_id=kb_id, status="prepared", manifest=manifest
            )
            session.add(generation)
            session.flush()
            session.add_all(
                GenerationDocument(generation_id=generation.generation_id, **member)
                for member in members
            )
        head = session.get(PreparedHead, kb_id)
        if head is None:
            session.add(PreparedHead(kb_id=kb_id, generation_id=generation.generation_id))
        else:
            head.generation_id = generation.generation_id
        result = {
            "kb_id": kb_id,
            "generation_id": generation.generation_id,
            "status": "prepared",
            "published": False,
            "reused_generation": reused,
            "documents": len(members),
            "chunks": counts,
            "created_revisions": created_revisions,
            "created_chunks": created_chunks,
            "external_calls_executed": 0,
        }
    return result


def inspect_generation(
    engine: Engine, kb_id: str, generation_id: str | None = None, include_chunks: bool = False
) -> dict:
    with Session(engine) as session:
        query = select(IndexGeneration).where(IndexGeneration.kb_id == kb_id)
        if generation_id:
            query = query.where(IndexGeneration.generation_id == generation_id)
        else:
            head = session.get(PreparedHead, kb_id)
            if head is None:
                raise IngestError([Issue("", "generation_not_found")])
            query = query.where(IndexGeneration.generation_id == head.generation_id)
        generation = session.scalar(query.order_by(IndexGeneration.created_at.desc()))
        if generation is None:
            raise IngestError([Issue("", "generation_not_found")])
        rows = session.execute(
            select(Document, DocumentRevision)
            .join(GenerationDocument, GenerationDocument.document_id == Document.document_id)
            .join(DocumentRevision, GenerationDocument.revision_id == DocumentRevision.revision_id)
            .where(GenerationDocument.generation_id == generation.generation_id)
            .order_by(Document.source_key)
        )
        result = {
            "kb_id": kb_id,
            "generation_id": generation.generation_id,
            "status": generation.status,
            "manifest": generation.manifest,
            "documents": [],
        }
        for document, revision in rows:
            item = {
                "document_id": document.document_id,
                "revision_id": revision.revision_id,
                "source_path_at_revision_creation": revision.source_path,
                "metadata": revision.metadata_json,
            }
            if include_chunks:
                chunks = session.scalars(
                    select(SourceChunk)
                    .where(
                        SourceChunk.revision_id == revision.revision_id,
                        SourceChunk.config_key == generation.manifest["config_key"],
                    )
                    .order_by(SourceChunk.ordinal)
                )
                item["chunks"] = [
                    {
                        "chunk_id": c.chunk_id,
                        "parent_chunk_id": c.parent_chunk_id,
                        "kind": c.kind,
                        "section_path": c.section_path,
                        "start_char": c.start_char,
                        "end_char": c.end_char,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "continuation": c.continuation,
                        "text": c.text,
                    }
                    for c in chunks
                ]
            result["documents"].append(item)
        return result
