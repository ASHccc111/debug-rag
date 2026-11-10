import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy.orm import Session

from debug_rag.ingestion.documents import IngestError, load_source
from debug_rag.ingestion.readers import (
    ParseError,
    digest,
    export_document,
    parse_binary,
    review_document,
)
from debug_rag.ingestion.service import prepare_documents
from debug_rag.retrieval.indexing import snapshot
from debug_rag.storage.sqlite import DocumentOrigin, DocumentRevision

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
META = {
    "source_key": "binary-demo",
    "title": "独立模拟导出规范",
    "app_snapshot": "demo-v1",
    "data_kind": "simulated",
    "feature_status": "delivered",
    "updated_at": "2026-11-03",
    "external_processing_allowed": False,
}


def sidecar(path):
    path.with_suffix(".meta.json").write_text(
        json.dumps(META, ensure_ascii=False), encoding="utf-8"
    )


def make_docx(path, *, image=False, merged=False, extra=""):
    span = '<w:gridSpan w:val="2"/>' if merged else ""
    body = f'''<w:document xmlns:w="{W}"><w:body>
      <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>文件导出</w:t></w:r></w:p>
      <w:p><w:r><w:t>取消导出后清理临时副本，保留用户保存的文件。</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:tcPr>{span}</w:tcPr><w:p><w:r><w:t>状态</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>处理</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>取消</w:t></w:r></w:p></w:tc>
      <w:tc><w:p><w:r><w:t>清理临时副本</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      {extra}<w:sectPr/></w:body></w:document>'''
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", body)
        if image:
            archive.writestr("word/media/mock.png", b"independent-test-placeholder")
    sidecar(path)
    return path


def test_docx_structure_review_and_ingest_origin_survive_source_removal(environment, tmp_path):
    _, engine, *_ = environment
    path = make_docx(tmp_path / "source.docx")
    original = path.read_bytes()
    exported = export_document(path, tmp_path / "parsed")
    canonical = Path(exported["document"])
    text = canonical.read_text(encoding="utf-8")
    assert "# 文件导出" in text and "单元格 2：清理临时副本" in text
    with pytest.raises(IngestError) as caught:
        prepare_documents(engine, "binary", canonical.parent)
    assert caught.value.issues[0].code == "document_review_required"
    review_document(canonical)
    prepared = prepare_documents(engine, "binary", canonical.parent)
    repeated = prepare_documents(engine, "binary", canonical.parent)
    assert repeated["created_revisions"] == 0 and repeated["reused_generation"]
    with Session(engine) as session:
        origin = session.query(DocumentOrigin).one()
        assert origin.original_bytes == original
        revision = session.get(DocumentRevision, origin.revision_id)
        assert revision.raw_text == canonical.read_bytes().decode("utf-8")
    # Retrieval uses persisted originals/maps, not a live path to the input file.
    path.unlink()
    _, chunks = snapshot(engine, "binary", prepared["generation_id"], include_parents=True)
    assert chunks and all(row["original_sha256"] == digest(original) for row in chunks)
    assert all(row["source_locations"] for row in chunks)
    assert any(any(loc.get("body_index") == 3 for loc in row["source_locations"]) for row in chunks)


@pytest.mark.parametrize("damage", ["canonical", "original", "map", "outside"])
def test_review_rejects_changed_or_out_of_bundle_sources(tmp_path, damage):
    exported = export_document(make_docx(tmp_path / "a.docx"), tmp_path / "out")
    path = Path(exported["document"])
    manifest_path = path.with_suffix(".origin.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if damage == "canonical":
        path.write_text(path.read_text(encoding="utf-8") + "伪造补充", encoding="utf-8")
    elif damage == "original":
        (path.parent / "original.docx").write_bytes(b"changed")
    elif damage == "map":
        manifest["blocks"][0]["start_char"] += 1
    else:
        manifest["original_file"] = "../../a.docx"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ParseError, match="document_origin_integrity_failed"):
        review_document(path)


