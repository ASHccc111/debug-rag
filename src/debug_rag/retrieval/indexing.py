"""Build/verify/publish immutable local indexes; capture a generation once per query."""

import hashlib
import json
import math
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from filelock import FileLock, Timeout
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from debug_rag.errors import RagError
from debug_rag.ingestion.documents import Metadata
from debug_rag.ingestion.service import fingerprint
from debug_rag.retrieval.lexical import TOKENIZER_VERSION, tokenize
from debug_rag.storage.sqlite import (
    Document,
    DocumentOrigin,
    DocumentRevision,
    GenerationDocument,
    IndexGeneration,
    KnowledgeBase,
    PreparedHead,
    SourceChunk,
    active_generation,
)


def snapshot(
    engine: Engine, kb_id: str, generation_id: str, *, include_parents: bool = False
) -> tuple[dict, list[dict]]:
    with Session(engine) as session:
        generation = session.get(IndexGeneration, generation_id)
        if generation is None or generation.kb_id != kb_id:
            raise RagError("generation_not_found", "知识库快照不存在。", 404)
        manifest = generation.manifest
        query = (
            select(SourceChunk, DocumentRevision, Document)
            .join(DocumentRevision, SourceChunk.revision_id == DocumentRevision.revision_id)
            .join(Document, Document.document_id == DocumentRevision.document_id)
            .join(
                GenerationDocument, GenerationDocument.revision_id == DocumentRevision.revision_id
            )
            .where(
                GenerationDocument.generation_id == generation_id,
                GenerationDocument.document_id == Document.document_id,
                Document.kb_id == kb_id,
                SourceChunk.config_key == manifest["config_key"],
                SourceChunk.kind.in_(["child", "parent"] if include_parents else ["child"]),
            )
            .order_by(Document.source_key, SourceChunk.ordinal)
        )
        rows, checked, origins = [], set(), {}
        for chunk, revision, document in session.execute(query):
            meta = Metadata.model_validate(revision.metadata_json).model_dump(mode="json")
            if (
                meta["app_snapshot"] != manifest["app_snapshot"]
                or meta["data_kind"] != manifest["data_kind"]
            ):
                raise RagError("source_scope_mismatch", "原文适用范围与索引清单不一致。", 409)
            if revision.revision_id not in checked:
                identity = {
                    "text": revision.raw_text,
                    "metadata": meta,
                    "format": revision.source_format,
                }
                origin = session.get(DocumentOrigin, revision.revision_id)
                if origin is not None:
                    identity["origin"] = origin.manifest
                    if (
                        hashlib.sha256(origin.original_bytes).hexdigest()
                        != origin.manifest["original_sha256"]
                    ):
                        raise RagError("source_integrity_failed", "保存的原始文件校验失败。", 409)
                    origins[revision.revision_id] = origin.manifest
                digest = fingerprint(identity)
                if digest != revision.fingerprint:
                    raise RagError("source_integrity_failed", "保存的文档版本校验失败。", 409)
                checked.add(revision.revision_id)
            if chunk.text != revision.raw_text[chunk.start_char : chunk.end_char]:
                raise RagError("source_mapping_failed", "片段不能准确定位原文。", 409)
            rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "kind": chunk.kind,
                    "parent_chunk_id": chunk.parent_chunk_id,
                    "document_id": document.document_id,
                    "revision_id": revision.revision_id,
                    "source_key": document.source_key,
                    "source_path": revision.source_path,
                    "metadata": meta,
                    "section_path": chunk.section_path,
                    "text": chunk.text,
                    "start_char": chunk.start_char,
                    "end_char": chunk.end_char,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "continuation": chunk.continuation,
                }
            )
        if (
            sum(row["kind"] == "child" for row in rows) != manifest["chunk_counts"]["child"]
            or (
                include_parents
                and sum(row["kind"] == "parent" for row in rows)
                != manifest["chunk_counts"]["parent"]
            )
            or len(checked) != manifest["document_count"]
        ):
            raise RagError("source_count_mismatch", "原文数量与快照清单不一致。", 409)
        for row in rows:
            origin = origins.get(row["revision_id"])
            if origin is not None:
                row.update(
                    original_sha256=origin["original_sha256"],
                    extraction_warnings=origin["warnings"],
                    source_locations=[
                        block["locator"]
                        for block in origin["blocks"]
                        if block["start_char"] < row["end_char"]
                        and block["end_char"] > row["start_char"]
                    ],
                )
        return dict(manifest), rows


