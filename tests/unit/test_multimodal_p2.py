from debug_rag.generation.grounding import compact_context, messages
from debug_rag.generation.provider import input_upper_bound
from debug_rag.retrieval.lexical import fuse, structured_focus


def test_structured_focus_keeps_linked_nodes_in_the_same_page_and_revision():
    chunks = {}
    for identity, text, revision, page in (
        ("a", "Check state → Archive", "r1", 2),
        ("b", "Archive → Complete", "r1", 2),
        ("c", "Archive → Discard", "r1", 3),
        ("d", "Archive → Reject", "r2", 2),
    ):
        chunks[identity] = {
            "chunk_id": identity,
            "metadata": {"title": "Orbit Flow"},
            "revision_id": revision,
            "source_locations": [{"page": page, "from_bbox": [0, 0, 1, 1]}],
            "text": text,
        }
    focus = structured_focus(chunks, "《Orbit Flow》从「Check state」出发的两步？", set(chunks))
    assert [item["chunk_id"] for item in focus] == ["a", "b"]
    assert structured_focus(chunks, "《Other Flow》从「Check state」出发？", set(chunks)) == []
    assert (
        fuse({"bm25": [{"chunk_id": "c", "score": 1}], "structured_focus": focus})[0]["chunk_id"]
        == "a"
    )


def test_compact_context_reserves_explicit_evidence_and_keeps_api_locations():
    metadata = {
        "title": "Orbit",
        "app_snapshot": "demo",
        "data_kind": "simulated",
        "feature_status": "delivered",
    }
    locations = [{"format": "pdf", "page": 2, "bbox": [1, 2, 3, 4]}] * 12
    baseline = {
        "metadata": metadata,
        "section_path": [],
        "source_locations": locations,
        "text": "generic " * 100,
        "chunk_id": "generic",
        "routes": {},
    }
    focused = {
        **baseline,
        "text": "verified " * 100,
        "chunk_id": "focused",
        "routes": {"structured_focus": {"rank": 1}},
    }
    budget = input_upper_bound(messages("Where?", [{**focused, "evidence_id": "E1"}], compact=True))
    selected = compact_context("Where?", [baseline, focused], budget, None)
    assert [row["chunk_id"] for row in selected] == ["focused"]
    assert selected[0]["source_locations"] == locations
    assert input_upper_bound(messages("Where?", selected, compact=True)) == budget
    assert input_upper_bound(messages("Where?", selected)) > budget
