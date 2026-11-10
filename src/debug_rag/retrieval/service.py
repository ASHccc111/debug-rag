"""Captured snapshot -> optional rewrite -> route recall -> one RRF -> optional rerank."""

import time
from collections import Counter

from debug_rag.errors import RagError
from debug_rag.generation.grounding import (
    compact_context,
    context,
    ensure_external_permission,
    messages,
    validate_answer,
)
from debug_rag.retrieval.indexing import load_artifact, published_snapshot, snapshot
from debug_rag.retrieval.lexical import bm25_search, fuse, structured_focus
from debug_rag.retrieval.rerank import validate_ranking


class RagService:
    def __init__(
        self, settings, engine, embedder, vectors, generator, *, rewriter=None, reranker=None
    ):
        self.settings, self.engine = settings, engine
        self.embedder, self.vectors, self.generator = embedder, vectors, generator
        self.rewriter, self.reranker = rewriter, reranker

    def search(
        self, kb_id: str, question: str, *, enhanced: bool = False, allow_paid: bool = False
    ) -> dict:
        started = time.perf_counter()
        if not question.strip() or len(question) > 300:
            raise RagError("invalid_question", "问题需为 1–300 个字符。", 422)
        generation_id, manifest, chunks = published_snapshot(self.settings, self.engine, kb_id)
        profile = manifest["pipeline"]["profile"]
        if profile == "hybrid":
            if not allow_paid:
                raise RagError(
                    "remote_embedding_opt_in_required",
                    "当前索引需要远程编码；请明确允许本次收费检索，或切回本地基线。",
                    409,
                )
            ensure_external_permission(chunks)
        if self.embedder.identity != manifest["pipeline"]["embedding"]:
            raise RagError(
                "embedding_identity_mismatch", "查询模型与索引模型不一致，请重建索引。", 409
            )
        data = load_artifact(self.settings.runtime_dir, generation_id, manifest)
        by_id = {c["chunk_id"]: c for c in chunks}
        if {row["chunk_id"] for row in data["corpus"]} != set(by_id):
            raise RagError("lexical_mapping_mismatch", "关键词索引与原文清单不一致。", 409)
        windows = {row["id"]: row for row in data["windows"]}
        if len(windows) != manifest["representation_count"]:
            raise RagError("vector_mapping_mismatch", "向量窗口清单不完整。", 409)
        allowed = {c["chunk_id"] for c in chunks if c["metadata"]["feature_status"] == "delivered"}
        calls = []
        rewrite_trace = {"status": "disabled", "query": None}
        rerank_trace = {"status": "disabled"}
        queries = [question]
        if enhanced and self.settings.query_rewrite_enabled:
            if any(not by_id[i]["metadata"]["external_processing_allowed"] for i in allowed):
                rewrite_trace = {"status": "skipped", "reason": "kb_external_processing_restricted"}
            else:
                rewritten, rewrite_trace = self._optional(
                    self.rewriter, "rewrite", (question,), "query_rewrite", calls
                )
                if rewritten:
                    value = rewritten["query"]
                    rewrite_trace["query"] = value
                    rewrite_trace["semantic_equivalence_verified"] = False
                    if value != question.strip():
                        queries.append(value)
                    else:
                        rewrite_trace["status"] = "unchanged"
        routes = {}
        for index, query in enumerate(queries):
            recalled = self._recall(
                kb_id, generation_id, manifest, by_id, windows, allowed, data, query, calls
            )
            suffix = "" if index == 0 else "_rewrite"
            routes.update({name + suffix: hits for name, hits in recalled.items()})
        if profile == "light" and self.settings.structured_recall_enabled:
            focused = structured_focus(by_id, question, allowed)
            if focused:
                routes["structured_focus"] = focused
        fused = fuse(routes, k=self.settings.rrf_k)
        candidates = [{**by_id[row["chunk_id"]], **row} for row in fused]
        if enhanced and self.settings.rerank_enabled:
            if not candidates:
                rerank_trace = {"status": "skipped", "reason": "no_candidates"}
            elif any(not c["metadata"]["external_processing_allowed"] for c in candidates):
                rerank_trace = {"status": "skipped", "reason": "external_processing_not_allowed"}
            else:
                # Keep the user's actual constraints for reranking; a rewrite only adds recall.
                ranked, rerank_trace = self._optional(
                    self.reranker, "rerank", (question, candidates), "rerank", calls
                )
                if ranked:
                    ordered = validate_ranking(ranked["results"], len(candidates))
                    candidates = [
                        {**candidates[row["index"]], "rerank_score": row["relevance_score"]}
                        for row in ordered
                    ]
                    rerank_trace["ranking"] = [
                        {"chunk_id": c["chunk_id"], "score": c["rerank_score"]} for c in candidates
                    ]
                    rerank_trace["query"] = question
        return {
            "kb_id": kb_id,
            "generation_id": generation_id,
            "app_snapshot": manifest["app_snapshot"],
            "data_kind": manifest["data_kind"],
            "candidates": candidates,
            "api_calls": calls,
            "trace": {
                "profile": profile + "_enhanced" if enhanced else profile,
                "dense_top_k": self.settings.dense_top_k,
                "sparse_top_k": self.settings.sparse_top_k if profile == "hybrid" else None,
                "bm25_top_k": self.settings.bm25_top_k if profile == "light" else None,
                "rrf_k": self.settings.rrf_k,
                "fusion": "single_global_rrf",
                "deduplication": "best_rank_per_source_chunk_per_route",
                **routes,
                "queries": queries,
                "query_rewrite_enabled": enhanced and self.settings.query_rewrite_enabled,
                "query_rewrite_applied": len(queries) > 1,
                "query_rewrite": rewrite_trace,
                "rerank_enabled": enhanced and self.settings.rerank_enabled,
                "rerank_applied": rerank_trace["status"] == "applied",
                "rerank": rerank_trace,
                "degraded": any(
                    t["status"] in {"failed", "skipped"} and t.get("reason") != "no_candidates"
                    for t in (rewrite_trace, rerank_trace)
                ),
                "parent_expansion_enabled": self.settings.parent_expansion_enabled,
                "parent_expansion_applied": False,
                "external_calls_executed": len(calls),
                "search_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        }

    def _optional(self, provider, method, args, purpose, calls):
        """Optional stages fail visibly back to the local baseline, without automatic retries."""
        if not self.settings.allow_external_calls:
            return None, {"status": "skipped", "reason": "external_calls_disabled"}
        if provider is None:
            return None, {"status": "skipped", "reason": "provider_not_configured"}
        try:
            value = getattr(provider, method)(*args)
            calls.append(
                {
                    **{k: value.get(k) for k in ("call_id", "served_model", "usage")},
                    "purpose": purpose,
                    "status": "succeeded",
                }
            )
            return value, {"status": "applied"}
        except RagError as exc:
            if getattr(exc, "api_call", None):
                calls.append(exc.api_call)
            return None, {"status": "failed", "reason": exc.code}

    def _recall(
        self, kb_id, generation_id, manifest, by_id, windows, allowed, data, question, calls
    ):
        hybrid = manifest["pipeline"]["profile"] == "hybrid"
        if hybrid:
            encoded = self.embedder.encode_hybrid([question], query=True)[0]
            vector = encoded["dense"]
            calls.extend(dict(row) for row in getattr(self.embedder, "last_calls", []))
        else:
            vector = self.embedder.encode([question], query=True)[0]
        counts = Counter(w["chunk_id"] for w in windows.values())
        factor = max(counts.values(), default=1)
        limit = min(len(windows), self.settings.dense_top_k * factor)
        raw_hits = self.vectors.search(
            manifest["collection"], vector, generation_id, kb_id, limit=limit
        )
        dense = self._source_hits(
            raw_hits, generation_id, kb_id, by_id, windows, allowed, self.settings.dense_top_k
        )
        if hybrid:
            vocabulary = data["sparse_vocabulary"]
            sparse = {vocabulary[k]: v for k, v in encoded["sparse"].items() if k in vocabulary}
            sparse_hits = (
                self.vectors.search_sparse(
                    manifest["collection"],
                    sparse,
                    generation_id,
                    kb_id,
                    limit=min(len(windows), self.settings.sparse_top_k * factor),
                )
                if sparse
                else []
            )
            return {
                "dense": dense,
                "sparse": self._source_hits(
                    sparse_hits,
                    generation_id,
                    kb_id,
                    by_id,
                    windows,
                    allowed,
                    self.settings.sparse_top_k,
                ),
            }
        return {
            "dense": dense,
            "bm25": bm25_search(data["corpus"], question, allowed, limit=self.settings.bm25_top_k),
        }

    @staticmethod
    def _source_hits(raw_hits, generation_id, kb_id, by_id, windows, allowed, top_k):
        result, seen = [], set()
        for hit in raw_hits:
            window = windows.get(hit["representation_id"])
            chunk = by_id.get(hit["chunk_id"])
            if (
                not window
                or not chunk
                or window["chunk_id"] != hit["chunk_id"]
                or hit["generation_id"] != generation_id
                or hit["kb_id"] != kb_id
                or hit["revision_id"] != chunk["revision_id"]
                or hit["revision_id"] != window["revision_id"]
                or hit["chunk_id"] not in allowed
            ):
                raise RagError(
                    "retrieval_mapping_invalid", "检索命中不属于当前允许的原文快照。", 409
                )
            if hit["chunk_id"] not in seen:
                result.append({"chunk_id": hit["chunk_id"], "score": hit["score"]})
                seen.add(hit["chunk_id"])
            if len(result) == top_k:
                break
        return result

    def prepare_context(
        self, kb_id: str, question: str, *, enhanced: bool = False, allow_paid: bool = False
    ) -> dict:
        """Preview evidence without answer generation; enhancement is explicitly opt-in."""
        result = self.search(kb_id, question, enhanced=enhanced, allow_paid=allow_paid)
        candidates = result.pop("candidates")
        base = {
            **result,
            "mode": "context_preview",
            "citations": [],
            "statements": [],
            "context": [],
        }
        if not candidates:
            return base
        parents = None
        if self.settings.parent_expansion_enabled:
            _, all_chunks = snapshot(
                self.engine, kb_id, result["generation_id"], include_parents=True
            )
            parents = {c["chunk_id"]: c for c in all_chunks if c["kind"] == "parent"}
        compact = self.settings.compact_context_enabled and any(
            "source_locations" in row for row in candidates[:5]
        )
        if compact:
            selected = compact_context(
                question, candidates, self.settings.max_input_tokens, parents
            )
        else:
            selected = context(
                question,
                candidates,
                self.settings.max_input_tokens,
                parents=parents,
                check_external=False,
            )
        base["context"] = selected
        base["trace"]["context_strategy"] = "children_then_expand" if compact else "parent_first"
        base["trace"]["selected_context_count"] = len(selected)
        represented = {
            identity for row in selected for identity in row["retrieved_child_chunk_ids"]
        }
        base["trace"]["omitted_candidate_count"] = len(candidates) - len(represented)
        base["trace"]["parent_expansion_applied"] = any(
            row["context_expansion"] == "parent" for row in selected
        )
        base["trace"]["selected_parent_count"] = sum(
            row["context_expansion"] == "parent" for row in selected
        )
        base["trace"]["parent_fallback_count"] = sum(
            row["context_expansion"] == "child_fallback" for row in selected
        )
        return base

    def answer(
        self, kb_id: str, question: str, *, enhanced: bool = False, allow_paid: bool = False
    ) -> dict:
        base = self.prepare_context(kb_id, question, enhanced=enhanced, allow_paid=allow_paid)
        base.pop("mode")
        selected = base["context"]
        if not selected:
            return {**base, "status": "insufficient_evidence", "answer": "当前范围没有可用证据。"}
        ensure_external_permission(selected)
        for attempt in range(2):
            generated = self.generator.complete(
                messages(
                    question,
                    selected,
                    repair=bool(attempt),
                    compact=base["trace"]["context_strategy"] == "children_then_expand",
                ),
                purpose="answer" if attempt == 0 else "citation_repair",
            )
            base["api_calls"].append(
                {key: generated[key] for key in ("call_id", "served_model", "usage")}
            )
            base["trace"]["external_calls_executed"] += 1
            try:
                answer = validate_answer(generated["content"], selected)
                used = {identity for s in answer.statements for identity in s.citations}
                return {
                    **base,
                    "status": answer.status,
                    "statements": [s.model_dump() for s in answer.statements],
                    "answer": "\n".join(
                        s.text + " " + " ".join(f"[{i}]" for i in s.citations)
                        for s in answer.statements
                    )
                    or answer.message,
                    "limitation": answer.limitation,
                    "citations": [row for row in selected if row["evidence_id"] in used],
                    "generation_validation": "structure_passed_semantics_not_verified",
                }
            except RagError as exc:
                if exc.code != "invalid_generation_output":
                    raise
        return {
            **base,
            "status": "partial",
            "generation_validation": "failed",
            "answer": "模型输出未通过格式或引用校验；本次仅展示原文，不提供生成结论。",
            "limitation": "至多尝试一次修复，未展示无效模型输出。",
        }
