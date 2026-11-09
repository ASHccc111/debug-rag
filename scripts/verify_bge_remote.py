"""Explicit paid Viking probe. Only independent simulation text may leave the machine."""

import argparse
import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from debug_rag.budget import BudgetLedger
from debug_rag.errors import RagError
from debug_rag.ingestion.documents import load_source
from debug_rag.ingestion.service import prepare_documents
from debug_rag.retrieval.indexing import IndexBuilder
from debug_rag.retrieval.remote_embedding import VikingEmbedder
from debug_rag.retrieval.service import RagService
from debug_rag.settings import Settings
from debug_rag.storage.milvus import MilvusVectors
from debug_rag.storage.sqlite import create_database

ROOT = Path(__file__).resolve().parents[1]
PRICING_SOURCE = (
    "https://docs.volcengine.com/docs/vector-database-vikingdb/billing-of-a-vector-database?lang=en"
)


def validate_retrieval(result):
    route_counts = {name: len(result["trace"].get(name, [])) for name in ("dense", "sparse")}
    sources = [row["source_key"] for row in result["context"]]
    if not all(route_counts.values()) or "demo-file-export" not in sources:
        raise RagError(
            "hybrid_verification_failed", "两路召回均须有结果，且须命中预期模拟资料。", 409
        )
    return {
        "generation_id": result["generation_id"],
        "trace": result["trace"],
        "sources": sources,
        "route_counts": route_counts,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument(
        "--build", action="store_true", help="Also build/search an isolated simulation KB"
    )
    args = parser.parse_args(argv)
    if not args.allow_paid:
        print(json.dumps({"error": "explicit_paid_authorization_required"}))
        return 2
    # Dedicated probe settings: do not enable generation/rewrite/rerank in .env.
    try:
        settings = Settings().model_copy(
            update={
                "embedding_backend": "viking",
                "allow_external_calls": True,
                "query_rewrite_enabled": False,
                "rerank_enabled": False,
                "viking_batch_size": 4,
                "viking_window_chars": 1200,
                "viking_request_upper_bound_cny": Decimal("0.04"),
                "viking_price_verified_on": date(2026, 11, 3),
                "viking_price_valid_through": date(2026, 11, 10),
            }
        )
    except (ValidationError, OSError):
        print(json.dumps({"error": "invalid_local_configuration"}))
        return 2
    engine = create_database(settings.sqlite_path)
    ledger = BudgetLedger(engine, settings.monthly_budget_cny)
    embedder = VikingEmbedder(settings, ledger)
    report = {
        "scope": "independent simulation; no company data; no generation or reranking",
        "pricing_source": PRICING_SOURCE,
        "reservation_per_request_cny": "0.04",
        "budget_before": ledger.summary(),
    }
    started = time.perf_counter()
    try:
        fixture_dir = ROOT / "fixtures/documents"
        if args.build:
            documents = load_source(fixture_dir)
            if any(
                d.metadata.data_kind != "simulated" or not d.metadata.external_processing_allowed
                for d in documents
            ):
                raise RagError("simulation_only", "验收只允许可外发的独立模拟资料。", 403)
        rows = embedder.encode_hybrid(
            [
                "模拟规范：相机状态卡片退出页面时解除状态订阅。",
                "模拟规范：文件导出取消后清理临时副本。",
                "模拟问题：文件导出取消后如何处理？",
            ]
        )
        report.update(
            protocol_passed=True,
            dense_dimensions=[len(row["dense"]) for row in rows],
            sparse_nonzero_counts=[len(row["sparse"]) for row in rows],
            probe_calls=embedder.last_calls,
        )
        if args.build:
            kb = "demo-bge-m3-validation"
            prepare_documents(engine, kb, fixture_dir)
            vectors = MilvusVectors(settings)
            report["index"] = IndexBuilder(settings, engine, embedder, vectors).build(kb)
            result = RagService(settings, engine, embedder, vectors, None).prepare_context(
                kb, "文件导出取消后需要清理什么？", allow_paid=True
            )
            report["retrieval"] = validate_retrieval(result)
        report["passed"] = True
    except RagError as exc:
        report.update(passed=False, error=exc.public(), last_calls=embedder.last_calls)
    except Exception as exc:
        report.update(passed=False, error_type=type(exc).__name__)
    finally:
        report.update(
            elapsed_seconds=round(time.perf_counter() - started, 3), budget_after=ledger.summary()
        )
        output = settings.runtime_dir / f"BGE-M3-live-{time.time_ns()}.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        engine.dispose()
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "report": str(output),
                "error": report.get("error"),
                "budget_after": report["budget_after"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