def test_images_and_merged_cells_are_explicit_and_never_auto_accepted(tmp_path):
    exported = export_document(
        make_docx(tmp_path / "a.docx", image=True, merged=True), tmp_path / "out"
    )
    path = Path(exported["document"])
    assert "images_require_ocr_or_manual_description" in exported["warnings"]
    assert "merged_cells_require_review" in exported["warnings"]
    assert list((path.parent / "assets").iterdir())
    with pytest.raises(ParseError, match="unresolved_review_items"):
        review_document(path)
    reviewed = review_document(path, accept_incomplete=True)
    assert reviewed["accepted_incomplete"]
    doc = load_source(path.parent)[0]
    assert doc.origin["manifest"]["warnings"] == exported["warnings"]


def test_zip_expansion_and_entities_are_rejected(tmp_path, monkeypatch):
    from debug_rag.ingestion import readers

    path = make_docx(tmp_path / "a.docx")
    monkeypatch.setattr(readers, "MAX_EXPANDED", 10)
    with pytest.raises(ParseError, match="docx_expansion_limit"):
        parse_binary(path)
    monkeypatch.setattr(readers, "MAX_EXPANDED", 100_000)
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY y "expanded">]><x/>')
    with pytest.raises(ParseError, match="unsafe_docx_xml"):
        parse_binary(path)


def test_input_binary_in_ingest_is_not_silently_skipped(tmp_path):
    make_docx(tmp_path / "a.docx")
    with pytest.raises(IngestError) as caught:
        load_source(tmp_path)
    assert caught.value.issues[0].code == "binary_requires_parse_review"


def test_exported_text_without_mapping_cannot_bypass_review(tmp_path):
    exported = export_document(make_docx(tmp_path / "a.docx"), tmp_path / "out")
    path = Path(exported["document"])
    path.with_suffix(".origin.json").unlink()
    with pytest.raises(IngestError) as caught:
        load_source(path)
    assert caught.value.issues[0].code == "document_origin_missing"


def test_auto_numbering_is_preserved_as_locator_and_requires_review(tmp_path):
    path = make_docx(
        tmp_path / "a.docx",
        extra=(
            '<w:p><w:pPr><w:numPr><w:ilvl w:val="1"/><w:numId w:val="7"/>'
            "</w:numPr></w:pPr><w:r><w:t>编号步骤。</w:t></w:r></w:p>"
        ),
    )
    parsed = parse_binary(path)
    numbered = next(block for block in parsed.blocks if block["text"] == "编号步骤。")
    assert numbered["locator"]["numbering"] == {"ilvl": "1", "numId": "7"}
    assert "automatic_numbering_requires_review" in parsed.warnings


def pdf(path, *, scan=False, encrypted=False):
    pymupdf = pytest.importorskip("pymupdf")

    document = pymupdf.open()
    page = document.new_page()
    if scan:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
        pix.clear_with(255)
        page.insert_image(pymupdf.Rect(30, 30, 300, 300), stream=pix.tobytes("png"))
    else:
        page.insert_text(
            (40, 40), "Independent simulation: cancel export and clean temporary copies."
        )
        for x in (40, 200, 360):
            page.draw_line((x, 80), (x, 160))
        for y in (80, 120, 160):
            page.draw_line((40, y), (360, y))
        for point, text in [
            ((50, 100), "Status"),
            ((210, 100), "Action"),
            ((50, 140), "export.cancel_state"),
            ((210, 140), "Clean temporary copy"),
        ]:
            page.insert_text(point, text, fontsize=10)
    if encrypted:
        document.save(
            path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="fixture", user_pw="fixture"
        )
    else:
        document.save(path)
    document.close()
    sidecar(path)
    return path


def test_pdf_text_table_page_bbox_and_preview(tmp_path):
    path = pdf(tmp_path / "a.pdf")
    parsed = parse_binary(path)
    tables = [block for block in parsed.blocks if block["kind"] == "table"]
    assert len(tables) == 1
    assert tables[0]["cells"][1][0] == "export.cancel_state"
    assert tables[0]["cells"][1][1] == "Clean temporary copy"
    assert tables[0]["locator"]["page"] == 1 and len(tables[0]["locator"]["bbox"]) == 4
    assert not any(
        block["kind"] == "paragraph" and block["text"] == "export.cancel_state"
        for block in parsed.blocks
    )
    assert parsed.assets["page-1.png"].startswith(b"\x89PNG")
    exported = export_document(path, tmp_path / "out")
    canonical = Path(exported["document"])
    review_document(canonical, accept_incomplete=True)
    assert load_source(canonical.parent)[0].origin["original"] == path.read_bytes()