def artifact_path(runtime: Path, generation_id: str) -> Path:
    if len(generation_id) != 32 or any(c not in "0123456789abcdef" for c in generation_id):
        raise RagError("invalid_generation_id", "索引 ID 不合法。", 409)
    return runtime / "indexes" / generation_id / "lexical.json"


def load_artifact(runtime: Path, generation_id: str, manifest: dict) -> dict:
    try:
        content = artifact_path(runtime, generation_id).read_bytes()
        if hashlib.sha256(content).hexdigest() != manifest["artifact_sha256"]:
            raise ValueError("Digest mismatch")
        data = json.loads(content)
        if data["generation_id"] != generation_id or data["tokenizer"] != TOKENIZER_VERSION:
            raise ValueError("Wrong generation or tokenizer")
        if manifest.get("pipeline", {}).get("profile") == "hybrid":
            vocabulary = data["sparse_vocabulary"]
            if (
                not isinstance(vocabulary, dict)
                or not vocabulary
                or any(not isinstance(term, str) or not term for term in vocabulary)
                or any(type(index) is not int for index in vocabulary.values())
                or sorted(vocabulary.values()) != list(range(len(vocabulary)))
            ):
                raise ValueError("Invalid sparse vocabulary")
        return data
    except (OSError, ValueError, KeyError, TypeError):
        raise RagError(
            "index_artifact_unavailable", "本地检索产物缺失或损坏，请重建索引。"
        ) from None


