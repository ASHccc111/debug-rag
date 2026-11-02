"""Explicitly authorized, bounded real-API smoke on the published simulated KB.

Does not read/print keys or rebuild an index. API calls use the application's ledger.
"""

import argparse
import json
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("文件导出取消了，临时文件和任务要咋处理？", "demo-file-export"),
    ("调试页相机状态卡片离开页面时怎么处理？", "demo-camera-card"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid", action="store_true", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    if args.base_url != "http://127.0.0.1:8001":
        parser.error("This smoke is restricted to the local application on port 8001")
    report = {
        "verified_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "scope": "two simulated real-API smoke cases; not a quality benchmark",
        "bge_m3_remote": "not_implemented_or_configured",
        "cases": [],
        "passed": False,
    }
    output = ROOT / "runtime" / "P2-live-api-verification.json"
    before = None
    try:
        with httpx.Client(base_url=args.base_url, timeout=180, trust_env=False) as client:
            state = client.get("/api/v1/status").raise_for_status().json()
            assert state["data_kind"] == "simulated" and state["index_published"]
            assert state["external_calls_enabled"] and state["generation_configured"]
            assert state["query_rewrite_enabled"] and state["rerank_enabled"]
            assert state["rerank_configured"]
            before = state["budget"]
            report["budget_before"] = before
            report["generation_id"] = state["generation_id"]
            assert Decimal(before["remaining_cny"]) >= Decimal("0.20")
            assert Decimal(before["unresolved_reserved_cny"]) == 0
            assert client.get("/health/ready").status_code == 200
            for question, expected in CASES:
                started = time.perf_counter()
                response = client.post(
                    "/api/v1/chat",
                    json={
                        "kb_id": "demo-debug",
                        "question": question,
                        "enhanced": True,
                    },
                )
                case = {
                    "question": question,
                    "http_status": response.status_code,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                }
                report["cases"].append(case)
                data = response.json()
                if response.status_code != 200:
                    case["error_code"] = data.get("error", {}).get("code", "unknown")
                    raise AssertionError("chat_endpoint_failed")
                # This response contains only simulated content, trace and safe usage metadata.
                case["result"] = data
                trace = data["trace"]
                assert data["generation_id"] == report["generation_id"], "generation_changed"
                assert trace["query_rewrite"]["status"] in {"applied", "unchanged"}, (
                    "rewrite_failed"
                )
                assert trace["rerank_applied"] and not trace["degraded"], "rerank_failed"
                assert trace["parent_expansion_applied"], "parent_expansion_not_applied"
                assert (
                    data.get("generation_validation") == "structure_passed_semantics_not_verified"
                )
                assert data["status"] in {"answered", "partial"} and data["statements"]
                assert any(c["source_key"] == expected for c in data["context"]), "source_missing"
                assert data["citations"], "citations_missing"
                for citation in data["citations"]:
                    path = f"/api/v1/sources/{data['generation_id']}/{citation['chunk_id']}"
                    source = client.get(path).raise_for_status().json()
                    assert source["text"] == citation["text"]
                    assert source["revision_id"] == citation["revision_id"]
                    assert client.get(path + "?kb_id=another-kb").status_code == 404
                case["source_citations_verified"] = True
                case["passed"] = True
                budget = client.get("/api/v1/status").raise_for_status().json()["budget"]
                assert Decimal(budget["unresolved_reserved_cny"]) == 0, "unresolved_charges"
                assert Decimal(budget["accounted_upper_bound_cny"]) - Decimal(
                    before["accounted_upper_bound_cny"]
                ) <= Decimal("0.20"), "smoke_cost_limit"
                print(
                    json.dumps(
                        {
                            "case_passed": question,
                            "calls": trace["external_calls_executed"],
                            "seconds": case["elapsed_seconds"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            report["passed"] = True
    except (AssertionError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        report["failure_type"] = type(exc).__name__
        # Only our own assertion labels are safe; never expose arbitrary HTTP exception text.
        if isinstance(exc, AssertionError) and exc.args:
            report["failure_check"] = str(exc.args[0])
    finally:
        try:
            with httpx.Client(base_url=args.base_url, timeout=10, trust_env=False) as client:
                after = client.get("/api/v1/status").raise_for_status().json()["budget"]
            report["budget_after"] = after
            if before:
                report["new_accounted_upper_bound_cny"] = str(
                    Decimal(after["accounted_upper_bound_cny"])
                    - Decimal(before["accounted_upper_bound_cny"])
                )
                report["new_recorded_calls"] = after["recorded_calls"] - before["recorded_calls"]
        except (httpx.HTTPError, ValueError, KeyError):
            report["budget_after_unavailable"] = True
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "cases": len(report["cases"]),
                "report": str(output),
                "cost_upper_bound_cny": report.get("new_accounted_upper_bound_cny"),
                "failure_check": report.get("failure_check"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
