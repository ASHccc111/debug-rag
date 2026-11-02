"""Offline BGE CLS/normalized encoding with explicit token windows, CPU only."""

import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path
from threading import RLock

from debug_rag.errors import RagError

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


class LocalEmbedder:
    def __init__(self, path: Path | None):
        self.path = path
        self._model = None
        self._lock = RLock()

    def _load(self):
        with self._lock:
            if self._model is not None:
                if any(
                    (p.stat().st_size, p.stat().st_mtime_ns) != stamp
                    for p, stamp in self._file_stats.items()
                ):
                    raise RagError(
                        "model_files_changed", "本地模型文件已改变，请重启并重建索引。", 409
                    )
                return
            if not self.path or not self.path.is_dir():
                raise RagError("embedding_not_configured", "请配置完整的本地 bge-small 模型目录。")
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            os.environ["TOKENIZERS_PARALLELISM"] = "false"
            import torch
            from transformers import AutoModel, AutoTokenizer

            torch.set_num_threads(4)
            config = json.loads((self.path / "config.json").read_text(encoding="utf-8"))
            if config.get("model_type") != "bert" or config.get("hidden_size") != 512:
                raise RagError(
                    "wrong_embedding_model", "light 档位需要 bge-small 中文 512 维模型。", 409
                )
            files = sorted(
                p
                for p in self.path.iterdir()
                if p.is_file() and (p.suffix in {".json", ".txt", ".safetensors", ".bin"})
            )
            digest = hashlib.sha256()
            for path in files:
                digest.update(path.name.encode())
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
            self._file_stats = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in files}
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.path, local_files_only=True, trust_remote_code=False, use_fast=True
            )
            model = (
                AutoModel.from_pretrained(
                    self.path,
                    local_files_only=True,
                    trust_remote_code=False,
                    use_safetensors=(self.path / "model.safetensors").exists(),
                )
                .to("cpu")
                .eval()
            )
            self.max_tokens = min(512, int(config["max_position_embeddings"]))
            self._identity = {
                "model": "BAAI/bge-small-zh-v1.5",
                "files_sha256": digest.hexdigest(),
                "dimension": 512,
                "pooling": "cls",
                "normalize": True,
                "device": "cpu",
                "max_tokens": self.max_tokens,
                "query_prefix": QUERY_PREFIX,
                "transformers": version("transformers"),
                "torch": version("torch"),
                "window_policy": "source-token-windows-v1",
            }
            self._model = model

    @property
    def identity(self) -> dict:
        self._load()
        return dict(self._identity)

    def windows(self, text: str) -> list[tuple[int, int]]:
        self._load()
        cursor, spans = 0, []
        while cursor < len(text):
            suffix = text[cursor:]
            encoded = self.tokenizer(suffix, add_special_tokens=False, return_offsets_mapping=True)
            offsets = encoded["offset_mapping"]
            capacity = self.max_tokens - self.tokenizer.num_special_tokens_to_add(pair=False)
            if len(offsets) <= capacity:
                stop = len(text)
            else:
                stop = cursor + offsets[capacity - 1][1]
                # WordPiece re-tokenization at a window boundary can change token count.
                while (
                    stop > cursor
                    and len(self.tokenizer(text[cursor:stop])["input_ids"]) > self.max_tokens
                ):
                    stop -= 1
            if stop <= cursor:
                raise RagError("embedding_window_failed", "无法形成有效的原文向量窗口。", 422)
            spans.append((cursor, stop))
            cursor = stop
        return spans

    def encode(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        self._load()
        import torch

        inputs = [(QUERY_PREFIX + text) if query else text for text in texts]
        if any(len(self.tokenizer(t)["input_ids"]) > self.max_tokens for t in inputs):
            raise RagError(
                "embedding_token_limit", "文本超过 Embedding token 上限，未做静默截断。", 422
            )
        vectors = []
        with self._lock, torch.inference_mode():
            for start in range(0, len(inputs), 8):
                batch = self.tokenizer(
                    inputs[start : start + 8], padding=True, truncation=False, return_tensors="pt"
                )
                output = self._model(**batch).last_hidden_state[:, 0]
                normalized = torch.nn.functional.normalize(output, p=2, dim=1)
                if not torch.isfinite(normalized).all():
                    raise RagError("invalid_embedding", "向量结果包含非法数值。")
                vectors.extend(normalized.tolist())
        return vectors
