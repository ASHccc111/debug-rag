import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from debug_rag import budget
from debug_rag.budget import SHANGHAI, BudgetLedger
from debug_rag.errors import RagError
from debug_rag.retrieval.remote_embedding import VikingEmbedder
from debug_rag.storage.sqlite import ApiCall, create_database


@pytest.fixture
def remote(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "now_shanghai", lambda: datetime(2026, 11, 2, 12, tzinfo=SHANGHAI))
    settings = SimpleNamespace(
        allow_external_calls=True,
        viking_api_key=SecretStr("unit-test-placeholder"),
        viking_embedding_endpoint=(
            "https://api-vikingdb.vikingdb.cn-beijing.volces.com/api/vikingdb/embedding"
        ),
        viking_embedding_model="bge-m3",
        viking_embedding_version="default",
        viking_embedding_revision="test-config-1",
        viking_batch_size=2,
        viking_window_chars=1200,
        viking_timeout_seconds=3,
        viking_request_upper_bound_cny=Decimal("0.01"),
        viking_price_verified_on="2026-11-02",
        viking_price_valid_through="2026-11-03",
    )
    engine = create_database(tmp_path / "ledger.sqlite3")
    yield settings, BudgetLedger(engine, Decimal("50"))
    engine.dispose()


def response(count=1):
    return {
        "code": "Success",
        "request_id": "mock-request-1",
        "result": {
            "data": [
                {"dense": [3.0, 4.0] + [0.0] * 1022, "sparse": {"相机": 0.4, "17": 0.2}}
                for _ in range(count)
            ],
            "token_usage": {"bge-m3": {"prompt_tokens": 12}},
        },
    }


def test_identity_and_windows_have_no_io_and_keep_every_character(remote):
    settings, ledger = remote
    embedder = VikingEmbedder(settings, ledger, httpx.MockTransport(lambda _: pytest.fail("I/O")))
    identity = embedder.identity
    assert identity["dimension"] == 1024 and identity["provider"] == "viking"
    assert identity["revision"] == "test-config-1"
    assert identity["version"] == "default"
    text = "相机😀" * 900
    windows = embedder.windows(text)
    assert "".join(text[a:b] for a, b in windows) == text
    assert all(len(text[a:b].encode("utf-8")) + 16 <= 8192 for a, b in windows)
    assert not embedder.last_calls and ledger.summary()["recorded_calls"] == 0


def test_contract_batch_order_normalization_and_conservative_ledger(remote):
    settings, ledger = remote
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == settings.viking_embedding_endpoint
        assert request.headers["Authorization"] == "Bearer unit-test-placeholder"
        body = json.loads(request.content)
        assert body["dense_model"] == {"name": "bge-m3", "version": "default", "dim": 1024}
        assert body["sparse_model"] == {"name": "bge-m3", "version": "default"}
        value = response(len(body["data"]))
        for source, row in zip(body["data"], value["result"]["data"]):
            row["sparse"] = {source["text"]: 0.5}
        return httpx.Response(200, json=value)

    embedder = VikingEmbedder(settings, ledger, httpx.MockTransport(handler))
    rows = embedder.encode_hybrid(["相机", "悬浮窗", "导出"])
    assert [list(row["sparse"]) for row in rows] == [["相机"], ["悬浮窗"], ["导出"]]
    assert rows[0]["dense"][:2] == [0.6, 0.8]
    assert math.isclose(math.hypot(*rows[0]["dense"]), 1)
    assert len(requests) == len(embedder.last_calls) == 2
    assert ledger.summary()["unresolved_reserved_cny"] == "0.02"
    with Session(ledger.engine) as session:
        calls = list(session.scalars(select(ApiCall)))
        assert all(row.status == "unknown" and row.charged_units == 10000 for row in calls)
        assert all(row.prompt_tokens is None and row.served_model is None for row in calls)
    assert embedder.last_calls[0]["usage"] == {"bge-m3": {"prompt_tokens": 12}}
    assert embedder.last_calls[0]["usage_verified"] is False
    # Each invocation exposes only its own batches; query purpose is recorded.
    assert len(embedder.encode(["查询"], query=True)[0]) == 1024
    assert len(embedder.last_calls) == 1
    assert embedder.last_calls[0]["purpose"] == "embedding_query"


