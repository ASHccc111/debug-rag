import hashlib
import threading
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from filelock import FileLock
from sqlalchemy.orm import Session

from debug_rag.errors import RagError
from debug_rag.jobs import JobManager
from debug_rag.main import create_app
from debug_rag.storage.sqlite import IndexGeneration, IndexJob, active_generation


class Builder:
    def build(self, kb_id, progress=None, expected_prepared_id=None):
        progress("encoding", "test-generation")
        return {"generation_id": "test-generation", "published": True}


def add_orphan(engine, kb_id="demo", job_id="orphan"):
    with Session(engine) as session, session.begin():
        session.add(
            IndexJob(
                job_id=job_id,
                kb_id=kb_id,
                status="running",
                stage="encoding",
                request_json={"profile": "light"},
                result_json={},
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            IndexGeneration(
                generation_id="orphan-generation", kb_id=kb_id, status="building", manifest={}
            )
        )


def test_jobs_persist_result_and_reject_duplicate_or_success_retry(environment):
    settings, engine, *_ = environment
    manager = JobManager(settings, engine, Builder())
    job = manager.submit("demo")
    assert job["status"] == "pending"
    assert job["created_at"].endswith("+00:00")
    assert job["updated_at"].endswith("+00:00")
    with pytest.raises(RagError, match="已有"):
        JobManager(settings, engine, Builder()).submit("demo")
    manager.run(job["job_id"])
    result = JobManager(settings, engine, Builder()).get(job["job_id"])
    assert result["status"] == "succeeded"
    assert result["generation_id"] == "test-generation"
    assert result["stage"] == "published"
    with pytest.raises(RagError) as caught:
        manager.submit("demo", retry_of=job["job_id"])
    assert caught.value.code == "index_job_not_retryable"


def test_recover_orphan_job_and_generation_preserves_published_pointer(environment):
    settings, engine, _, _, _, _, builder = environment
    published = builder.build("demo")
    add_orphan(engine)
    manager = JobManager(settings, engine, builder)
    assert manager.recover() == ["orphan"]
    assert manager.get("orphan")["status"] == "interrupted"
    with Session(engine) as session:
        assert session.get(IndexGeneration, "orphan-generation").status == "interrupted"
    assert active_generation(engine, "demo") == published["generation_id"]
    retry = manager.submit("demo", retry_of="orphan")
    manager.run(retry["job_id"])
    assert manager.get(retry["job_id"])["status"] == "succeeded"
    assert manager.get("orphan")["status"] == "interrupted"


@pytest.mark.parametrize("kind", ["job", "build"])
def test_recovery_does_not_interrupt_live_other_process_lock(environment, kind):
    settings, engine, *_ = environment
    add_orphan(engine)
    manager = JobManager(settings, engine, Builder())
    name = hashlib.sha256(b"demo").hexdigest() + (".job.lock" if kind == "job" else ".lock")
    directory = settings.runtime_dir / "locks"
    directory.mkdir(exist_ok=True)
    with FileLock(directory / name, timeout=0):
        assert manager.recover() == []
        assert manager.get("orphan")["status"] == "running"
    assert manager.recover() == ["orphan"]


def test_live_queued_task_is_not_mistaken_for_interrupted_and_close_is_retryable(environment):
    settings, engine, *_ = environment
    manager = JobManager(settings, engine, Builder())
    job = manager.submit("demo")
    assert JobManager(settings, engine, Builder()).recover() == []
    manager.close()
    assert manager.get(job["job_id"])["status"] == "interrupted"
    assert manager.get(job["job_id"])["retryable"]


def test_failed_job_keeps_old_generation_and_never_exposes_exception_details(environment):
    settings, engine, _, _, _, vectors, builder = environment
    published = builder.build("demo")
    vectors.fail_validation = True
    manager = JobManager(settings, engine, builder)
    job = manager.submit("demo")
    manager.run(job["job_id"])
    result = manager.get(job["job_id"])
    assert result["status"] == "failed"
    assert result["error_code"] == "index_build_failed"
    assert "injected vector" not in str(result)
    assert active_generation(engine, "demo") == published["generation_id"]


def test_background_job_saves_pending_before_work_and_can_be_polled(environment):
    settings, engine, *_ = environment
    entered, release = threading.Event(), threading.Event()

    def build(kb_id, progress, expected_prepared_id):
        entered.set()
        assert release.wait(5)
        return {"generation_id": "done"}

    manager = JobManager(settings, engine, SimpleNamespace(build=build))
    job = manager.submit("demo")
    worker = manager.start(job["job_id"])
    try:
        assert entered.wait(5)
        assert manager.get(job["job_id"])["status"] == "running"
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert manager.get(job["job_id"])["status"] == "succeeded"


def test_recovery_confirms_published_job_if_process_died_before_acknowledgement(environment):
    settings, engine, _, _, _, _, builder = environment
    published = builder.build("demo")
    add_orphan(engine)
    with Session(engine) as session, session.begin():
        session.get(IndexJob, "orphan").generation_id = published["generation_id"]
    manager = JobManager(settings, engine, builder)
    manager.recover()
    recovered = manager.get("orphan")
    assert recovered["status"] == "succeeded"
    assert recovered["result"]["recovered_after_publish"]
    assert not recovered["retryable"]


def test_acknowledgement_failure_does_not_relabel_successful_publish_failed(
    environment, monkeypatch
):
    settings, engine, _, _, _, _, builder = environment
    manager = JobManager(settings, engine, builder)
    original = manager._update

    def fail_ack(job_id, **values):
        if values.get("status") == "succeeded":
            raise RuntimeError("injected acknowledgement loss")
        original(job_id, **values)

    monkeypatch.setattr(manager, "_update", fail_ack)
    job = manager.submit("demo")
    manager.run(job["job_id"])
    assert manager.get(job["job_id"])["status"] == "succeeded"
    assert manager.get(job["job_id"])["result"]["recovered_after_publish"]


def test_missing_input_rejected_before_creating_job(environment):
    settings, engine, *_ = environment
    manager = JobManager(settings, engine, Builder())
    with pytest.raises(RagError) as caught:
        manager.submit("missing")
    assert caught.value.code == "documents_not_prepared"
    assert manager.list("missing") == []


def test_prepared_input_is_locked_when_job_is_submitted(environment):
    settings, engine, source, _, _, _, builder = environment
    from debug_rag.ingestion.service import prepare_documents

    manager = JobManager(settings, engine, builder)
    job = manager.submit("demo")
    path = source / "file.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n新条件。", encoding="utf-8")
    prepare_documents(engine, "demo", source)
    manager.run(job["job_id"])
    assert manager.get(job["job_id"])["error_code"] == "prepared_input_changed"


