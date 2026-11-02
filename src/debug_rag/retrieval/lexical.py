"""Explicit Chinese bigrams and whole technical identifiers; no pickle artifacts."""

import re

from rank_bm25 import BM25Okapi

TOKENIZER_VERSION = "zh-bigram-ident-v1"


def tokenize(text: str) -> list[str]:
    tokens = []
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_.:-]*|[0-9]+|[\u3400-\u9fff]+", text):
        part = match.group().lower()
        if "\u3400" <= part[0] <= "\u9fff":
            tokens.extend(part[i : i + 2] for i in range(max(1, len(part) - 1)))
        else:
            tokens.append(part)
    return tokens


def bm25_search(corpus: list[dict], question: str, allowed: set[str], limit: int = 5):
    if not corpus or not tokenize(question):
        return []
    model = BM25Okapi([row["tokens"] for row in corpus])
    scores = model.get_scores(tokenize(question))
    ranked = sorted(
        (
            (row["chunk_id"], float(score))
            for row, score in zip(corpus, scores)
            if row["chunk_id"] in allowed and score > 0
        ),
        key=lambda hit: (-hit[1], hit[0]),
    )
    return [{"chunk_id": identity, "score": score} for identity, score in ranked[:limit]]


def fuse(routes: dict[str, list[dict]], k: int = 60) -> list[dict]:
    """No score mixing; repeated hits in one route contribute only once."""
    combined = {}
    for route, hits in routes.items():
        seen = set()
        rank = 0
        for hit in hits:
            identity = hit["chunk_id"]
            if identity in seen:
                continue
            seen.add(identity)
            rank += 1
            row = combined.setdefault(
                identity, {"chunk_id": identity, "rrf_score": 0, "routes": {}}
            )
            row["rrf_score"] += 1 / (k + rank)
            row["routes"][route] = {"rank": rank, "raw_score": hit["score"]}
    return sorted(combined.values(), key=lambda row: (-row["rrf_score"], row["chunk_id"]))
