"""Bailian qwen3-rerank native adapter, independent of the generation model.

Contract: https://help.aliyun.com/zh/model-studio/text-rerank-api
No provider body or exception text is exposed. Retries are deliberately disabled.
"""

import math

import httpx

from debug_rag.errors import RagError
from debug_rag.generation.grounding import ensure_external_permission


def validate_ranking(results, count):
    if not isinstance(results, list) or len(results) != count:
        raise ValueError("Incomplete rerank result")
    seen = set()
    for row in results:
        index, score = row["index"], row["relevance_score"]
        if (
            type(index) is not int
            or not 0 <= index < count
            or index in seen
            or type(score) not in {int, float}
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise ValueError("Invalid rerank mapping or score")
        seen.add(index)
    return sorted(results, key=lambda row: (-row["relevance_score"], row["index"]))


class BailianReranker:
    def __init__(self, settings, ledger, transport=None):
        self.settings, self.ledger, self.transport = settings, ledger, transport

    def check_configured(self):
        if not self.settings.allow_external_calls:
            raise RagError("external_calls_disabled", "外部模型调用已关闭。")
        if not self.settings.rerank_api_key.get_secret_value() or not self.settings.rerank_endpoint:
            raise RagError("rerank_not_configured", "请配置百炼重排地址与自己的 API Key。")

    def rerank(self, query: str, candidates: list[dict]) -> dict:
        self.check_configured()
        ensure_external_permission(candidates)
        if not 1 <= len(candidates) <= 20:
            raise RagError("rerank_candidate_limit", "重排仅接受 1–20 个原文候选。", 422)
        documents = [
            row["metadata"]["title"] + "\n" + " / ".join(row["section_path"]) + "\n" + row["text"]
            for row in candidates
        ]
        # Token accounting repeats the query for each passage, not just once per request.
        bound = sum(len((query + text).encode("utf-8")) + 256 for text in documents)
        if bound > self.settings.rerank_max_input_tokens:
            raise RagError("rerank_input_limit", "重排输入超出当前预算上限。", 422)
        s = self.settings
        pricing = {
            "provider": "bailian",
            "model": s.rerank_model,
            "currency": "CNY",
            "input_per_million": str(s.rerank_input_cny_per_million),
            "output_per_million": "0",
            "verified_on": str(s.rerank_price_verified_on),
            "valid_through": str(s.rerank_price_valid_through),
            "source": "https://help.aliyun.com/zh/model-studio/model-pricing",
            "method": "account-region verified input-token rate; not a provider invoice",
        }
        call_id = self.ledger.reserve(s.rerank_model, "rerank", bound, 0, pricing=pricing)
        record = {
            "call_id": call_id,
            "purpose": "rerank",
            "served_model": s.rerank_model,
            "usage": None,
        }
        attempted = False
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=s.rerank_timeout_seconds,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                attempted = True
                response = client.post(
                    s.rerank_endpoint,
                    headers={"Authorization": "Bearer " + s.rerank_api_key.get_secret_value()},
                    json={
                        "model": s.rerank_model,
                        "input": {"query": query, "documents": documents},
                        "parameters": {"top_n": len(documents), "return_documents": False},
                    },
                )
            if response.status_code != 200:
                raise RagError("rerank_provider_error", "重排服务返回错误，未自动重试。", 502)
            data = response.json()
            if not isinstance(data, dict) or data.get("code"):
                raise ValueError("Invalid rerank response")
            record["usage"] = data.get("usage")
            usage = data.get("usage")
            total = usage.get("total_tokens") if isinstance(usage, dict) else None
            self.ledger.settle(
                call_id, {"prompt_tokens": total, "completion_tokens": 0}, s.rerank_model, bound, 0
            )
            ranked = validate_ranking(data["output"]["results"], len(documents))
            return {**record, "results": ranked}
        except RagError as exc:
            self.ledger.unknown(call_id)
            if attempted:
                exc.api_call = {**record, "status": "failed"}
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            self.ledger.unknown(call_id)
            error = RagError("invalid_rerank_response", "重排超时或响应无效，使用融合排名。", 502)
            if attempted:
                error.api_call = {**record, "status": "failed"}
            raise error from None
