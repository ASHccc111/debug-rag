"""Readiness validates metadata/configuration without probing a paid embedding API."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from debug_rag import budget, diagnostics
from debug_rag.budget import SHANGHAI
from debug_rag.retrieval.indexing import artifact_path
from debug_rag.retrieval.remote_embedding import VikingEmbedder
from debug_rag.storage.sqlite import ApiCall, IndexGeneration


@pytest.fixture
def probes(monkeypatch):
    """Every service observation is simulated; real database clients are forbidden."""
    monkeypatch.setattr(
        diagnostics,
        "probe_milvus",
        lambda _: diagnostics.Check(status="ok", detail="simulated Milvus availability"),
    )
    monkeypatch.setattr(
        diagnostics,
        "probe_collection",
        lambda *_: diagnostics.Check(status="ok", detail="simulated collection verification"),
    )
    monkeypatch.setattr(
        diagnostics,
        "new_milvus_client",
        lambda *_: pytest.fail("Readiness unit tests must not connect to a database service"),
    )
    monkeypatch.setattr(
        VikingEmbedder,
        "encode_hybrid",
        lambda *_args, **_kwargs: pytest.fail("Readiness must never call remote encoding"),
    )
    monkeypatch.setattr(budget, "now_shanghai", lambda: datetime(2026, 11, 2, 12, tzinfo=SHANGHAI))


@pytest.fixture
def remote_profile(environment, probes):
    settings, engine, _, _, _, _, builder = environment
    published = builder.build("demo")
    settings = settings.model_copy(
        update={
            "kb_id": "demo",
            "embedding_backend": "viking",
            "allow_external_calls": True,
            "viking_api_key": SecretStr("unit-test-placeholder"),
            "deepseek_api_key": SecretStr("unit-test-placeholder"),
            "viking_request_upper_bound_cny": Decimal("0.01"),
            "viking_price_verified_on": date(2026, 11, 2),
            "viking_price_valid_through": date(2026, 11, 3),
        }
    )
    # Build a metadata-only hybrid fixture from the disposable local generation.
    # Vector reads remain mocked; this does not assert a real hybrid index exists.
    path = artifact_path(settings.runtime_dir, published["generation_id"])
    artifact = json.loads(path.read_bytes())
    artifact["sparse_vocabulary"] = {"simulated-term": 0}
    content = json.dumps(artifact, ensure_ascii=False, sort_keys=True).encode("utf-8")
    path.write_bytes(content)
    with Session(engine) as session, session.begin():
        generation = session.get(IndexGeneration, published["generation_id"])
        manifest = dict(generation.manifest)
        manifest["stage"] = "P4"
        manifest["pipeline"] = {
            **manifest["pipeline"],
            "profile": "hybrid",
            "embedding": VikingEmbedder(settings, None).identity,
        }
        manifest["artifact_sha256"] = hashlib.sha256(content).hexdigest()
        generation.manifest = manifest
    return settings, engine


def test_remote_ready_means_configuration_and_local_metadata_only(remote_profile):
    settings, engine = remote_profile
    result = diagnostics.readiness(settings, engine)
    assert result["retrieval_ready"] is True
    assert result["ready"] is True
    assert result["published_profile"] == "hybrid"
    assert result["checks"]["model_pipeline"]["status"] == "ok"
    assert "no paid probe" in result["checks"]["model_pipeline"]["detail"]
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(ApiCall)) == 0


@pytest.mark.parametrize(
    "updates",
    [
        {"viking_price_valid_through": date(2026, 11, 1)},
        {"viking_price_verified_on": date(2026, 11, 3)},
        {"viking_request_upper_bound_cny": None},
        {"viking_price_verified_on": None},
        {"viking_api_key": SecretStr("")},
    ],
)
def test_invalid_remote_configuration_is_not_ready(remote_profile, updates):
    settings, engine = remote_profile
    result = diagnostics.readiness(settings.model_copy(update=updates), engine)
    assert result["retrieval_ready"] is False
    assert result["ready"] is False
    assert result["checks"]["model_pipeline"]["status"] == "not_configured"


def test_remote_identity_drift_cannot_report_ready(remote_profile):
    settings, engine = remote_profile
    changed = settings.model_copy(update={"viking_embedding_revision": "different-config"})
    result = diagnostics.readiness(changed, engine)
    assert result["retrieval_ready"] is False
    assert result["checks"]["knowledge_base"]["status"] == "ok"
    assert result["checks"]["model_pipeline"]["status"] == "not_configured"


def test_published_collection_missing_cannot_report_ready(remote_profile, monkeypatch):
    settings, engine = remote_profile
    monkeypatch.setattr(
        diagnostics,
        "probe_collection",
        lambda *_: diagnostics.Check(status="error", detail="simulated missing collection"),
    )
    result = diagnostics.readiness(settings, engine)
    assert result["retrieval_ready"] is False
    assert result["ready"] is False
    assert result["checks"]["published_vectors"]["status"] == "error"


def test_global_external_switch_blocks_remote_readiness(remote_profile):
    settings, engine = remote_profile
    result = diagnostics.readiness(
        settings.model_copy(update={"allow_external_calls": False}), engine
    )
    assert result["retrieval_ready"] is False
    assert result["ready"] is False
    assert result["checks"]["model_pipeline"]["status"] == "not_configured"


def test_local_retrieval_can_be_ready_while_generation_is_disabled(environment, probes, tmp_path):
    settings, engine, _, _, _, _, builder = environment
    builder.build("demo")
    model_path = tmp_path / "simulated-local-model-path"
    model_path.mkdir()
    settings = settings.model_copy(update={"kb_id": "demo", "embedding_model_path": model_path})
    result = diagnostics.readiness(settings, engine)
    assert result["published_profile"] == "light"
    assert result["retrieval_ready"] is True
    assert result["ready"] is False
    assert result["checks"]["model_pipeline"]["status"] == "not_configured"


def test_backend_mismatch_with_published_profile_is_not_ready(remote_profile, tmp_path):
    settings, engine = remote_profile
    model_path = tmp_path / "simulated-local-model-path"
    model_path.mkdir()
    local = settings.model_copy(
        update={"embedding_backend": "local", "embedding_model_path": model_path}
    )
    result = diagnostics.readiness(local, engine)
    assert result["retrieval_ready"] is False
    assert result["checks"]["model_pipeline"]["status"] == "not_configured"