class IndexBuilder:
    def __init__(self, settings, engine, embedder, vectors):
        self.settings, self.engine, self.embedder, self.vectors = (
            settings,
            engine,
            embedder,
            vectors,
        )

    def build(self, kb_id: str, *, progress=None, expected_prepared_id=None) -> dict:
        locks = self.settings.runtime_dir / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(kb_id.encode()).hexdigest() + ".lock"
        try:
            with FileLock(locks / name, timeout=0):
                return self._build(
                    kb_id, progress=progress, expected_prepared_id=expected_prepared_id
                )
        except Timeout:
            raise RagError("index_build_busy", "该知识库已有索引构建任务。", 409) from None

    def _build(self, kb_id, *, progress=None, expected_prepared_id=None):
        def report(stage, generation_id=None):
            if progress is not None:
                progress(stage, generation_id)

        report("preparing")
        with Session(self.engine) as session:
            head = session.get(PreparedHead, kb_id)
            if head is None:
                raise RagError("documents_not_prepared", "请先导入完整文档目录。", 409)
            prepared_id = head.generation_id
            if expected_prepared_id is not None and prepared_id != expected_prepared_id:
                raise RagError("prepared_input_changed", "待构建资料已改变，请重新创建任务。", 409)
        base, chunks = snapshot(self.engine, kb_id, prepared_id)
        identity = self.embedder.identity
        hybrid = identity.get("provider") == "viking"
        if hybrid and any(not chunk["metadata"]["external_processing_allowed"] for chunk in chunks):
            raise RagError(
                "external_processing_not_allowed", "资料未许可远程编码，未调用服务。", 403
            )
        pipeline = {
            "profile": "hybrid" if hybrid else "light",
            "embedding": identity,
            "tokenizer": TOKENIZER_VERSION,
            "index": "FLAT",
            "metric": "COSINE",
            "schema_version": "p4-hybrid-v1" if hybrid else "p2-v1",
        }
        if hybrid:
            pipeline.update(
                sparse_index="SPARSE_INVERTED_INDEX",
                sparse_metric="IP",
                sparse_mapping="generation-vocabulary-v1",
            )
        # Publication is a new immutable generation; P1 prepared records remain untouched.
        generation_id = uuid4().hex
        collection = ("rag_hybrid_" if hybrid else "rag_light_") + generation_id
        manifest = {
            **base,
            "stage": "P4" if hybrid else "P2",
            "prepared_generation_id": prepared_id,
            "pipeline": pipeline,
            "collection": collection,
        }
        with Session(self.engine) as session, session.begin():
            session.add(
                IndexGeneration(
                    generation_id=generation_id, kb_id=kb_id, status="building", manifest=manifest
                )
            )
            session.flush()
            session.add_all(
                GenerationDocument(generation_id=generation_id, **member)
                for member in base["members"]
            )
        try:
            windows, texts, corpus = [], [], []
            for chunk in chunks:
                corpus.append(
                    {
                        "chunk_id": chunk["chunk_id"],
                        "tokens": tokenize(
                            chunk["metadata"]["title"]
                            + "\n"
                            + " / ".join(chunk["section_path"])
                            + "\n"
                            + chunk["text"]
                        ),
                    }
                )
                for start, end in self.embedder.windows(chunk["text"]):
                    windows.append(
                        {
                            "id": uuid5(
                                NAMESPACE_URL, f"{generation_id}:{chunk['chunk_id']}:{start}:{end}"
                            ).hex,
                            "chunk_id": chunk["chunk_id"],
                            "start": start,
                            "end": end,
                            "revision_id": chunk["revision_id"],
                        }
                    )
                    texts.append(chunk["text"][start:end])
            report("encoding", generation_id)
            if hybrid:
                encoded_rows = self.embedder.encode_hybrid(texts)
                encoded = [row["dense"] for row in encoded_rows]
                sparse_rows = [row["sparse"] for row in encoded_rows]
                if any(
                    not isinstance(row, dict)
                    or not row
                    or any(
                        not isinstance(term, str)
                        or not term
                        or isinstance(weight, bool)
                        or not isinstance(weight, (int, float))
                        or not math.isfinite(weight)
                        or weight <= 0
                        for term, weight in row.items()
                    )
                    for row in sparse_rows
                ):
                    raise RagError("invalid_sparse_embedding", "稀疏向量格式无效，未发布。", 409)
                vocabulary = {
                    term: index
                    for index, term in enumerate(
                        sorted({term for row in sparse_rows for term in row})
                    )
                }
            else:
                encoded = self.embedder.encode(texts)
                vocabulary = None
            if len(encoded) != len(windows) or not encoded:
                raise RagError("invalid_embedding_count", "向量数量与原文窗口不一致。", 409)
            if any(
                len(vector) != identity["dimension"]
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in vector
                )
                or sum(value * value for value in vector) <= 0
                for vector in encoded
            ):
                raise RagError("invalid_dense_embedding", "稠密向量格式或维度无效，未发布。", 409)
            lookup = {c["chunk_id"]: c for c in chunks}
            rows = [
                {
                    **{k: w[k] for k in ("id", "chunk_id", "revision_id")},
                    "kb_id": kb_id,
                    "generation_id": generation_id,
                    "app_snapshot": base["app_snapshot"],
                    "data_kind": base["data_kind"],
                    "feature_status": lookup[w["chunk_id"]]["metadata"]["feature_status"],
                    "dense": vector,
                }
                for w, vector in zip(windows, encoded)
            ]
            if hybrid:
                for row, sparse in zip(rows, sparse_rows):
                    row["sparse"] = {vocabulary[term]: weight for term, weight in sparse.items()}
            report("vector_write", generation_id)
            if hybrid:
                self.vectors.build_hybrid(collection, rows, identity["dimension"])
            else:
                self.vectors.build(collection, rows, identity["dimension"])
            report("validating", generation_id)
            if hybrid:
                self.vectors.validate_hybrid(collection, rows, identity["dimension"])
            else:
                self.vectors.validate(collection, rows, identity["dimension"])
            rows_by_id = {row["id"]: row for row in rows}

            def valid_probe(hits, minimum_score):
                if (
                    not hits
                    or not math.isfinite(hits[0]["score"])
                    or hits[0]["score"] < minimum_score
                ):
                    return False
                hit = hits[0]
                row = rows_by_id.get(hit.get("representation_id"))
                return row is not None and all(
                    hit.get(key) == row[key]
                    for key in ("kb_id", "generation_id", "revision_id", "chunk_id")
                )

            probe = self.vectors.search(
                collection, encoded[0], generation_id, kb_id, limit=1, delivered_only=False
            )
            if not valid_probe(probe, 0.999):
                raise RagError("index_probe_failed", "向量试检索失败，未发布。", 409)
            if hybrid:
                sparse_probe = self.vectors.search_sparse(
                    collection,
                    rows[0]["sparse"],
                    generation_id,
                    kb_id,
                    limit=1,
                    delivered_only=False,
                )
                if not valid_probe(sparse_probe, 0) or sparse_probe[0]["score"] <= 0:
                    raise RagError("sparse_probe_failed", "稀疏向量试检索失败，未发布。", 409)
            data = {
                "generation_id": generation_id,
                "tokenizer": TOKENIZER_VERSION,
                "corpus": corpus,
                "windows": windows,
            }
            if hybrid:
                data["sparse_vocabulary"] = vocabulary
            content = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
            path = artifact_path(self.settings.runtime_dir, generation_id)
            path.parent.mkdir(parents=True, exist_ok=False)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
            manifest.update(
                {
                    "artifact_sha256": hashlib.sha256(content).hexdigest(),
                    "representation_count": len(windows),
                }
            )
            load_artifact(self.settings.runtime_dir, generation_id, manifest)
            if len({c["chunk_id"] for c in chunks}) != len(corpus):
                raise RagError("duplicate_chunk_mapping", "原文片段身份重复。", 409)
            report("publishing", generation_id)
            with Session(self.engine) as session, session.begin():
                # Another ingest may have prepared newer documents while this build ran.
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                if session.get(PreparedHead, kb_id).generation_id != prepared_id:
                    raise RagError(
                        "prepared_input_changed", "构建期间输入已改变，请重新构建。", 409
                    )
                generation = session.get(IndexGeneration, generation_id)
                generation.manifest = manifest
                generation.status = "ready"
                session.get(KnowledgeBase, kb_id).active_generation_id = generation_id
            return {
                "kb_id": kb_id,
                "generation_id": generation_id,
                "status": "ready",
                "published": True,
                "source_chunks": len(chunks),
                "vector_windows": len(windows),
                "external_calls_executed": len(getattr(self.embedder, "last_calls", []))
                if hybrid
                else 0,
                "profile": pipeline["profile"],
            }
        except Exception as exc:
            with Session(self.engine) as session, session.begin():
                generation = session.get(IndexGeneration, generation_id)
                generation.status = "failed"
                generation.manifest = {
                    **manifest,
                    "failure_code": exc.code if isinstance(exc, RagError) else "index_build_failed",
                }
            # Retain owned staging artifacts for diagnosis; never drop other generations.
            raise


