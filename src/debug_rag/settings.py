"""Validated environment configuration. Constructing settings has no I/O side effects."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_", env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="forbid"
    )

    runtime_dir: Path = PROJECT_ROOT / "runtime"
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: SecretStr = SecretStr("")
    milvus_timeout_seconds: float = Field(default=3, gt=0, le=30)
    kb_id: str = Field(default="demo-debug", min_length=1, max_length=100)
    embedding_model_path: Path | None = None
    embedding_backend: Literal["local", "viking"] = "local"
    dense_top_k: int = Field(default=5, ge=1, le=5)
    sparse_top_k: int = Field(default=5, ge=1, le=5)
    bm25_top_k: int = Field(default=5, ge=1, le=5)
    rrf_k: int = Field(default=60, ge=1, le=1000)
    allow_external_calls: bool = False
    monthly_budget_cny: Decimal = Field(default=Decimal("50"), gt=0, le=50)
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: Literal["deepseek-flash"] = "deepseek-flash"
    generation_timeout_seconds: float = Field(default=45, gt=0, le=60)
    max_input_tokens: int = Field(default=6000, ge=2000, le=6000)
    max_output_tokens: int = Field(default=1500, ge=100, le=1500)
    parent_expansion_enabled: bool = True
    query_rewrite_enabled: bool = False
    rerank_enabled: bool = False
    rerank_api_key: SecretStr = SecretStr("")
    rerank_endpoint: str = ""
    rerank_model: Literal["qwen3-rerank"] = "qwen3-rerank"
    rerank_timeout_seconds: float = Field(default=20, gt=0, le=60)
    rerank_max_input_tokens: int = Field(default=16000, ge=2000, le=30000)
    rerank_input_cny_per_million: Decimal | None = Field(default=None, gt=0)
    rerank_price_verified_on: date | None = None
    rerank_price_valid_through: date | None = None
    # Explicit opt-in backend; changing this never rewrites or publishes an existing index.
    viking_api_key: SecretStr = SecretStr("")
    viking_embedding_endpoint: str = (
        "https://api-vikingdb.vikingdb.cn-beijing.volces.com/api/vikingdb/embedding"
    )
    viking_embedding_model: Literal["bge-m3"] = "bge-m3"
    viking_embedding_version: str = Field(default="default", min_length=1, max_length=100)
    viking_embedding_revision: str = Field(
        default="viking-bge-m3-default-v1", min_length=1, max_length=100
    )
    viking_batch_size: int = Field(default=4, ge=1, le=16)
    viking_window_chars: int = Field(default=1200, ge=1, le=1800)
    viking_timeout_seconds: float = Field(default=30, gt=0, le=60)
    viking_request_upper_bound_cny: Decimal | None = Field(default=None, gt=0, le=50)
    viking_price_verified_on: date | None = None
    viking_price_valid_through: date | None = None

    @field_validator("viking_embedding_endpoint")
    @classmethod
    def validate_viking_endpoint(cls, value):
        allowed = {
            f"https://api-vikingdb.vikingdb.{region}.volces.com/api/vikingdb/embedding"
            for region in ("cn-beijing", "cn-shanghai", "cn-guangzhou")
        }
        if value not in allowed:
            raise ValueError("Use an official VikingDB HTTPS embedding endpoint for the region")
        return value

    @field_validator(
        "rerank_input_cny_per_million",
        "rerank_price_verified_on",
        "rerank_price_valid_through",
        "viking_request_upper_bound_cny",
        "viking_price_verified_on",
        "viking_price_valid_through",
        mode="before",
    )
    @classmethod
    def empty_optional_price(cls, value):
        return None if value == "" else value

    @field_validator("rerank_endpoint")
    @classmethod
    def validate_rerank_endpoint(cls, value):
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not (parsed.hostname or "").endswith(".aliyuncs.com")
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port not in {None, 443}
            or parsed.path != "/api/v1/services/rerank/text-rerank/text-rerank"
        ):
            raise ValueError("Use the official Bailian HTTPS rerank endpoint without credentials")
        return value

    @field_validator("embedding_model_path", mode="before")
    @classmethod
    def empty_model_path(cls, value):
        return None if value == "" else value

    @field_validator("runtime_dir", "embedding_model_path", mode="after")
    @classmethod
    def absolute_project_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        return (value if value.is_absolute() else PROJECT_ROOT / value).resolve()

    @field_validator("milvus_uri")
    @classmethod
    def validate_milvus_uri(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Milvus URI must be an http(s) service URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use RAG_MILVUS_TOKEN, never credentials in the service URL")
        return value.rstrip("/")

    @property
    def sqlite_path(self) -> Path:
        return self.runtime_dir / "metadata.sqlite3"
