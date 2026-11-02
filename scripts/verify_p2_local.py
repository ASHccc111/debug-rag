"""Read-only HTTP acceptance of an already-published local simulated KB. No paid APIs."""

import json
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8001"
ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("相机状态中的 phase 和 permission 有什么区别？", "demo-camera-state"),
    ("文件导出取消后需要清理什么？", "demo-file-export"),
    ("应用内悬浮层进入后台时如何处理？", "demo-app-overlay"),
    ("调试页相机状态卡片离开页面时怎么处理？", "demo-camera-card"),
]


def main():
    results = []
    with httpx.Client(base_url=BASE, timeout=180, trust_env=False) as client:
        before = client.get("/api/v1/status").json()
        assert before["index_published"] and before["data_kind"] == "simulated"
        assert before["external_calls_enabled"] is False, (
            "This verification requires paid calls OFF"
        )
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        for question, expected in CASES:
            response = client.post(
                "/api/v1/search", json={"kb_id": "demo-debug", "question": question}
            )
            response.raise_for_status()
            result = response.json()
            top = result["candidates"][:5]
            assert top and all(c["metadata"]["feature_status"] == "delivered" for c in top)
            assert any(c["source_key"] == expected for c in top), (
                question,
                "expected source absent",
            )
            first = top[0]
            path = f"/api/v1/sources/{result['generation_id']}/{first['chunk_id']}"
            source = client.get(path).json()
            assert source["text"] == first["text"]
            assert client.get(path + "?kb_id=another-kb").status_code == 404
            results.append(
                {
                    "question": question,
                    "expected_source": expected,
                    "expected_source_in_top5": True,
                    "generation_id": result["generation_id"],
                    "top5": [
                        {
                            k: c[k]
                            for k in (
                                "source_key",
                                "chunk_id",
                                "revision_id",
                                "section_path",
                                "start_line",
                                "end_line",
                                "rrf_score",
                            )
                        }
                        for c in top
                    ],
                    "trace": result["trace"],
                }
            )
        disabled = client.post("/api/v1/chat", json={"question": CASES[0][0]})
        assert disabled.status_code == 503
        assert disabled.json()["error"]["code"] == "external_calls_disabled"
        after = client.get("/api/v1/status").json()
        assert after["budget"]["recorded_calls"] == before["budget"]["recorded_calls"]
    report = {
        "scope": "4 deterministic simulated retrieval smoke cases; not a quality benchmark",
        "base_url": BASE,
        "results": results,
        "budget": after["budget"],
        "disabled_chat_error": disabled.json(),
        "paid_calls_in_verification": 0,
    }
    output = ROOT / "runtime" / "P2-local-verification.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"passed_cases": len(results), "paid_calls": 0, "report": str(output)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