def test_pdf_vector_arrow_direction_and_source_locations(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "flow.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        for box, point, label in (
            ((40, 60, 160, 100), (60, 85), "Stop task"),
            ((40, 150, 160, 190), (60, 175), "Check status"),
            ((210, 150, 330, 190), (230, 175), "Other task"),
        ):
            page.draw_rect(pymupdf.Rect(box))
            page.insert_text(point, label)
        page.draw_line((100, 150), (100, 104))
        page.draw_polyline(
            [(95, 107), (105, 107), (100, 100), (95, 107)], color=None, fill=(0, 0, 0)
        )
        page.draw_line((160, 170), (210, 170))
        document.save(path)
    sidecar(path)

    exported = export_document(path, tmp_path / "out")
    canonical = Path(exported["document"])
    review_document(canonical, accept_incomplete=True)
    manifest = load_source(canonical.parent)[0].origin["manifest"]
    assert manifest["parser_version"] == "structured-binary-v2"
    edges = [b for b in manifest["blocks"] if b["kind"] == "diagram_edge"]
    assert [edge["text"] for edge in edges] == ["Check status → Stop task"]
    assert edges[0]["locator"] == {
        "format": "pdf",
        "page": 1,
        "bbox": [95.0, 100.0, 105.0, 150.0],
        "from_bbox": [40.0, 150.0, 160.0, 190.0],
        "to_bbox": [40.0, 60.0, 160.0, 100.0],
    }


def test_old_pdf_parser_bundle_still_loads(tmp_path):
    exported = export_document(pdf(tmp_path / "legacy.pdf"), tmp_path / "out")
    canonical = Path(exported["document"])
    manifest_path = Path(exported["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["parser_version"] = "structured-binary-v1"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    review_document(canonical, accept_incomplete=True)
    assert load_source(canonical.parent)[0].origin["manifest"]["parser_version"] == (
        "structured-binary-v1"
    )


def test_scan_only_pdf_requires_ocr_and_cannot_be_ingested_as_text(tmp_path):
    exported = export_document(pdf(tmp_path / "scan.pdf", scan=True), tmp_path / "out")
    assert "page_1_requires_ocr_review" in exported["warnings"]
    with pytest.raises(ParseError, match="no_extracted_text_requires_ocr"):
        review_document(Path(exported["document"]), accept_incomplete=True)


def test_empty_table_labels_are_not_source_text(tmp_path):
    path = tmp_path / "empty.docx"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'''<w:document xmlns:w="{W}"><w:body>
        <w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>
        </w:body></w:document>''',
        )
    sidecar(path)
    exported = export_document(path, tmp_path / "out")
    with pytest.raises(ParseError, match="no_extracted_text_requires_ocr"):
        review_document(Path(exported["document"]), accept_incomplete=True)


def test_encrypted_pdf_refused_without_guessing_password(tmp_path):
    with pytest.raises(ParseError, match="encrypted_pdf"):
        parse_binary(pdf(tmp_path / "a.pdf", encrypted=True))


def test_parser_cli_produces_bundle_without_creating_database(tmp_path, monkeypatch, capsys):
    from debug_rag import cli
    from debug_rag.settings import Settings

    settings = Settings(_env_file=None, runtime_dir=tmp_path / "unused-db")
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    path = make_docx(tmp_path / "a.docx")
    assert cli.main(["parse", "--source", str(path), "--output", str(tmp_path / "out")]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert not settings.sqlite_path.exists()
    assert cli.main(["review-parse", "--source", exported["document"]]) == 0


def test_original_blob_tampering_is_rejected_by_snapshot(environment, tmp_path):
    from debug_rag.errors import RagError

    _, engine, *_ = environment
    exported = export_document(make_docx(tmp_path / "a.docx"), tmp_path / "out")
    path = Path(exported["document"])
    review_document(path)
    prepared = prepare_documents(engine, "binary", path.parent)
    with Session(engine) as session, session.begin():
        session.query(DocumentOrigin).one().original_bytes = b"tampered"
    with pytest.raises(RagError) as caught:
        snapshot(engine, "binary", prepared["generation_id"])
    assert caught.value.code == "source_integrity_failed"
