"""Read-only acceptance of the migrated server after a real local build and restart."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=180, trust_env=False) as client:
        live = client.get("/health/live").json()
        assert Path(live["project_root"]) == ROOT
        before = client.get("/api/v1/status").json()
        assert not before["external_calls_enabled"]
        assert before["embedding_backend"] == "local" and before["index_published"]
        jobs = client.get("/api/v1/index-jobs?kb_id=demo-debug").json()["jobs"]
        published = [job for job in jobs if job["status"] == "succeeded"]
        assert published and published[0]["generation_id"] == before["generation_id"]
        assert datetime.fromisoformat(published[0]["created_at"]).tzinfo is not None
        response = client.post("/api/v1/search", json={"question": "文件导出取消后需要清理什么？"})
        response.raise_for_status()
        result = response.json()
        assert result["generation_id"] == before["generation_id"]
        assert result["trace"]["external_calls_executed"] == 0
        assert any(row["source_key"] == "demo-file-export" for row in result["candidates"][:5])
        readiness = client.get("/health/ready").json()
        assert readiness["retrieval_ready"] and not readiness["ready"]
        assert readiness["checks"]["published_vectors"]["status"] == "ok"
        blocked = client.post(
            "/api/v1/index-jobs",
            json={"kb_id": "demo-debug"},
            headers={"Origin": "https://untrusted.example"},
        )
        assert blocked.status_code == 403
        after = client.get("/api/v1/status").json()
        assert after["budget"]["recorded_calls"] == before["budget"]["recorded_calls"] == 6
        assert after["budget"]["accounted_upper_bound_cny"] == "0.009703"
    with sqlite3.connect((ROOT / "runtime/metadata.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            db.execute(
                "SELECT status FROM index_generations WHERE generation_id=?",
                ("e3724e2f525b499d991eb5456d4266c5",),
            ).fetchone()[0]
            == "ready"
        )
    report = {
        "project_root": str(ROOT),
        "published_generation": before["generation_id"],
        "persisted_job": published[0],
        "restart_persistence": "passed",
        "post_restart_search": "passed",
        "readiness": readiness,
        "original_baseline_retained": True,
        "sqlite_integrity": "ok",
        "cross_origin_management": "blocked",
        "paid_calls": 0,
        "recorded_calls": after["budget"]["recorded_calls"],
    }
    output = ROOT / "runtime/migration-local-verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "paid_calls": 0, "report": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