def test_remote_backend_cannot_be_built_by_local_management(environment):
    settings, engine, *_ = environment
    settings = settings.model_copy(update={"embedding_backend": "viking"})
    with pytest.raises(RagError) as caught:
        JobManager(settings, engine, Builder()).submit("demo")
    assert caught.value.code == "paid_build_requires_cli"


def test_management_api_rejects_foreign_origin_host_and_nonlocal_client(environment):
    settings, *_ = environment
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:8001", client=("127.0.0.1", 50000)
    ) as client:
        client.app.state.jobs.start = lambda _: None
        for headers in (
            {"Origin": "https://evil.example"},
            {"Host": "evil.example"},
            {"Sec-Fetch-Site": "cross-site"},
        ):
            response = client.post("/api/v1/index-jobs", json={"kb_id": "demo"}, headers=headers)
            assert response.status_code == 403
        submitted = client.post(
            "/api/v1/index-jobs",
            json={"kb_id": "demo"},
            headers={"Origin": "http://127.0.0.1:8001"},
        )
        assert submitted.status_code == 202
        job = submitted.json()
        assert client.get("/api/v1/index-jobs/" + job["job_id"]).json()["status"] == "pending"
        assert (
            client.get("/api/v1/index-jobs?kb_id=demo").json()["jobs"][0]["job_id"] == job["job_id"]
        )
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:8001", client=("192.0.2.10", 50000)
    ) as client:
        assert client.post("/api/v1/index-jobs", json={"kb_id": "demo"}).status_code == 403


def test_paid_endpoints_reject_foreign_origins_before_any_model_calls(environment):
    settings, *_ = environment
    settings = settings.model_copy(update={"allow_external_calls": True})
    with TestClient(
        create_app(settings), base_url="http://127.0.0.1:8001", client=("127.0.0.1", 50000)
    ) as client:
        for path, extra in [
            ("chat", {}),
            ("search", {"allow_paid": True}),
            ("search/advanced", {}),
            ("context", {"enhanced": True}),
        ]:
            result = client.post(
                "/api/v1/" + path,
                json={"kb_id": "demo", "question": "相机", **extra},
                headers={"Origin": "https://evil.example"},
            )
            assert result.status_code == 403
            assert result.json()["error"]["code"] == "management_origin_invalid"
        assert client.app.state.ledger.summary()["recorded_calls"] == 0
