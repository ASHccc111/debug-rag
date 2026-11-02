import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from debug_rag import budget
from debug_rag.budget import SHANGHAI, BudgetLedger
from debug_rag.errors import RagError
from debug_rag.generation.provider import DeepSeekGenerator
from debug_rag.settings import Settings
from debug_rag.storage.sqlite import ApiCall, create_database


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    # Freeze this fixture's price window independently of production price refreshes.
    monkeypatch.setitem(budget.PRICING, "verified_on", "2026-10-26")
    monkeypatch.setitem(budget.PRICING, "valid_through", "2026-11-02")
    monkeypatch.setattr(budget, "now_shanghai", lambda: datetime(2026, 10, 26, 15, tzinfo=SHANGHAI))
    engine = create_database(tmp_path / "metadata.sqlite3")
    yield BudgetLedger(engine, Decimal("50"))
    engine.dispose()


def settings(tmp_path, **changes):
    return Settings(
        _env_file=None,
        runtime_dir=tmp_path,
        allow_external_calls=True,
        deepseek_api_key="unit-test-not-a-real-key",
        **changes,
    )


def test_budget_reservation_is_atomic_across_concurrent_calls(ledger):
    tight = BudgetLedger(ledger.engine, Decimal("0.03"))

    def reserve(_):
        try:
            return tight.reserve("deepseek-flash", "answer", 6000, 1500)
        except RagError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert results.count("monthly_budget_exceeded") == 1
    assert tight.summary()["recorded_calls"] == 1
    assert Decimal(tight.summary()["accounted_upper_bound_cny"]) == Decimal("0.024")


def test_known_usage_settles_unknown_is_retained_and_carried_to_next_month(ledger, monkeypatch):
    first = ledger.reserve("deepseek-flash", "answer", 6000, 1500)
    ledger.settle(
        first, {"prompt_tokens": 100, "completion_tokens": 50}, "actual-model-version", 6000, 1500
    )
    second = ledger.reserve("deepseek-flash", "citation_repair", 6000, 1500)
    ledger.unknown(second)
    assert Decimal(ledger.summary()["accounted_upper_bound_cny"]) == Decimal("0.0246")
    monkeypatch.setattr(budget, "now_shanghai", lambda: datetime(2026, 11, 1, tzinfo=SHANGHAI))
    assert Decimal(ledger.summary()["accounted_upper_bound_cny"]) == Decimal("0.024")
    assert ledger.summary()["month"] == "2026-11"
    restarted = BudgetLedger(ledger.engine, Decimal("50"))
    assert restarted.summary()["unresolved_reserved_cny"] == "0.024"


def test_invalid_usage_and_overrun_never_become_free_calls(ledger):
    call = ledger.reserve("deepseek-flash", "answer", 6000, 1500)
    ledger.settle(call, {"prompt_tokens": True, "completion_tokens": 1}, None, 6000, 1500)
    assert ledger.summary()["unresolved_reserved_cny"] == "0.024"
    second = ledger.reserve("deepseek-flash", "answer", 6000, 1500)
    with pytest.raises(RagError) as caught:
        ledger.settle(
            second, {"prompt_tokens": 7000, "completion_tokens": 10}, "actual", 6000, 1500
        )
    assert caught.value.code == "provider_usage_out_of_bounds"
    with pytest.raises(RagError) as caught:
        ledger.reserve("deepseek-flash", "answer", 6000, 1500)
    assert caught.value.code == "budget_needs_review"


def test_expired_pricing_and_month_boundary_block_before_call(ledger, monkeypatch):
    monkeypatch.setattr(budget, "now_shanghai", lambda: datetime(2026, 11, 3, tzinfo=SHANGHAI))
    with pytest.raises(RagError) as caught:
        ledger.reserve("deepseek-flash", "answer", 6000, 1500)
    assert caught.value.code == "pricing_not_verified"
    monkeypatch.setattr(
        budget, "now_shanghai", lambda: datetime(2026, 10, 31, 23, 59, tzinfo=SHANGHAI)
    )
    with pytest.raises(RagError) as caught:
        ledger.reserve("deepseek-flash", "answer", 6000, 1500)
    assert caught.value.code == "budget_month_boundary"
    assert ledger.summary()["recorded_calls"] == 0


def test_provider_request_contract_and_actual_model_recording(ledger, tmp_path):
    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "disabled"}
        assert body["response_format"] == {"type": "json_object"}
        assert body["max_tokens"] == 1500
        assert "tools" not in body
        return httpx.Response(
            200,
            json={
                "model": "DeepSeek-test-version",
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )

    generator = DeepSeekGenerator(settings(tmp_path), ledger, httpx.MockTransport(handler))
    result = generator.complete([{"role": "system", "content": "返回 JSON"}])
    assert result["served_model"] == "DeepSeek-test-version"
    with Session(ledger.engine) as session:
        row = session.scalar(select(ApiCall))
        assert row.served_model == "DeepSeek-test-version"
        assert row.status == "settled_upper_bound"
        assert row.charged_units == 600


@pytest.mark.parametrize("kind", ["timeout", "http_error", "bad_json", "missing_usage"])
def test_provider_failures_preserve_reservation_and_never_retry_or_leak_secrets(
    ledger, tmp_path, kind
):
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("secret-provider-debug-message", request=request)
        if kind == "http_error":
            return httpx.Response(429, text="secret-provider-debug-message")
        if kind == "bad_json":
            return httpx.Response(200, text="secret-provider-debug-message")
        return httpx.Response(
            200,
            json={
                "model": "actual",
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            },
        )

    generator = DeepSeekGenerator(settings(tmp_path), ledger, httpx.MockTransport(handler))
    if kind == "missing_usage":
        generator.complete([{"role": "system", "content": "JSON"}])
    else:
        with pytest.raises(RagError) as caught:
            generator.complete([{"role": "system", "content": "JSON"}])
        assert "secret" not in str(caught.value)
    assert len(calls) == 1
    assert ledger.summary()["unresolved_reserved_cny"] == "0.024"


def test_disabled_or_oversized_input_has_no_network_or_ledger_call(ledger, tmp_path):
    def unexpected(_):
        raise AssertionError("Network must not be used")

    config = settings(tmp_path)
    config.allow_external_calls = False
    generator = DeepSeekGenerator(config, ledger, httpx.MockTransport(unexpected))
    with pytest.raises(RagError) as caught:
        generator.complete([{"role": "system", "content": "JSON"}])
    assert caught.value.code == "external_calls_disabled"
    config.allow_external_calls = True
    with pytest.raises(RagError) as caught:
        generator.complete([{"role": "user", "content": "长" * 6000}])
    assert caught.value.code == "generation_input_limit"
    assert ledger.summary()["recorded_calls"] == 0
