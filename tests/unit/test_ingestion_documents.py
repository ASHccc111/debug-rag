import json

import pytest

from debug_rag.ingestion.documents import IngestError, load_document, load_source


def markdown(body="正文。\n", **changes):
    meta = {
        "source_key": "test-doc",
        "title": "测试文档",
        "app_snapshot": "demo-v1",
        "data_kind": "simulated",
        "feature_status": "delivered",
        "updated_at": "2026-10-25",
        "external_processing_allowed": False,
    }
    meta.update(changes)
    return (
        "---\n"
        + "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in meta.items()
        )
        + "\n---\n"
        + body
    )


def test_preserves_bom_crlf_and_txt_sidecar(tmp_path):
    path = tmp_path / "one.md"
    original = "\ufeff" + markdown("# 标题\n\n原文，不改写。\n").replace("\n", "\r\n")
    path.write_bytes(original.encode("utf-8"))
    doc = load_document(path, tmp_path)
    assert doc.raw_text == original
    assert doc.raw_text[doc.body_start :] == "# 标题\r\n\r\n原文，不改写。\r\n"
    path = tmp_path / "two.txt"
    path.write_bytes("\ufeff纯文本\r\n".encode("utf-8"))
    path.with_suffix(".meta.json").write_text(
        json.dumps(doc.metadata.model_dump(mode="json")), encoding="utf-8"
    )
    txt = load_document(path, tmp_path)
    assert txt.raw_text[txt.body_start :] == "纯文本\r\n"
    assert txt.metadata.external_processing_allowed is False


@pytest.mark.parametrize(
    "changes,field",
    [
        ({"feature_status": "maybe"}, "feature_status"),
        ({"external_processing_allowed": "false"}, "external_processing_allowed"),
        ({"updated_at": "2026-02-30"}, "updated_at"),
        ({"source_key": "../bad"}, "source_key"),
        ({"app_snapshot": ""}, "app_snapshot"),
        ({"unknown": True}, "unknown"),
    ],
)
def test_metadata_errors_identify_field_without_echoing_values(tmp_path, changes, field):
    path = tmp_path / "bad.md"
    path.write_text(markdown(**changes), encoding="utf-8")
    with pytest.raises(IngestError) as caught:
        load_document(path, tmp_path)
    assert caught.value.issues[0].code == "invalid_metadata"
    assert caught.value.issues[0].location == field


@pytest.mark.parametrize(
    "raw,code",
    [
        ("普通正文", "missing_frontmatter"),
        ("---\ntitle: x\n", "unclosed_frontmatter"),
        ("---\ntitle: x\ntitle: y\n---\n正文", "invalid_metadata_syntax"),
        ("---\nx: &a [*a]\n---\n正文", "invalid_metadata_syntax"),
        ("---\n!!python/object:os.system {}\n---\n正文", "invalid_metadata_syntax"),
        (markdown("\n\t"), "empty_body"),
    ],
)
def test_invalid_sources_fail_explicitly(tmp_path, raw, code):
    path = tmp_path / "bad.md"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(IngestError) as caught:
        load_document(path, tmp_path)
    assert caught.value.issues[0].code == code


def test_txt_sidecar_and_utf8_limits(tmp_path, monkeypatch):
    path = tmp_path / "one.txt"
    path.write_bytes(b"\xff")
    with pytest.raises(IngestError) as caught:
        load_document(path, tmp_path)
    assert caught.value.issues[0].code == "invalid_utf8"
    path.write_text("abc", encoding="utf-8")
    with pytest.raises(IngestError) as caught:
        load_document(path, tmp_path)
    assert caught.value.issues[0].file == "one.meta.json"
    monkeypatch.setattr("debug_rag.ingestion.documents.MAX_BYTES", 2)
    with pytest.raises(IngestError) as caught:
        load_document(path, tmp_path)
    assert caught.value.issues[0].code == "file_too_large"


def test_duplicate_keys_and_mixed_snapshot_reject_whole_batch(tmp_path):
    (tmp_path / "a.md").write_text(markdown(), encoding="utf-8")
    (tmp_path / "b.md").write_text(markdown(app_snapshot="demo-v2"), encoding="utf-8")
    with pytest.raises(IngestError) as caught:
        load_source(tmp_path)
    assert {i.code for i in caught.value.issues} == {
        "duplicate_source_key",
        "mixed_snapshot_or_data_kind",
    }


def test_path_outside_selected_root_is_rejected(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text(markdown(), encoding="utf-8")
    root = tmp_path / "selected"
    root.mkdir()
    with pytest.raises(IngestError) as caught:
        load_document(outside, root)
    assert caught.value.issues[0].code == "source_outside_root"
