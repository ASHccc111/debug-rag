"""Read-only probes, plus explicitly requested disposable smoke tests. No paid APIs."""

import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from debug_rag.settings import Settings
from debug_rag.storage.sqlite import IndexGeneration, active_generation, check_database


class Check(BaseModel):
    status: Literal["ok", "error", "not_initialized", "not_configured", "not_checked"]
    detail: str


def new_milvus_client(settings: Settings):
    from pymilvus import MilvusClient

    return MilvusClient(
        uri=settings.milvus_uri,
        token=settings.milvus_token.get_secret_value(),
        timeout=settings.milvus_timeout_seconds,
    )


def probe_milvus(settings: Settings) -> Check:
    client = None
    try:
        client = new_milvus_client(settings)
        version = client.get_server_version(timeout=settings.milvus_timeout_seconds)
        if not version.lstrip("v").startswith("2.6."):
            return Check(status="error", detail=f"Expected Milvus 2.6.x; received {version}")
        return Check(status="ok", detail=f"Milvus {version}; read-only connection verified")
    except Exception as exc:
        # Exception strings may contain endpoint credentials. Report type, never raw args.
        return Check(status="error", detail=f"Milvus unavailable ({type(exc).__name__})")
    finally:
        if client is not None:
            client.close()


def probe_collection(settings: Settings, manifest: dict) -> Check:
    client = None
    try:
        client = new_milvus_client(settings)
        description = client.describe_collection(manifest["collection"])
        fields = {field["name"]: field for field in description["fields"]}
        dimension = int(fields["dense"]["params"]["dim"])
        if dimension != manifest["pipeline"]["embedding"]["dimension"]:
            raise ValueError("Wrong dimension")
        if manifest["pipeline"]["profile"] == "hybrid":
            from pymilvus import DataType

            if fields.get("sparse", {}).get("type") != DataType.SPARSE_FLOAT_VECTOR:
                raise ValueError("Missing sparse field")
        count = client.query(
            collection_name=manifest["collection"],
            filter="",
            output_fields=["count(*)"],
            consistency_level="Strong",
        )[0]["count(*)"]
        if count != manifest["representation_count"]:
            raise ValueError("Wrong row count")
        return Check(status="ok", detail="Published collection schema and count verified")
    except Exception:
        return Check(status="error", detail="Published collection missing or inconsistent")
    finally:
        if client is not None:
            client.close()


def readiness(settings: Settings, engine: Engine) -> dict:
    from debug_rag.retrieval.indexing import load_artifact

    knowledge = Check(status="not_initialized", detail="No verified published index")
    published_profile = None
    manifest = {}
    try:
        check_database(engine)
        database = Check(status="ok", detail="SQLite query succeeded")
        generation_id = active_generation(engine, settings.kb_id)
    except Exception as exc:
        database = Check(status="error", detail=f"SQLite unavailable ({type(exc).__name__})")
        generation_id = None
    if generation_id:
        try:
            with Session(engine) as session:
                generation = session.get(IndexGeneration, generation_id)
                manifest = generation.manifest
                load_artifact(settings.runtime_dir, generation_id, manifest)
                published_profile = manifest.get("pipeline", {}).get("profile")
                if manifest.get("stage") in {"P2", "P4"}:
                    knowledge = Check(status="ok", detail="Published index artifacts verified")
        except Exception:
            knowledge = Check(status="error", detail="Published index artifacts unavailable")
    if settings.embedding_backend == "viking":
        from debug_rag.budget import now_shanghai
        from debug_rag.retrieval.remote_embedding import VikingEmbedder

        today = now_shanghai().date()
        embedding_configured = bool(
            settings.viking_api_key.get_secret_value()
            and settings.viking_request_upper_bound_cny is not None
            and settings.viking_price_verified_on is not None
            and settings.viking_price_valid_through is not None
            and settings.viking_price_verified_on <= today <= settings.viking_price_valid_through
            and manifest.get("pipeline", {}).get("embedding")
            == VikingEmbedder(settings, None).identity
        )
    else:
        embedding_configured = bool(
            settings.embedding_model_path and settings.embedding_model_path.is_dir()
        )
    matches_profile = published_profile == (
        "hybrid" if settings.embedding_backend == "viking" else "light"
    )
    milvus = probe_milvus(settings)
    collection = (
        probe_collection(settings, manifest)
        if knowledge.status == "ok" and milvus.status == "ok"
        else Check(status="not_checked", detail="A published index and Milvus must be available")
    )
    checks = {
        "sqlite": database,
        "milvus": milvus,
        "knowledge_base": knowledge,
        "published_vectors": collection,
        "model_pipeline": Check(
            status="ok"
            if (
                settings.allow_external_calls
                and settings.deepseek_api_key.get_secret_value()
                and embedding_configured
                and matches_profile
            )
            else "not_configured",
            detail="Configuration only, no paid probe; external generation needs a key and opt-in.",
        ),
    }
    return {
        "ready": all(check.status == "ok" for check in checks.values()),
        "stage": "P3-P4",
        "published_profile": published_profile,
        "embedding_backend": settings.embedding_backend,
        "retrieval_ready": all(
            checks[name].status == "ok"
            for name in ("sqlite", "milvus", "knowledge_base", "published_vectors")
        )
        and embedding_configured
        and matches_profile
        and (settings.embedding_backend == "local" or settings.allow_external_calls),
        "checks": {name: check.model_dump() for name, check in checks.items()},
    }


