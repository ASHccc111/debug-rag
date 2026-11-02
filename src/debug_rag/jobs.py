"""Durable local index jobs. A process exit never turns a partial build into a publish."""

import hashlib
import threading
from datetime import datetime, timezone
from uuid import uuid4

from filelock import FileLock, Timeout
from sqlalchemy import select
from sqlalchemy.orm import Session

from debug_rag.errors import RagError
from debug_rag.storage.sqlite import IndexGeneration, IndexJob, KnowledgeBase, PreparedHead

ACTIVE = ("pending", "running")
RETRYABLE = ("failed", "interrupted")
ERROR_MESSAGES = {
    "process_interrupted": "上次服务在构建中退出；原已发布知识库保留，可重新构建。",
    "service_stopping": "服务停止前任务尚未执行，可重新构建。",
    "prepared_input_changed": "准备资料已发生变化，请检查最新导入结果后重新构建。",
    "index_build_busy": "同库已有构建正在执行，请稍后重试。",
    "index_build_failed": "构建未完成，请检查本机模型、Milvus 和运行日志后重试。",
}


def now():
    return datetime.now(timezone.utc)


def utc_iso(value):
    # SQLite returns naive datetimes even for DateTime(timezone=True).
    return (
        value.replace(tzinfo=timezone.utc).isoformat()
        if value.tzinfo is None
        else value.isoformat()
    )


