from decimal import Decimal

import pytest
from pydantic import ValidationError

from debug_rag.settings import Settings


def test_defaults_disable_paid_calls_and_limit_budget(tmp_path):
    settings = Settings(_env_file=None, runtime_dir=tmp_path)
    assert settings.allow_external_calls is False
    assert settings.query_rewrite_enabled is False and settings.rerank_enabled is False
    assert settings.monthly_budget_cny == Decimal("50")
    assert settings.sqlite_path == tmp_path / "metadata.sqlite3"


@pytest.mark.parametrize("value", [0, -1, 50.01, 100])
def test_cannot_exceed_approved_monthly_budget(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, monthly_budget_cny=value)


@pytest.mark.parametrize("uri", ["not-a-url", "file:///data/milvus.db", "http://u:p@host:19530"])
def test_rejects_invalid_or_credential_bearing_uri(uri):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, milvus_uri=uri)


def test_empty_optional_model_path_and_no_secret_in_repr():
    settings = Settings(_env_file=None, embedding_model_path="", milvus_token="private-test-value")
    assert settings.embedding_model_path is None
    assert "private-test-value" not in repr(settings)


@pytest.mark.parametrize(
    "url",
    [
        "http://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        "https://other.example/api/v1/services/rerank/text-rerank/text-rerank",
        "https://u:key@dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank?key=secret",
    ],
)
def test_reranker_endpoint_rejects_credential_leak_and_wrong_hosts(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rerank_endpoint=url)


def test_example_environment_parses_without_enabling_paid_calls():
    from debug_rag.settings import PROJECT_ROOT

    settings = Settings(_env_file=PROJECT_ROOT / ".env.example")
    assert not settings.allow_external_calls
    assert settings.rerank_input_cny_per_million is None
    assert settings.rerank_price_verified_on is None


def test_viking_configuration_is_independent_and_secret_is_masked():
    settings = Settings(_env_file=None, viking_api_key="private-viking-unit-test")
    assert settings.viking_embedding_model == "bge-m3"
    assert settings.viking_embedding_endpoint.endswith("/api/vikingdb/embedding")
    assert not settings.allow_external_calls
    assert not settings.rerank_api_key.get_secret_value()
    assert "private-viking-unit-test" not in repr(settings)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api-vikingdb.vikingdb.cn-beijing.volces.com/api/vikingdb/embedding?key=private",
        "https://api-vikingdb.vikingdb.cn-beijing.volces.com/api/data/embedding/version/2",
        "http://api-vikingdb.vikingdb.cn-beijing.volces.com/api/vikingdb/embedding",
        "https://unrelated.example/api/vikingdb/embedding",
    ],
)
def test_viking_configuration_rejects_wrong_protocol_host_or_api_version(endpoint):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, viking_embedding_endpoint=endpoint)
