"""DeepSeek native JSON completion with disabled thinking and zero transport retries."""

import json

import httpx

from debug_rag.errors import RagError

ENDPOINT = "https://api.deepseek.com/chat/completions"


def input_upper_bound(messages: list[dict]) -> int:
    # A conservative UTF-8 byte bound plus framing headroom, NOT an exact tokenizer count.
    return len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) + 1024


class DeepSeekGenerator:
    def __init__(self, settings, ledger, transport=None):
        self.settings, self.ledger, self.transport = settings, ledger, transport

    def check_configured(self):
        if not self.settings.allow_external_calls:
            raise RagError("external_calls_disabled", "外部模型调用已关闭；可先使用仅检索模式。")
        if not self.settings.deepseek_api_key.get_secret_value():
            raise RagError("generation_key_missing", "请在本机 .env 配置自己的 DeepSeek API Key。")

    def complete(
        self, messages: list[dict], purpose: str = "answer", *, max_output_tokens: int | None = None
    ) -> dict:
        self.check_configured()
        output_limit = min(
            max_output_tokens or self.settings.max_output_tokens, self.settings.max_output_tokens
        )
        if input_upper_bound(messages) > self.settings.max_input_tokens:
            raise RagError("generation_input_limit", "生成输入超出当前预算上限，未调用模型。", 422)
        call_id = self.ledger.reserve(
            self.settings.deepseek_model,
            purpose,
            self.settings.max_input_tokens,
            output_limit,
        )
        payload = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": output_limit,
            "temperature": 0.1,
            "stream": False,
        }
        attempted = False
        record = {"call_id": call_id, "purpose": purpose, "served_model": None, "usage": None}
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=self.settings.generation_timeout_seconds,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                attempted = True
                response = client.post(
                    ENDPOINT,
                    json=payload,
                    headers={
                        "Authorization": "Bearer "
                        + self.settings.deepseek_api_key.get_secret_value(),
                        "Content-Type": "application/json",
                    },
                )
            if response.status_code != 200:
                raise RagError(
                    "generation_provider_error", "生成服务返回错误；未自动重试，预留费用保留。", 502
                )
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Invalid response object")
            record.update(served_model=data.get("model"), usage=data.get("usage"))
            self.ledger.settle(
                call_id,
                data.get("usage"),
                data.get("model"),
                self.settings.max_input_tokens,
                output_limit,
            )
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise RagError(
                    "generation_incomplete", "模型输出未正常结束，本次不作为有效答案。", 502
                )
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Missing completion content")
            return {
                "content": content,
                "call_id": call_id,
                "served_model": data.get("model"),
                "usage": data.get("usage"),
            }
        except RagError as exc:
            self.ledger.unknown(call_id)
            if attempted:
                exc.api_call = {**record, "status": "failed"}
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            self.ledger.unknown(call_id)
            error = RagError(
                "generation_provider_unavailable", "生成请求超时或响应无效；未自动重试。", 502
            )
            if attempted:
                error.api_call = {**record, "status": "failed"}
            raise error from None
