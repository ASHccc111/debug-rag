"""Explicit Chinese bigrams and whole technical identifiers; no pickle artifacts."""

import re

from rank_bm25 import BM25Okapi

TOKENIZER_VERSION = "zh-bigram-ident-v1"
STRUCTURED_FOCUS_WEIGHT = 2


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


def structured_focus(chunks, question, allowed, limit=3):
    """Follow an explicitly named source to a table row or a linked diagram node."""
    titles = set(re.findall(r"《([^》]+)》", question))
    if not titles:
        return []
    prompt = re.sub(r"《[^》]+》", "", question)
    phrases = re.findall(r"「([^」]+)」|“([^”]+)”", prompt)
    focus = {part.casefold() for pair in phrases for part in pair if part}
    focus.update(re.findall(r"[a-z_][a-z0-9_.]{2,}", prompt.casefold()))
    if not focus:
        return []
    ranked, edges, continuations = {}, [], set()
    for row in chunks.values():
        if row["chunk_id"] not in allowed or row["metadata"]["title"] not in titles:
            continue
        locations = row.get("source_locations", [])
        text = row["text"].casefold()
        if any("table" in loc for loc in locations):
            keys = re.findall(r"(?m)^第 \d+ 行：单元格 1：([^；\n]+)", text)
            if focus.intersection(key.strip() for key in keys):
                ranked[row["chunk_id"]] = 2
        pages = {loc["page"] for loc in locations if "from_bbox" in loc}
        if len(pages) != 1:
            continue
        scope = row["revision_id"], next(iter(pages))
        for left, right in re.findall(r"(?m)^([^\n]+) → ([^\n]+)$", text):
            edges.append((row["chunk_id"], scope, left, right))
            if left in focus or right in focus:
                ranked[row["chunk_id"]] = 2
                if left in focus:
                    continuations.add((scope, right, "out"))
                if right in focus:
                    continuations.add((scope, left, "in"))
    for identity, scope, left, right in edges:
        if (scope, left, "out") in continuations or (scope, right, "in") in continuations:
            ranked.setdefault(identity, 1)
    return [
        {"chunk_id": identity, "score": score}
        for identity, score in sorted(ranked.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def fuse(routes: dict[str, list[dict]], k: int = 60) -> list[dict]:
    """No score mixing; repeated hits in one route contribute only once."""
    combined = {}
    for route, hits in routes.items():
        weight = STRUCTURED_FOCUS_WEIGHT if route == "structured_focus" else 1
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
            row["rrf_score"] += weight / (k + rank)
            row["routes"][route] = {"rank": rank, "raw_score": hit["score"]}
    return sorted(combined.values(), key=lambda row: (-row["rrf_score"], row["chunk_id"]))
