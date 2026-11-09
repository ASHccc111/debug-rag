"""VikingDB BGE-M3 dense/sparse adapter; construction never performs network I/O.

Wire contract: volcengine/vikingdb-python-sdk, vector/models/embedding.py.
Sparse keys remain opaque strings. The index owns their collision-free integer mapping.
Only a verified *per-request* charge bound is used until billing usage is verified.
"""

import math
import re
from decimal import Decimal
from threading import local

import httpx

from debug_rag.errors import RagError

DIMENSION = 1024
USAGE_FIELDS = {
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "text_tokens",
    "image_tokens",
    "tokens",
}


def safe_usage(value):
    """Retain numeric counters only; never reflect arbitrary provider text into traces."""
    if not isinstance(value, dict):
        return None
    counters = {
        key: value[key] for key in USAGE_FIELDS if type(value.get(key)) is int and value[key] >= 0
    }
    for key in ("bge-m3", "dense", "sparse"):
        nested = value.get(key)
        if isinstance(nested, dict):
            selected = {
                name: nested[name]
                for name in USAGE_FIELDS
                if type(nested.get(name)) is int and nested[name] >= 0
            }
            if selected:
                counters[key] = selected
    return counters or None


def validate_embedding(row):
    if not isinstance(row, dict):
        raise ValueError("Invalid embedding row")
    dense, sparse = row.get("dense"), row.get("sparse")
    if (
        not isinstance(dense, list)
        or len(dense) != DIMENSION
        or any(type(x) not in {int, float} or not math.isfinite(x) for x in dense)
    ):
        raise ValueError("Invalid dense vector")
    norm = math.hypot(*dense)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("Invalid dense norm")
    if (
        not isinstance(sparse, dict)
        or not sparse
        or any(
            not isinstance(key, str)
            or not key
            or len(key) > 4096
            or type(weight) not in {int, float}
            or not math.isfinite(weight)
            or weight <= 0
            for key, weight in sparse.items()
        )
    ):
        raise ValueError("Invalid sparse vector")
    return {"dense": [float(x / norm) for x in dense], "sparse": dict(sparse)}