class JobManager:
    def __init__(self, settings, engine, builder):
        self.settings, self.engine, self.builder = settings, engine, builder
        self._held = {}
        self._guard = threading.Lock()
        self._closed = False

    def _lock(self, kb_id, *, build=False):
        directory = self.settings.runtime_dir / "locks"
        directory.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(kb_id.encode()).hexdigest()
        return FileLock(
            directory / (name + (".lock" if build else ".job.lock")), timeout=0, thread_local=False
        )

    @staticmethod
    def _public(row):
        return {
            "job_id": row.job_id,
            "kb_id": row.kb_id,
            "status": row.status,
            "stage": row.stage,
            "generation_id": row.generation_id,
            "error_code": row.error_code,
            "error_message": (
                ERROR_MESSAGES.get(row.error_code, "构建未完成，请检查本机状态后重试。")
                if row.error_code
                else None
            ),
            "request": row.request_json,
            "result": row.result_json,
            "created_at": utc_iso(row.created_at),
            "updated_at": utc_iso(row.updated_at),
            "retryable": row.status in RETRYABLE,
        }

    def get(self, job_id):
        with Session(self.engine) as session:
            row = session.get(IndexJob, job_id)
            if row is None:
                raise RagError("index_job_not_found", "索引任务不存在。", 404)
            return self._public(row)

    def list(self, kb_id, limit=20):
        with Session(self.engine) as session:
            rows = session.scalars(
                select(IndexJob)
                .where(IndexJob.kb_id == kb_id)
                .order_by(IndexJob.created_at.desc())
                .limit(limit)
            )
            return [self._public(row) for row in rows]

    def submit(self, kb_id, retry_of=None):
        if self._closed:
            raise RagError("service_stopping", "服务正在停止，请重新启动后重试。", 503)
        # The management path must remain local even when external calls are enabled.
        if getattr(self.settings, "embedding_backend", "local") != "local":
            raise RagError(
                "paid_build_requires_cli", "远程索引请通过 CLI 显式确认费用后构建。", 409
            )
        lock = self._lock(kb_id)
        try:
            lock.acquire()
        except Timeout:
            raise RagError("index_build_busy", "该知识库已有索引维护任务。", 409) from None
        job_id = uuid4().hex
        try:
            with Session(self.engine) as session, session.begin():
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                if retry_of:
                    previous = session.get(IndexJob, retry_of)
                    if previous is None or previous.kb_id != kb_id:
                        raise RagError("index_job_not_found", "索引任务不存在。", 404)
                    if previous.status not in RETRYABLE:
                        raise RagError(
                            "index_job_not_retryable", "只有失败或中断任务可以重试。", 409
                        )
                if session.scalar(
                    select(IndexJob.job_id)
                    .where(IndexJob.kb_id == kb_id, IndexJob.status.in_(ACTIVE))
                    .limit(1)
                ):
                    raise RagError("index_build_busy", "该知识库已有索引维护任务。", 409)
                head = session.get(PreparedHead, kb_id)
                if head is None:
                    raise RagError("documents_not_prepared", "请先通过 CLI 导入完整资料。", 409)
                session.add(
                    IndexJob(
                        job_id=job_id,
                        kb_id=kb_id,
                        status="pending",
                        stage="queued",
                        generation_id=None,
                        error_code=None,
                        request_json={
                            "profile": "light",
                            "retry_of": retry_of,
                            "prepared_generation_id": head.generation_id,
                        },
                        result_json={},
                        created_at=now(),
                        updated_at=now(),
                    )
                )
            with self._guard:
                self._held[job_id] = lock
        except BaseException:
            lock.release()
            raise
        return self.get(job_id)

    def start(self, job_id):
        thread = threading.Thread(
            target=self.run, args=(job_id,), daemon=True, name="rag-index-" + job_id[:8]
        )
        thread.start()
        return thread

    def run(self, job_id):
        with self._guard:
            lock = self._held.pop(job_id, None)
        if lock is None:
            raise RagError("index_job_not_owned", "任务已被执行或不属于本进程。", 409)
        try:
            row = self.get(job_id)
            self._update(job_id, status="running", stage="preparing")

            def progress(stage, generation_id=None):
                values = {"stage": stage}
                if generation_id:
                    values["generation_id"] = generation_id
                self._update(job_id, **values)

            result = self.builder.build(
                row["kb_id"],
                progress=progress,
                expected_prepared_id=row["request"]["prepared_generation_id"],
            )
            self._update(
                job_id,
                status="succeeded",
                stage="published",
                generation_id=result["generation_id"],
                result_json=result,
            )
        except Exception as exc:
            # Publication and job acknowledgement use separate transactions. A successful
            # publish must not be relabeled failed if the acknowledgement was interrupted.
            with Session(self.engine) as session, session.begin():
                row = session.get(IndexJob, job_id)
                if not self._confirm_published(session, row):
                    row.status, row.stage = "failed", "failed"
                    row.error_code = exc.code if isinstance(exc, RagError) else "index_build_failed"
                    row.updated_at = now()
        finally:
            lock.release()

    def _update(self, job_id, **values):
        with Session(self.engine) as session, session.begin():
            row = session.get(IndexJob, job_id)
            for key, value in values.items():
                setattr(row, key, value)
            row.updated_at = now()

    @staticmethod
    def _confirm_published(session, row):
        generation = session.get(IndexGeneration, row.generation_id) if row.generation_id else None
        kb = session.get(KnowledgeBase, row.kb_id)
        if (
            generation is None
            or generation.kb_id != row.kb_id
            or generation.status != "ready"
            or kb is None
            or kb.active_generation_id != generation.generation_id
        ):
            return False
        manifest = generation.manifest
        row.status, row.stage, row.error_code = "succeeded", "published", None
        row.result_json = {
            "generation_id": generation.generation_id,
            "published": True,
            "recovered_after_publish": True,
            "source_chunks": manifest.get("chunk_counts", {}).get("child"),
            "vector_windows": manifest.get("representation_count"),
        }
        row.updated_at = now()
        return True

    def recover(self):
        """Only an unlocked job AND build can be orphaned; other processes may be active."""
        with Session(self.engine) as session:
            kb_ids = set(session.scalars(select(IndexJob.kb_id).where(IndexJob.status.in_(ACTIVE))))
            kb_ids.update(
                session.scalars(
                    select(IndexGeneration.kb_id).where(IndexGeneration.status == "building")
                )
            )
        recovered = []
        for kb_id in kb_ids:
            try:
                with self._lock(kb_id), self._lock(kb_id, build=True):
                    with Session(self.engine) as session, session.begin():
                        for row in session.scalars(
                            select(IndexJob).where(
                                IndexJob.kb_id == kb_id, IndexJob.status.in_(ACTIVE)
                            )
                        ):
                            if not self._confirm_published(session, row):
                                row.status, row.stage = "interrupted", "interrupted"
                                row.error_code, row.updated_at = "process_interrupted", now()
                            recovered.append(row.job_id)
                        for row in session.scalars(
                            select(IndexGeneration).where(
                                IndexGeneration.kb_id == kb_id, IndexGeneration.status == "building"
                            )
                        ):
                            row.status = "interrupted"
                            row.manifest = {**row.manifest, "failure_code": "process_interrupted"}
            except Timeout:
                continue
        return recovered

    def close(self):
        # Running daemon jobs are recovered after an actual process exit; shutdown is bounded.
        self._closed = True
        with self._guard:
            pending, self._held = self._held, {}
        for job_id, lock in pending.items():
            self._update(
                job_id, status="interrupted", stage="interrupted", error_code="service_stopping"
            )
            lock.release()
