"""Local binary uploads, durable parse attempts, and explicit batch preparation."""

import hashlib
import json
import threading
from pathlib import Path
from shutil import copytree
from uuid import uuid4

from filelock import FileLock, Timeout
from sqlalchemy import select
from sqlalchemy.orm import Session

from debug_rag.errors import RagError
from debug_rag.ingestion.documents import IngestError
from debug_rag.ingestion.readers import MAX_BINARY, ParseError, export_document, review_document
from debug_rag.ingestion.service import prepare_documents
from debug_rag.jobs import ACTIVE, RETRYABLE, now, utc_iso
from debug_rag.storage.sqlite import KnowledgeBase, ParseJob, PreparedHead


class ParseJobs:
    def __init__(self, settings, engine):
        self.engine = engine
        self.root = settings.runtime_dir / "parse-jobs"
        self.root.mkdir(parents=True, exist_ok=True)

    def _lock(self, name="worker"):
        return FileLock(self.root / f"{name}.lock", timeout=0, thread_local=False)

    @staticmethod
    def _public(row):
        return {
            "job_id": row.job_id,
            "kb_id": row.kb_id,
            "status": row.status,
            "error_code": row.error_code,
            "retryable": row.status in RETRYABLE,
            "request": {k: v for k, v in row.request_json.items() if k != "input_id"},
            "result": row.result_json,
            "created_at": utc_iso(row.created_at),
            "updated_at": utc_iso(row.updated_at),
        }

    def _row(self, session, job_id):
        row = session.get(ParseJob, job_id)
        if row is None:
            raise RagError("parse_job_not_found", "解析任务不存在。", 404)
        return row

    def get(self, job_id):
        with Session(self.engine) as session:
            return self._public(self._row(session, job_id))

    def list(self, kb_id):
        with Session(self.engine) as session:
            rows = session.scalars(
                select(ParseJob)
                .where(ParseJob.kb_id == kb_id)
                .order_by(ParseJob.created_at.desc(), ParseJob.job_id)
                .limit(50)
            )
            return [self._public(row) for row in rows]

    async def upload(self, kb_id, filename, metadata, stream):
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".docx"} or any(char in filename for char in "/\\\0"):
            raise RagError("unsupported_upload", "请选择 PDF 或 DOCX。", 422)
        job_id = uuid4().hex
        directory = self.root / job_id
        directory.mkdir()
        source = directory / f"input{suffix}"
        size, digest = 0, hashlib.sha256()
        try:
            with source.open("xb") as handle:
                async for part in stream:
                    size += len(part)
                    if size > MAX_BINARY:
                        raise RagError("binary_file_too_large", "原件超过 20 MiB。", 413)
                    digest.update(part)
                    handle.write(part)
            if not size:
                raise RagError("empty_upload", "上传内容为空。", 422)
            sidecar = source.with_suffix(".meta.json")
            sidecar.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            return self._submit(
                job_id,
                kb_id,
                {
                    "input_id": job_id,
                    "filename": filename,
                    "suffix": suffix,
                    "size": size,
                    "sha256": digest.hexdigest(),
                    "retry_of": None,
                },
            )
        except Exception:
            # Failed transport or busy worker has no persisted task to recover.
            with Session(self.engine) as session:
                persisted = session.get(ParseJob, job_id) is not None
            if not persisted:
                source.unlink(missing_ok=True)
                source.with_suffix(".meta.json").unlink(missing_ok=True)
                directory.rmdir()
            raise

    def _submit(self, job_id, kb_id, data):
        lock = self._lock()
        try:
            lock.acquire()
        except Timeout:
            raise RagError("parse_worker_busy", "已有解析任务运行中，请稍后提交。", 409) from None
        try:
            with Session(self.engine) as session, session.begin():
                row = ParseJob(
                    job_id=job_id,
                    kb_id=kb_id,
                    status="pending",
                    request_json=data,
                    created_at=now(),
                    updated_at=now(),
                )
                session.add(row)
                session.flush()
                result = self._public(row)
            threading.Thread(target=self._run, args=(job_id, data, lock), daemon=True).start()
        except BaseException:
            lock.release()
            raise
        return result

    def _update(self, job_id, status, *, error=None, result=None):
        with Session(self.engine) as session, session.begin():
            row = self._row(session, job_id)
            row.status, row.error_code, row.updated_at = status, error, now()
            if result is not None:
                row.result_json = result

    def _run(self, job_id, data, lock):
        try:
            self._update(job_id, "running")
            source = self._input(data)
            if hashlib.sha256(source.read_bytes()).hexdigest() != data["sha256"]:
                raise ParseError("original_digest_mismatch")
            result = export_document(source, self.root / job_id / "draft")
            self._update(
                job_id,
                "needs_review",
                result={
                    "warnings": result["warnings"],
                    "blocks": result["blocks"],
                },
            )
        except ParseError as exc:
            self._update(job_id, "failed", error=exc.code)
        except Exception:
            self._update(job_id, "failed", error="parse_failed")
        finally:
            lock.release()

    def _input(self, data):
        return self.root / data["input_id"] / ("input" + data["suffix"])

    def recover(self):
        try:
            with self._lock(), Session(self.engine) as session, session.begin():
                for row in session.scalars(select(ParseJob).where(ParseJob.status.in_(ACTIVE))):
                    row.status, row.error_code, row.updated_at = (
                        "interrupted",
                        "process_interrupted",
                        now(),
                    )
        except Timeout:
            pass

    def retry(self, job_id):
        with Session(self.engine) as session:
            row = self._row(session, job_id)
            if row.status not in RETRYABLE:
                raise RagError("parse_not_retryable", "仅失败或中断的解析任务可重试。", 409)
            return self._submit(uuid4().hex, row.kb_id, {**row.request_json, "retry_of": job_id})

    def _draft_path(self, job_id):
        paths = list((self.root / job_id / "draft").glob("*/document.md"))
        if len(paths) != 1:
            raise RagError("draft_unavailable", "解析草稿不可用。", 404)
        return paths[0]

    def draft(self, job_id):
        job = self.get(job_id)
        if job["status"] not in {"needs_review", "reviewed"}:
            raise RagError("draft_unavailable", "解析草稿尚未就绪。", 409)
        path = self._draft_path(job_id)
        manifest = json.loads(path.with_suffix(".origin.json").read_text(encoding="utf-8"))
        return {
            "text": path.read_text(encoding="utf-8"),
            "warnings": manifest["warnings"],
            "page_previews": [
                asset["file"].split("/")[-1]
                for asset in manifest["assets"]
                if asset["file"].startswith("assets/page-")
            ],
        }

    def original(self, job_id):
        with Session(self.engine) as session:
            data = self._row(session, job_id).request_json
            return self._input(data), data["filename"]

    def page(self, job_id, number):
        if (
            not 1 <= number <= 100
            or f"page-{number}.png" not in self.draft(job_id)["page_previews"]
        ):
            raise RagError("preview_not_found", "页面预览不存在。", 404)
        return self._draft_path(job_id).parent / "assets" / f"page-{number}.png"

    def review(self, job_id, accept_incomplete):
        try:
            with self._lock("review-" + self.get(job_id)["job_id"]):
                job = self.get(job_id)
                if job["status"] == "reviewed":
                    return job
                if job["status"] != "needs_review":
                    raise RagError("draft_unavailable", "草稿尚未就绪。", 409)
                review_document(self._draft_path(job_id), accept_incomplete=accept_incomplete)
                self._update(
                    job_id,
                    "reviewed",
                    result={
                        **job["result"],
                        "accepted_incomplete": accept_incomplete,
                    },
                )
                return self.get(job_id)
        except ParseError as exc:
            raise RagError(exc.code, "草稿未通过核对门禁。", 422) from None
        except Timeout:
            raise RagError("review_busy", "该草稿正在核对。", 409) from None

    def prepare(self, kb_id, job_ids, replace_existing):
        if len(set(job_ids)) != len(job_ids):
            raise RagError("duplicate_parse_job", "所选解析任务重复。", 422)
        with Session(self.engine) as session:
            kb = session.get(KnowledgeBase, kb_id)
            if not replace_existing and (
                (kb and kb.active_generation_id) or session.get(PreparedHead, kb_id)
            ):
                raise RagError("replace_confirmation_required", "请确认替换该库的完整资料集。", 409)
        for job_id in job_ids:
            job = self.get(job_id)
            if job["kb_id"] != kb_id or job["status"] != "reviewed":
                raise RagError("parse_job_not_reviewed", "仅可导入同库已核对草稿。", 409)
        batch = self.root / "batches" / uuid4().hex
        for job_id in job_ids:
            copytree(self._draft_path(job_id).parent, batch / job_id)
        try:
            return prepare_documents(self.engine, kb_id, batch, replace_existing=replace_existing)
        except IngestError as exc:
            if exc.issues[0].code == "replace_confirmation_required":
                raise RagError(
                    "replace_confirmation_required", "请确认替换该库的完整资料集。", 409
                ) from None
            raise RagError(exc.issues[0].code, "所选草稿未能组成完整资料集。", 422) from None
