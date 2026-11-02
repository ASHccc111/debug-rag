"""Explicit local/hybrid commands; remote indexing and search require --allow-paid."""

import argparse
import json
import sys
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from debug_rag.budget import BudgetLedger
from debug_rag.components import components
from debug_rag.diagnostics import milvus_smoke, model_smoke, readiness
from debug_rag.errors import RagError
from debug_rag.ingestion.chunking import ChunkConfig
from debug_rag.ingestion.documents import IngestError
from debug_rag.ingestion.service import inspect_generation, prepare_documents
from debug_rag.retrieval.indexing import activate_generation
from debug_rag.settings import Settings
from debug_rag.storage.milvus import MilvusVectors
from debug_rag.storage.sqlite import IndexGeneration, KnowledgeBase, create_database


def package_versions() -> dict:
    result = {}
    for name in ["debug-rag", "fastapi", "pydantic", "sqlalchemy", "pymilvus", "torch"]:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "not installed"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Check local foundation without paid calls")
    doctor.add_argument("--profile", choices=["light"], default="light")
    doctor.add_argument("--milvus-smoke", action="store_true", help="Use a disposable collection")
    doctor.add_argument("--require-ready", action="store_true", help="Also require a published RAG")
    commands.add_parser("init-db", help="Create metadata tables without clearing any records")
    smoke = commands.add_parser("model-smoke", help="CPU encoding using existing local files")
    smoke.add_argument("--path", type=Path, required=True)
    ingest = commands.add_parser("ingest", help="Prepare a complete local document batch (P1)")
    ingest.add_argument("--kb", required=True)
    ingest.add_argument("--source", type=Path, required=True)
    ingest.add_argument("--profile", choices=["light"], default="light")
    ingest.add_argument("--parent-chars", type=int, default=1600)
    ingest.add_argument("--child-chars", type=int, default=600)
    ingest.add_argument(
        "--publish", action="store_true", help="Build, verify and publish local indexes"
    )
    ingest.add_argument("--backend", choices=["local", "viking"])
    ingest.add_argument("--allow-paid", action="store_true")
    inspect = commands.add_parser("inspect", help="Inspect a prepared generation and its sources")
    inspect.add_argument("--kb", required=True)
    inspect.add_argument("--generation")
    inspect.add_argument("--chunks", action="store_true", help="Include original chunk text")
    build = commands.add_parser("build-index", help="Build and publish from the prepared input")
    build.add_argument("--kb", required=True)
    build.add_argument("--backend", choices=["local", "viking"])
    build.add_argument("--allow-paid", action="store_true")
    indexes = commands.add_parser("indexes", help="List immutable generations and active pointer")
    indexes.add_argument("--kb", required=True)
    activate = commands.add_parser("activate-index", help="Validate and activate a retained index")
    activate.add_argument("--kb", required=True)
    activate.add_argument("--generation", required=True)
    for name in ("search", "context", "ask"):
        command = commands.add_parser(
            name,
            help={
                "search": "Local search",
                "context": "Preview local evidence expansion",
                "ask": "Generate with citations",
            }[name],
        )
        command.add_argument("--kb", required=True)
        command.add_argument("--question", required=True)
        command.add_argument("--backend", choices=["local", "viking"])
        command.add_argument("--allow-paid", action="store_true")
        command.add_argument(
            "--enhanced",
            action="store_true",
            help="Opt into configured remote rewrite/rerank; may incur costs",
        )
    commands.add_parser("budget", help="Read the local project-wide usage ledger")
    args = parser.parse_args(argv)
    engine = None
    try:
        settings = Settings()
        if getattr(args, "backend", None):
            settings.embedding_backend = args.backend
        needs_encoding = args.command in {"build-index", "search", "context", "ask"} or (
            args.command == "ingest" and args.publish
        )
        if needs_encoding and settings.embedding_backend == "viking" and not args.allow_paid:
            raise RagError(
                "remote_embedding_opt_in_required", "远程编码需要显式 --allow-paid。", 409
            )
        if args.command == "model-smoke":
            result = model_smoke(args.path)
            exit_code = 0
        else:
            engine = create_database(settings.sqlite_path)
            if args.command == "init-db":
                result = {"initialized": True, "database": str(settings.sqlite_path)}
                exit_code = 0
            elif args.command == "ingest":
                config = ChunkConfig(parent_chars=args.parent_chars, child_chars=args.child_chars)
                result = prepare_documents(engine, args.kb, args.source, config)
                if args.publish:
                    builder, _, _ = components(settings, engine)
                    result["index"] = builder.build(args.kb)
                exit_code = 0
            elif args.command == "inspect":
                result = inspect_generation(engine, args.kb, args.generation, args.chunks)
                exit_code = 0
            elif args.command == "build-index":
                builder, _, _ = components(settings, engine)
                result = builder.build(args.kb)
                exit_code = 0
            elif args.command == "indexes":
                with Session(engine) as session:
                    kb = session.get(KnowledgeBase, args.kb)
                    result = {
                        "kb_id": args.kb,
                        "active_generation_id": kb.active_generation_id if kb else None,
                        "generations": [
                            {
                                "generation_id": row.generation_id,
                                "status": row.status,
                                "profile": row.manifest.get("pipeline", {}).get("profile"),
                                "created_at": row.created_at.isoformat(),
                            }
                            for row in session.scalars(
                                select(IndexGeneration)
                                .where(IndexGeneration.kb_id == args.kb)
                                .order_by(IndexGeneration.created_at.desc())
                            )
                        ],
                    }
                exit_code = 0
            elif args.command == "activate-index":
                result = activate_generation(
                    settings, engine, MilvusVectors(settings), args.kb, args.generation
                )
                exit_code = 0
            elif args.command in {"search", "context", "ask"}:
                _, service, _ = components(settings, engine)
                action = {
                    "search": service.search,
                    "context": service.prepare_context,
                    "ask": service.answer,
                }[args.command]
                result = action(
                    args.kb, args.question, enhanced=args.enhanced, allow_paid=args.allow_paid
                )
                exit_code = 0
            elif args.command == "budget":
                result = BudgetLedger(engine, settings.monthly_budget_cny).summary()
                exit_code = 0
            else:
                result = readiness(settings, engine)
                result["foundation_ready"] = all(
                    result["checks"][name]["status"] == "ok" for name in ["sqlite", "milvus"]
                )
                result["versions"] = package_versions()
                result["external_calls_executed"] = 0
                result["monthly_budget_cny"] = str(settings.monthly_budget_cny)
                if args.milvus_smoke:
                    if not result["foundation_ready"]:
                        raise RuntimeError("Milvus foundation is not ready for the smoke test")
                    result["milvus_smoke"] = milvus_smoke(settings)
                exit_code = 0 if result["foundation_ready"] else 1
                if args.require_ready and not result["ready"]:
                    exit_code = 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code
    except RagError as exc:
        print(json.dumps(exc.public(), ensure_ascii=False), file=sys.stderr)
        return 1
    except IngestError as exc:
        print(
            json.dumps(
                {"error": "document_preparation_failed", "issues": [asdict(i) for i in exc.issues]},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    except ValidationError as exc:
        errors = [".".join(str(part) for part in item["loc"]) for item in exc.errors()]
        print(json.dumps({"error": "invalid_configuration", "fields": errors}), file=sys.stderr)
        return 2
    except Exception as exc:
        # Avoid printing arbitrary SDK/config exception text containing credentials.
        print(json.dumps({"error": "command_failed", "type": type(exc).__name__}), file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