def milvus_smoke(settings: Settings) -> dict:
    """Verify real dense/sparse I/O, deleting only a collection created by this call."""
    from pymilvus import DataType, MilvusClient

    client = new_milvus_client(settings)
    name = "p0_smoke_" + uuid4().hex
    created = False
    try:
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("dense", DataType.FLOAT_VECTOR, dim=2)
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        indexes = client.prepare_index_params()
        indexes.add_index(field_name="dense", index_type="FLAT", metric_type="COSINE")
        indexes.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="IP")
        client.create_collection(collection_name=name, schema=schema, index_params=indexes)
        created = True
        client.insert(
            collection_name=name,
            data=[
                {"id": 1, "dense": [1.0, 0.0], "sparse": {1: 1.0}},
                {"id": 2, "dense": [0.0, 1.0], "sparse": {2: 1.0}},
            ],
        )
        for field, vector, metric in [
            ("dense", [1.0, 0.0], "COSINE"),
            ("sparse", {1: 1.0}, "IP"),
        ]:
            hits = client.search(
                collection_name=name,
                data=[vector],
                anns_field=field,
                limit=1,
                search_params={"metric_type": metric},
                consistency_level="Strong",
            )
            if not hits or not hits[0] or hits[0][0]["id"] != 1:
                raise RuntimeError(f"{field} retrieval did not match the inserted record")
        client.delete(collection_name=name, ids=[1])
        remaining = client.query(collection_name=name, filter="id == 1", consistency_level="Strong")
        if remaining:
            raise RuntimeError("Deleted smoke record is still visible")
    finally:
        try:
            if created:
                client.drop_collection(collection_name=name)
        finally:
            client.close()
    return {"dense": "passed", "sparse": "passed", "delete": "passed", "cleanup": "passed"}


def model_smoke(path: Path) -> dict:
    """Load existing files only; this diagnostic never downloads a model."""
    import os

    if not path.is_dir() or not (path / "config.json").is_file():
        raise ValueError("Provide an existing, complete local model directory")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    started = time.perf_counter()
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(4)
    model = SentenceTransformer(str(path.resolve()), device="cpu", local_files_only=True)
    initialization_ms = round((time.perf_counter() - started) * 1000, 2)
    texts = ["相机状态如何显示在悬浮窗？", "悬浮窗展示设备状态。", "文件导出后检查结果。"]
    durations = []
    for _ in range(3):
        started = time.perf_counter()
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        durations.append(round((time.perf_counter() - started) * 1000, 2))
    if not torch.isfinite(torch.from_numpy(vectors)).all():
        raise RuntimeError("Embedding contains non-finite values")
    return {
        "model_directory": path.name,
        "device": "cpu",
        "shape": list(vectors.shape),
        "initialization_ms_including_imports": initialization_ms,
        "three_batch_encode_ms": durations,
        "scope": "3 short simulated texts; not an end-to-end RAG benchmark",
    }