@pytest.mark.parametrize("kind", ["disabled", "key", "price", "expired", "budget", "oversized"])
def test_preflight_errors_never_send_requests(remote, kind):
    settings, ledger = remote
    if kind == "disabled":
        settings.allow_external_calls = False
    elif kind == "key":
        settings.viking_api_key = SecretStr("")
    elif kind == "price":
        settings.viking_request_upper_bound_cny = None
    elif kind == "expired":
        settings.viking_price_valid_through = "2026-11-01"
    elif kind == "budget":
        ledger = BudgetLedger(ledger.engine, Decimal("0.001"))
    embedder = VikingEmbedder(settings, ledger, httpx.MockTransport(lambda _: pytest.fail("I/O")))
    with pytest.raises(RagError):
        embedder.encode_hybrid(["长" * 1201 if kind == "oversized" else "相机"])
    assert not embedder.last_calls and ledger.summary()["recorded_calls"] == 0


@pytest.mark.parametrize(
    "kind",
    [
        "count",
        "dimension",
        "zero_dense",
        "nan_dense",
        "bool_dense",
        "empty_sparse",
        "zero_sparse",
        "negative_sparse",
        "bool_sparse",
        "envelope",
        "http",
        "json",
        "timeout",
    ],
)
def test_bad_responses_never_retry_or_leak_and_preserve_reservation(remote, kind):
    settings, ledger = remote
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("secret-provider-response", request=request)
        if kind in {"http", "json"}:
            return httpx.Response(429 if kind == "http" else 200, text="secret-provider-response")
        payload = response()
        row = payload["result"]["data"][0]
        if kind == "count":
            payload["result"]["data"] = []
        elif kind == "dimension":
            row["dense"] = [1.0]
        elif kind == "zero_dense":
            row["dense"] = [0.0] * 1024
        elif kind == "nan_dense":
            row["dense"][0] = float("nan")
        elif kind == "bool_dense":
            row["dense"][0] = True
        elif kind == "empty_sparse":
            row["sparse"] = {}
        elif kind in {"zero_sparse", "negative_sparse", "bool_sparse"}:
            row["sparse"] = {
                "token": {"zero_sparse": 0, "negative_sparse": -1, "bool_sparse": True}[kind]
            }
        elif kind == "envelope":
            payload["code"] = "Forbidden.secret-provider-response"
        # json.dumps permits NaN here intentionally to exercise finite-value validation.
        return httpx.Response(200, text=json.dumps(payload))

    embedder = VikingEmbedder(settings, ledger, httpx.MockTransport(handler))
    with pytest.raises(RagError) as caught:
        embedder.encode_hybrid(["正文不应泄露"])
    assert "secret" not in str(caught.value) and "正文" not in str(caught.value)
    assert len(calls) == 1 and ledger.summary()["unresolved_reserved_cny"] == "0.01"
    assert embedder.last_calls[0]["status"] == "failed"


def test_untrusted_usage_and_request_id_are_not_reflected_into_traces(remote):
    settings, ledger = remote
    payload = response()
    payload["request_id"] = "secret-provider-response\nuser-text"
    payload["result"]["token_usage"] = {
        "user-text": "secret-provider-response",
        "total_tokens": True,
    }
    embedder = VikingEmbedder(
        settings, ledger, httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    embedder.encode_hybrid(["相机"])
    assert embedder.last_calls[0]["usage"] is None
    assert "request_id" not in embedder.last_calls[0]
    assert "secret" not in json.dumps(embedder.last_calls)
    assert ledger.summary()["unresolved_reserved_cny"] == "0.01"


def test_later_batch_failure_keeps_earlier_call_accounted(remote):
    settings, ledger = remote
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 2:
            raise httpx.ConnectError("secret", request=request)
        return httpx.Response(200, json=response(2))

    embedder = VikingEmbedder(settings, ledger, httpx.MockTransport(handler))
    with pytest.raises(RagError):
        embedder.encode_hybrid(["相机", "悬浮窗", "导出"])
    assert [record["status"] for record in embedder.last_calls] == ["succeeded", "failed"]
    assert ledger.summary()["unresolved_reserved_cny"] == "0.02"


def test_concurrent_queries_do_not_share_call_traces(remote):
    settings, ledger = remote
    barrier = Barrier(2)

    def handler(_):
        barrier.wait(timeout=5)
        return httpx.Response(200, json=response())

    embedder = VikingEmbedder(settings, ledger, httpx.MockTransport(handler))

    def invoke(query):
        embedder.encode_hybrid(["相机"], query=query)
        return list(embedder.last_calls)

    with ThreadPoolExecutor(max_workers=2) as pool:
        traces = list(pool.map(invoke, [False, True]))
    assert [trace[0]["purpose"] for trace in traces] == ["embedding_documents", "embedding_query"]
    assert all(len(trace) == 1 and trace[0]["status"] == "succeeded" for trace in traces)
    assert traces[0][0]["call_id"] != traces[1][0]["call_id"]
    assert embedder.last_calls == []
    assert ledger.summary()["unresolved_reserved_cny"] == "0.02"
