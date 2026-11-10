"""Application factory; importing this module does not start models or connect to services."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from debug_rag import __version__
from debug_rag.components import components
from debug_rag.diagnostics import readiness
from debug_rag.errors import RagError
from debug_rag.jobs import JobManager
from debug_rag.parse_jobs import ParseJobs
from debug_rag.retrieval.indexing import snapshot
from debug_rag.settings import PROJECT_ROOT, Settings
from debug_rag.storage.sqlite import IndexGeneration, active_generation, create_database


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kb_id: str = Field(default="demo-debug", min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=300)
    allow_paid: bool = False


class EnhancedQuestion(Question):
    enhanced: bool = False


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kb_id: str = Field(default="demo-debug", min_length=1, max_length=100)


class ParseReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accept_incomplete: bool = False


class PrepareUpload(BuildRequest):
    job_ids: list[str] = Field(min_length=1, max_length=20)
    replace_existing: bool = False


def local_management(request: Request):
    """Reject DNS rebinding and other web origins before any maintenance mutation."""
    local = {"127.0.0.1", "localhost", "::1"}
    if request.client is None or request.client.host not in local:
        raise RagError("management_local_only", "知识库维护仅允许本机访问。", 403)
    if request.url.hostname not in local:
        raise RagError("management_host_invalid", "请通过本机地址打开维护页面。", 403)
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
            same = (parsed.scheme, parsed.netloc) == (request.url.scheme, request.url.netloc)
        except ValueError:
            same = False
        if not same:
            raise RagError("management_origin_invalid", "维护请求必须来自当前本机页面。", 403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise RagError("management_origin_invalid", "维护请求必须来自当前本机页面。", 403)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_database(config.sqlite_path)
        app.state.engine = engine
        app.state.builder, app.state.rag, app.state.ledger = components(config, engine)
        app.state.jobs = JobManager(config, engine, app.state.builder)
        app.state.recovered_jobs = app.state.jobs.recover()
        app.state.parse_jobs = ParseJobs(config, engine)
        app.state.parse_jobs.recover()
        try:
            yield
        finally:
            app.state.jobs.close()
            engine.dispose()

    app = FastAPI(title="Debug RAG", version=__version__, lifespan=lifespan)

    @app.exception_handler(RagError)
    async def rag_error(_: Request, exc: RagError):
        return JSONResponse(exc.public(), status_code=exc.status)

    @app.exception_handler(Exception)
    async def internal_error(_: Request, exc: Exception):
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "内部服务错误，请检查本机运行状态。"}},
            status_code=500,
        )

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(
            (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
        )

    @app.get("/health/live")
    def live():
        return {
            "alive": True,
            "stage": "P3-P4",
            "version": __version__,
            "project_root": str(PROJECT_ROOT),
        }

    @app.get("/health/ready")
    def ready():
        result = readiness(config, app.state.engine)
        return JSONResponse(result, status_code=200 if result["ready"] else 503)

    @app.get("/api/v1/status")
    def status(kb_id: str = Query(default=config.kb_id, min_length=1, max_length=100)):
        generation_id = active_generation(app.state.engine, kb_id)
        with Session(app.state.engine) as session:
            generation = session.get(IndexGeneration, generation_id) if generation_id else None
            manifest = generation.manifest if generation else {}
        return {
            "stage": "P3-P4",
            "kb_id": kb_id,
            "generation_id": generation_id,
            "index_published": bool(generation),
            "retrieval_profile": manifest.get("pipeline", {}).get("profile", "light"),
            "embedding_backend": config.embedding_backend,
            "maintenance_enabled": config.embedding_backend == "local",
            "recovered_job_count": len(app.state.recovered_jobs),
            "app_snapshot": manifest.get("app_snapshot"),
            "data_kind": manifest.get("data_kind"),
            "multi_turn_enabled": False,
            "parent_expansion_enabled": config.parent_expansion_enabled,
            "query_rewrite_enabled": config.query_rewrite_enabled,
            "rerank_enabled": config.rerank_enabled,
            "rerank_configured": bool(
                config.rerank_endpoint and config.rerank_api_key.get_secret_value()
            ),
            "external_calls_enabled": config.allow_external_calls,
            "generation_configured": bool(
                config.allow_external_calls and config.deepseek_api_key.get_secret_value()
            ),
            "budget": app.state.ledger.summary(),
        }

    @app.post("/api/v1/search")
    def search(question: Question, request: Request):
        if question.allow_paid:
            local_management(request)
        return app.state.rag.search(
            question.kb_id, question.question, allow_paid=question.allow_paid
        )

    @app.post("/api/v1/chat")
    def chat(question: EnhancedQuestion, request: Request):
        local_management(request)
        return app.state.rag.answer(
            question.kb_id,
            question.question,
            enhanced=question.enhanced,
            allow_paid=question.allow_paid,
        )

    @app.post("/api/v1/search/advanced")
    def advanced_search(question: Question, request: Request):
        if question.allow_paid or config.allow_external_calls:
            local_management(request)
        return app.state.rag.search(
            question.kb_id, question.question, enhanced=True, allow_paid=question.allow_paid
        )

    @app.post("/api/v1/context")
    def preview_context(question: EnhancedQuestion, request: Request):
        if question.allow_paid or (question.enhanced and config.allow_external_calls):
            local_management(request)
        return app.state.rag.prepare_context(
            question.kb_id,
            question.question,
            enhanced=question.enhanced,
            allow_paid=question.allow_paid,
        )

    @app.get("/api/v1/index-jobs")
    def jobs(kb_id: str = Query(default=config.kb_id, min_length=1, max_length=100)):
        return {"jobs": app.state.jobs.list(kb_id)}

    @app.get("/api/v1/parse-jobs")
    def parse_jobs(request: Request, kb_id: str = Query(min_length=1, max_length=100)):
        local_management(request)
        return {"jobs": app.state.parse_jobs.list(kb_id)}

    @app.post("/api/v1/parse-jobs", status_code=202)
    async def upload(
        request: Request,
        kb_id: str = Query(min_length=1, max_length=100),
        filename: str = Query(min_length=5, max_length=180),
        snapshot: str = Query(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$"),
        data_kind: Literal["simulated", "business"] = "simulated",
    ):
        from datetime import date
        from hashlib import sha256

        local_management(request)
        if request.headers.get("content-type") != "application/octet-stream":
            raise RagError("unsupported_upload_type", "请直接提交文档二进制。", 415)
        metadata = {
            "source_key": "upload-" + sha256(filename.casefold().encode()).hexdigest()[:32],
            "title": Path(filename).stem,
            "app_snapshot": snapshot,
            "data_kind": data_kind,
            "feature_status": "delivered",
            "updated_at": date.today().isoformat(),
            "external_processing_allowed": False,
        }
        return await app.state.parse_jobs.upload(kb_id, filename, metadata, request.stream())

    @app.get("/api/v1/parse-jobs/{job_id}")
    def parse_status(job_id: str, request: Request):
        local_management(request)
        return app.state.parse_jobs.get(job_id)

    @app.post("/api/v1/parse-jobs/{job_id}/retry", status_code=202)
    def retry_parse(job_id: str, request: Request):
        local_management(request)
        return app.state.parse_jobs.retry(job_id)

    @app.get("/api/v1/parse-jobs/{job_id}/draft")
    def parse_draft(job_id: str, request: Request):
        local_management(request)
        return app.state.parse_jobs.draft(job_id)

    @app.get("/api/v1/parse-jobs/{job_id}/original")
    def parse_original(job_id: str, request: Request):
        local_management(request)
        path, filename = app.state.parse_jobs.original(job_id)
        return FileResponse(path, filename=filename, media_type="application/octet-stream")

    @app.get("/api/v1/parse-jobs/{job_id}/pages/{number}")
    def parse_page(job_id: str, number: int, request: Request):
        local_management(request)
        return FileResponse(app.state.parse_jobs.page(job_id, number), media_type="image/png")

    @app.post("/api/v1/parse-jobs/{job_id}/review")
    def review_parse(job_id: str, body: ParseReview, request: Request):
        local_management(request)
        return app.state.parse_jobs.review(job_id, body.accept_incomplete)

    @app.post("/api/v1/parse-jobs/prepare")
    def prepare_uploads(body: PrepareUpload, request: Request):
        local_management(request)
        return app.state.parse_jobs.prepare(body.kb_id, body.job_ids, body.replace_existing)

    @app.get("/api/v1/index-jobs/{job_id}")
    def job(job_id: str):
        return app.state.jobs.get(job_id)

    @app.post("/api/v1/index-jobs", status_code=202)
    def build(body: BuildRequest, request: Request):
        local_management(request)
        submitted = app.state.jobs.submit(body.kb_id)
        app.state.jobs.start(submitted["job_id"])
        return submitted

    @app.post("/api/v1/index-jobs/{job_id}/retry", status_code=202)
    def retry(job_id: str, request: Request):
        local_management(request)
        original = app.state.jobs.get(job_id)
        submitted = app.state.jobs.submit(original["kb_id"], retry_of=job_id)
        app.state.jobs.start(submitted["job_id"])
        return submitted

    @app.get("/api/v1/sources/{generation_id}/{chunk_id}")
    def source(
        generation_id: str,
        chunk_id: str,
        kb_id: str = Query(default=config.kb_id, min_length=1, max_length=100),
    ):
        with Session(app.state.engine) as session:
            generation = session.get(IndexGeneration, generation_id)
            if generation is None or generation.kb_id != kb_id or generation.status != "ready":
                raise RagError("source_not_found", "引用原文不存在于此库的已发布快照。", 404)
        _, chunks = snapshot(app.state.engine, kb_id, generation_id, include_parents=True)
        row = next((c for c in chunks if c["chunk_id"] == chunk_id), None)
        if row is None:
            raise RagError("source_not_found", "引用原文不存在于此快照。", 404)
        return {"generation_id": generation_id, **row}

    return app


app = create_app()