def published_snapshot(settings, engine, kb_id):
    generation_id = active_generation(engine, kb_id)
    if generation_id is None:
        raise RagError("knowledge_base_not_published", "知识库还未发布可检索索引。", 409)
    manifest, chunks = snapshot(engine, kb_id, generation_id)
    if manifest.get("stage") not in {"P2", "P4"} or "pipeline" not in manifest:
        raise RagError("incompatible_generation", "活跃索引不符合当前检索配置。", 409)
    return generation_id, manifest, chunks


def activate_generation(settings, engine, vectors, kb_id: str, generation_id: str) -> dict:
    """Switch to a previously verified generation without re-encoding or deleting anything."""
    locks = settings.runtime_dir / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    lock_path = locks / (hashlib.sha256(kb_id.encode()).hexdigest() + ".lock")
    try:
        with FileLock(lock_path, timeout=0):
            with Session(engine) as session:
                target = session.get(IndexGeneration, generation_id)
                if target is None or target.kb_id != kb_id or target.status != "ready":
                    raise RagError("generation_not_ready", "只能激活同库已校验完成的索引。", 409)
            manifest, chunks = snapshot(engine, kb_id, generation_id)
            data = load_artifact(settings.runtime_dir, generation_id, manifest)
            pipeline = manifest.get("pipeline", {})
            if pipeline.get("profile") not in {"light", "hybrid"}:
                raise RagError("incompatible_generation", "索引配置不兼容。", 409)
            lookup = {chunk["chunk_id"]: chunk for chunk in chunks}
            windows = data["windows"]
            if (
                len(windows) != manifest["representation_count"]
                or len({window["id"] for window in windows}) != len(windows)
                or {window["chunk_id"] for window in windows} != set(lookup)
                or {row["chunk_id"] for row in data["corpus"]} != set(lookup)
                or any(
                    window["revision_id"] != lookup[window["chunk_id"]]["revision_id"]
                    for window in windows
                )
            ):
                raise RagError("vector_mapping_mismatch", "索引窗口与原文清单不一致。", 409)
            expected = [
                {
                    **{key: window[key] for key in ("id", "chunk_id", "revision_id")},
                    "kb_id": kb_id,
                    "generation_id": generation_id,
                    "app_snapshot": manifest["app_snapshot"],
                    "data_kind": manifest["data_kind"],
                    "feature_status": lookup[window["chunk_id"]]["metadata"]["feature_status"],
                }
                for window in windows
            ]
            vectors.validate_existing(
                manifest["collection"],
                expected,
                pipeline["embedding"]["dimension"],
                hybrid=pipeline["profile"] == "hybrid",
            )
            with Session(engine) as session, session.begin():
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                target = session.get(IndexGeneration, generation_id)
                if target.status != "ready":
                    raise RagError("generation_not_ready", "目标索引状态已改变。", 409)
                kb = session.get(KnowledgeBase, kb_id)
                previous = kb.active_generation_id
                kb.active_generation_id = generation_id
            return {
                "kb_id": kb_id,
                "generation_id": generation_id,
                "previous_generation_id": previous,
                "profile": pipeline["profile"],
                "published": True,
                "external_calls_executed": 0,
            }
    except Timeout:
        raise RagError("index_build_busy", "该知识库已有索引任务，不能切换。", 409) from None