class VikingEmbedder:
    def __init__(self, settings, ledger, transport=None):
        self.settings, self.ledger, self.transport = settings, ledger, transport
        self._state = local()
        self.last_calls = []

    @property
    def last_calls(self):
        return getattr(self._state, "last_calls", [])

    @last_calls.setter
    def last_calls(self, value):
        self._state.last_calls = value

    @property
    def identity(self):
        s = self.settings
        return {
            "provider": "viking",
            "endpoint": s.viking_embedding_endpoint,
            "model": s.viking_embedding_model,
            "version": s.viking_embedding_version,
            "revision": s.viking_embedding_revision,
            "dimension": DIMENSION,
            "dense_normalization": "l2-v1",
            "sparse_format": "opaque-token-weight-v1",
            "window_chars": s.viking_window_chars,
        }

    def windows(self, text):
        if not isinstance(text, str) or not text:
            return []
        size = self.settings.viking_window_chars
        return [(i, min(len(text), i + size)) for i in range(0, len(text), size)]

    def check_configured(self):
        s = self.settings
        if not s.allow_external_calls:
            raise RagError("external_calls_disabled", "外部模型调用已关闭。", 409)
        if not s.viking_api_key.get_secret_value():
            raise RagError("embedding_not_configured", "请在本机配置远程向量服务密钥。", 409)
        endpoints = {
            f"https://api-vikingdb.vikingdb.{region}.volces.com/api/vikingdb/embedding"
            for region in ("cn-beijing", "cn-shanghai", "cn-guangzhou")
        }
        if s.viking_embedding_endpoint not in endpoints or s.viking_embedding_model != "bge-m3":
            raise RagError("invalid_embedding_endpoint", "远程向量服务配置不匹配。", 409)
        if not 1 <= s.viking_batch_size <= 16 or not 1 <= s.viking_window_chars <= 1800:
            raise RagError("invalid_embedding_limits", "远程向量批次或窗口配置不合法。", 409)

    def _pricing(self):
        s = self.settings
        bound = s.viking_request_upper_bound_cny
        if bound is None or not bound.is_finite() or bound <= 0:
            raise RagError("pricing_not_verified", "请先核实远程向量每请求费用上界及有效期。", 409)
        return {
            "provider": "vikingdb",
            "model": s.viking_embedding_model,
            "currency": "CNY",
            # One accounting unit is one request, *not* an observed input token.
            "input_per_million": str(bound * Decimal(1_000_000)),
            "output_per_million": "0",
            "verified_on": str(s.viking_price_verified_on),
            "valid_through": str(s.viking_price_valid_through),
            "source": "https://docs.volcengine.com/docs/vector-database-vikingdb/billing-of-a-vector-database?lang=en",
            "method": "per-request bound; synthetic reservation unit, not token usage",
            "request_upper_bound_cny": str(bound),
        }

    def encode(self, texts, *, query=False):
        return [row["dense"] for row in self.encode_hybrid(texts, query=query)]

    def encode_hybrid(self, texts, *, query=False):
        self.last_calls = []
        self.check_configured()
        if not isinstance(texts, list):
            raise RagError("invalid_embedding_input", "向量编码需要文本列表。", 422)
        # A byte bound plus special-token margin prevents relying on server truncation.
        if any(
            not isinstance(text, str)
            or not text.strip()
            or len(text) > self.settings.viking_window_chars
            or len(text.encode("utf-8")) + 16 > 8192
            for text in texts
        ):
            raise RagError("embedding_input_limit", "远程编码文本为空或超过安全窗口。", 422)
        if not texts:
            return []
        pricing = self._pricing()
        result = []
        for start in range(0, len(texts), self.settings.viking_batch_size):
            batch = texts[start : start + self.settings.viking_batch_size]
            result.extend(self._request(batch, query, pricing))
        return result

    def _request(self, texts, query, pricing):
        s = self.settings
        purpose = "embedding_query" if query else "embedding_documents"
        try:
            call_id = self.ledger.reserve(s.viking_embedding_model, purpose, 1, 0, pricing=pricing)
        except RagError:
            raise
        except Exception:
            raise RagError(
                "embedding_ledger_unavailable", "费用台账不可用，未调用远程编码。"
            ) from None
        record = {
            "call_id": call_id,
            "purpose": purpose,
            "requested_model": s.viking_embedding_model,
            "served_model": None,
            "usage": None,
            "usage_verified": False,
            "status": "reserved",
            "attempted": False,
        }
        self.last_calls.append(record)
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=s.viking_timeout_seconds,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                record["attempted"] = True
                response = client.post(
                    s.viking_embedding_endpoint,
                    headers={"Authorization": "Bearer " + s.viking_api_key.get_secret_value()},
                    json={
                        "dense_model": {
                            "name": s.viking_embedding_model,
                            "version": s.viking_embedding_version,
                            "dim": DIMENSION,
                        },
                        "sparse_model": {
                            "name": s.viking_embedding_model,
                            "version": s.viking_embedding_version,
                        },
                        "data": [{"text": text} for text in texts],
                    },
                )
            record["http_status"] = response.status_code
            if response.status_code in {401, 403}:
                raise RagError(
                    "embedding_access_denied",
                    "火山向量服务拒绝访问，请检查服务开通、地域、项目及 API Key 权限。",
                    403,
                )
            if response.status_code != 200:
                raise RagError(
                    "embedding_provider_error", "远程向量服务返回错误，未自动重试。", 502
                )
            body = response.json()
            if not isinstance(body, dict) or body.get("code") != "Success":
                raise ValueError("Unsuccessful provider envelope")
            payload = body.get("result")
            if not isinstance(payload, dict):
                raise ValueError("Missing provider result")
            rows = payload.get("data")
            if not isinstance(rows, list) or len(rows) != len(texts):
                raise ValueError("Embedding count mismatch")
            vectors = [validate_embedding(row) for row in rows]
            record["usage"] = safe_usage(payload.get("token_usage"))
            request_id = body.get("request_id")
            if isinstance(request_id, str) and re.fullmatch(
                r"[\w.:-]{1,128}", request_id, re.ASCII
            ):
                record["request_id"] = request_id
            # Token shape/rates for simultaneous dense+sparse are not assumed.
            self.ledger.settle(call_id, None, None, 1, 0)
            record["status"] = "succeeded"
            record["ledger_status"] = "unknown"
            return vectors
        except Exception as exc:
            record["status"] = "failed"
            try:
                self.ledger.unknown(call_id)
            except Exception:
                error = RagError(
                    "embedding_ledger_unavailable", "费用台账处理失败，已停止远程编码。"
                )
                error.api_call = dict(record)
                raise error from None
            if isinstance(exc, RagError):
                exc.api_call = dict(record)
                raise
            error = RagError(
                "invalid_embedding_response", "远程向量调用失败或响应无效，未自动重试。", 502
            )
            error.api_call = dict(record)
            raise error from None
