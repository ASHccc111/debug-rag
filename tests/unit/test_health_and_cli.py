import json

from fastapi.testclient import TestClient

from debug_rag import cli, diagnostics
from debug_rag.diagnostics import Check
from debug_rag.main import create_app
from debug_rag.settings import Settings


def test_liveness_does_not_probe_database_or_paid_models(tmp_path, monkeypatch):
    def unexpected_probe(_):
        raise AssertionError("Liveness must not connect to Milvus")

    monkeypatch.setattr(diagnostics, "probe_milvus", unexpected_probe)
    with TestClient(create_app(Settings(_env_file=None, runtime_dir=tmp_path))) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["alive"] is True


def test_healthy_dependencies_are_not_a_ready_knowledge_base(tmp_path, monkeypatch):
    monkeypatch.setattr(
        diagnostics, "probe_milvus", lambda _: Check(status="ok", detail="test dependency")
    )
    with TestClient(create_app(Settings(_env_file=None, runtime_dir=tmp_path))) as client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["knowledge_base"]["status"] == "not_initialized"
    assert response.json()["ready"] is False


def test_doctor_returns_failure_when_milvus_is_down(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None, runtime_dir=tmp_path))
    monkeypatch.setattr(
        diagnostics, "probe_milvus", lambda _: Check(status="error", detail="not available")
    )
    assert cli.main(["doctor"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["external_calls_executed"] == 0
    assert result["foundation_ready"] is False


def test_doctor_distinguishes_foundation_from_answer_readiness(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None, runtime_dir=tmp_path))
    monkeypatch.setattr(
        diagnostics, "probe_milvus", lambda _: Check(status="ok", detail="test dependency")
    )
    assert cli.main(["doctor"]) == 0
    assert json.loads(capsys.readouterr().out)["ready"] is False
    assert cli.main(["doctor", "--require-ready"]) == 1


def test_config_failure_does_not_print_sensitive_input(monkeypatch, capsys):
    monkeypatch.setenv("RAG_MILVUS_URI", "http://private-user:private-password@host:19530")
    assert cli.main(["doctor"]) == 2
    output = capsys.readouterr().err
    assert "invalid_configuration" in output
    assert "private-password" not in output


def test_probe_does_not_disclose_sdk_exception_secrets(monkeypatch):
    def fail(_):
        raise RuntimeError("private-test-secret")

    monkeypatch.setattr(diagnostics, "new_milvus_client", fail)
    check = diagnostics.probe_milvus(Settings(_env_file=None))
    assert check.status == "error"
    assert "private-test-secret" not in check.detail
