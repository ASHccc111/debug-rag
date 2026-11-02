import os

import pytest
from p2_support import FakeEmbedder, FakeVectors
from test_ingestion_documents import markdown

from debug_rag.ingestion.service import prepare_documents
from debug_rag.retrieval.indexing import IndexBuilder
from debug_rag.settings import Settings
from debug_rag.storage.sqlite import create_database


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    """Unit tests must never inherit workstation keys, prices or paid-call flags."""
    for name in tuple(os.environ):
        if name.startswith("RAG_"):
            monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def environment(tmp_path):
    settings = Settings(_env_file=None, runtime_dir=tmp_path / "runtime")
    engine = create_database(settings.sqlite_path)
    source = tmp_path / "input"
    source.mkdir()
    for filename, body, metadata in [
        ("camera.md", "# 相机\n\n" + "相机状态需要绑定观察者，退出页面时解除订阅。\n" * 12, {}),
        (
            "file.md",
            "# 文件导出\n\n文件保存前先脱敏，取消操作后清理临时文件。\n",
            {"source_key": "file"},
        ),
        (
            "plan.md",
            "# 相机规划\n\n相机未来自动打开系统悬浮窗，此能力尚未实现。\n",
            {"source_key": "future", "feature_status": "planned"},
        ),
    ]:
        (source / filename).write_text(
            markdown(body, external_processing_allowed=True, **metadata), encoding="utf-8"
        )
    prepared = prepare_documents(engine, "demo", source)
    embedder, vectors = FakeEmbedder(), FakeVectors()
    builder = IndexBuilder(settings, engine, embedder, vectors)
    yield settings, engine, source, prepared, embedder, vectors, builder
    engine.dispose()
