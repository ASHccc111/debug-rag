import pytest
from test_ingestion_documents import markdown

from debug_rag.ingestion.chunking import ChunkConfig, chunk_document
from debug_rag.ingestion.documents import LoadedDocument, load_document


def check_locations(doc, chunks, config):
    parents = {c.ordinal: c for c in chunks if c.kind == "parent"}
    children = [c for c in chunks if c.kind == "child"]
    assert "".join(c.text for c in children) == doc.raw_text[doc.body_start :]
    for chunk in chunks:
        assert chunk.text == doc.raw_text[chunk.start_char : chunk.end_char]
        assert chunk.start_line == doc.raw_text.count("\n", 0, chunk.start_char) + 1
        assert chunk.end_line == doc.raw_text.count("\n", 0, chunk.end_char - 1) + 1
        limit = config.parent_chars if chunk.kind == "parent" else config.child_chars
        assert len(chunk.text) <= limit
        if chunk.kind == "child":
            parent = parents[chunk.parent_ordinal]
            assert parent.start_char <= chunk.start_char < chunk.end_char <= parent.end_char
            assert chunk.section_path == parent.section_path


def test_structure_ignores_headings_inside_code_and_preserves_table_list(tmp_path):
    body = (
        "# 主标题\n\n前言。\n\n## 接入\n\n```python\n# 不是标题\nx = 1\n```\n\n"
        "- 第一步\n  - 子步骤\n- 第二步\n\n"
        "| 字段 | 值 |\n| --- | --- |\n| 状态 | 正常 |\n\n### 验证\n\n观察结果。\n"
    )
    path = tmp_path / "one.md"
    path.write_text(markdown(body), encoding="utf-8")
    doc = load_document(path, tmp_path)
    config = ChunkConfig(child_chars=200)
    chunks = chunk_document(doc, config)
    check_locations(doc, chunks, config)
    assert [c.section_path for c in chunks if c.kind == "parent"] == [
        ["主标题"],
        ["主标题", "接入"],
        ["主标题", "接入", "验证"],
    ]
    assert any(
        "```python\n# 不是标题\nx = 1\n```" in c.text.replace("\r\n", "\n")
        for c in chunks
        if c.kind == "child"
    )
    assert any("| 状态 | 正常 |" in c.text for c in chunks if c.kind == "child")


@pytest.mark.parametrize("format", ["md", "txt"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_oversized_blocks_and_long_chinese_have_exact_coverage(tmp_path, format, newline):
    body = "# 标题\n\n```text\n" + "超长段落" * 500 + "\n```\n\n" + "说明。" * 400
    path = tmp_path / "one.md"
    raw = "\ufeff" + markdown(body).replace("\n", newline)
    path.write_bytes(raw.encode("utf-8"))
    loaded = load_document(path, tmp_path)
    doc = LoadedDocument(
        loaded.source_path, format, loaded.metadata, loaded.raw_text, loaded.body_start
    )
    config = ChunkConfig(parent_chars=500, child_chars=200)
    chunks = chunk_document(doc, config)
    check_locations(doc, chunks, config)
    assert any(c.continuation for c in chunks)
    assert all(not (c.text.endswith("\r")) for c in chunks)


def test_txt_does_not_treat_hash_as_markdown_heading(tmp_path):
    path = tmp_path / "one.md"
    path.write_text(markdown("# 普通文本\n\n下一段\n"), encoding="utf-8")
    loaded = load_document(path, tmp_path)
    doc = LoadedDocument(
        loaded.source_path, "txt", loaded.metadata, loaded.raw_text, loaded.body_start
    )
    config = ChunkConfig()
    chunks = chunk_document(doc, config)
    check_locations(doc, chunks, config)
    assert all(c.section_path == ["测试文档"] for c in chunks)
