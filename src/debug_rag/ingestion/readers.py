"""Reviewable DOCX/PDF extraction. Binary originals and canonical text are distinct.

No OCR or model is invoked. Images/scans/unsupported structures are explicit review
items, never silently counted as successfully recognized text.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

VERSION = "structured-binary-v1"
ORIGIN_MARKER = "<!-- debug-rag-structured-source: required-origin-v1 -->"
MAX_BINARY = 20 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024
MAX_PAGES = 100
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = "{" + NS["w"] + "}"


class ParseError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class ParsedDocument:
    blocks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    assets: dict[str, bytes] = field(default_factory=dict)

    def add(self, kind, text, locator, **extra):
        self.blocks.append({"kind": kind, "text": text, "locator": locator, **extra})


def digest(content):
    return hashlib.sha256(content).hexdigest()


def has_source_text(block):
    """Generated table labels and image placeholders are not source evidence."""
    if block["kind"] == "paragraph":
        return bool(block["text"].strip())
    if block["kind"] == "table":
        return any(
            bool((cell.get("text", "") if isinstance(cell, dict) else cell or "").strip())
            for row in block["cells"]
            for cell in row
        )
    return False


def xml(content):
    if (
        len(content) > 8 * 1024 * 1024
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise ParseError("unsafe_docx_xml")
    return ET.fromstring(content)


def paragraph_text(element):
    parts = []
    for node in element.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag in {W + "br", W + "cr"}:
            parts.append("\n")
        elif node.tag == W + "tab":
            parts.append("\t")
    return "".join(parts)


def read_docx(path):
    result = ParsedDocument()
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 10000 or sum(info.file_size for info in infos) > MAX_EXPANDED:
                raise ParseError("docx_expansion_limit")
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise ParseError("invalid_docx")
            document = xml(archive.read("word/document.xml"))
            styles = {}
            if "word/styles.xml" in names:
                for style in xml(archive.read("word/styles.xml")).findall("w:style", NS):
                    name = style.find("w:name", NS)
                    styles[style.get(W + "styleId")] = (
                        name.get(W + "val", "") if name is not None else ""
                    )
            body = document.find("w:body", NS)
            if body is None:
                raise ParseError("invalid_docx")
            for ordinal, node in enumerate(body):
                locator = {"format": "docx", "body_index": ordinal + 1}
                if node.tag == W + "p":
                    text = paragraph_text(node)
                    numbering = node.find("w:pPr/w:numPr", NS)
                    if numbering is not None:
                        locator["numbering"] = {
                            child.tag.rsplit("}", 1)[-1]: child.get(W + "val")
                            for child in numbering
                        }
                        result.warnings.append("automatic_numbering_requires_review")
                    style = node.find("w:pPr/w:pStyle", NS)
                    label = (
                        styles.get(style.get(W + "val"), style.get(W + "val", ""))
                        if style is not None
                        else ""
                    )
                    match = re.search(r"(?:heading|标题)\s*([1-6])", label, re.I)
                    if text.strip():
                        result.add(
                            "heading" if match else "paragraph",
                            text,
                            locator,
                            level=int(match[1]) if match else 0,
                        )
                elif node.tag == W + "tbl":
                    rows, merged = [], False
                    for row_id, row in enumerate(node.findall("w:tr", NS), 1):
                        cells = []
                        for col_id, cell in enumerate(row.findall("w:tc", NS), 1):
                            span = cell.find("w:tcPr/w:gridSpan", NS)
                            merge = cell.find("w:tcPr/w:vMerge", NS)
                            merged |= span is not None or merge is not None
                            cells.append(
                                {
                                    "row": row_id,
                                    "cell": col_id,
                                    "text": "\n".join(
                                        paragraph_text(p) for p in cell.findall("w:p", NS)
                                    ),
                                    "grid_span": span.get(W + "val") if span is not None else "1",
                                    "vertical_merge": merge.get(W + "val", "continue")
                                    if merge is not None
                                    else None,
                                }
                            )
                            if cell.find("w:tbl", NS) is not None:
                                result.warnings.append("nested_table_requires_review")
                        rows.append(cells)
                    text = "\n".join(
                        f"第 {i} 行：" + "；".join(f"单元格 {c['cell']}：{c['text']}" for c in row)
                        for i, row in enumerate(rows, 1)
                    )
                    result.add("table", text, locator, cells=rows)
                    if merged:
                        result.warnings.append("merged_cells_require_review")
                elif node.tag != W + "sectPr":
                    result.warnings.append("unsupported_docx_block")
            image_nodes = list(
                document.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
            )
            if image_nodes or any("word/media/" in name for name in names):
                result.warnings.append("images_require_ocr_or_manual_description")
                for i, name in enumerate(
                    sorted(n for n in names if n.startswith("word/media/") and not n.endswith("/")),
                    1,
                ):
                    ext = Path(name).suffix.lower()
                    asset = f"image-{i}{ext if re.fullmatch(r'\.[a-z0-9]{1,6}', ext) else '.bin'}"
                    result.assets[asset] = archive.read(name)
                    result.add(
                        "image",
                        "[图片内容未识别，不作为回答依据]",
                        {"format": "docx", "media_part": name},
                        asset=asset,
                    )
            for name in names:
                if re.match(
                    r"word/(header|footer|footnotes|endnotes|comments|charts|diagrams)", name
                ):
                    result.warnings.append("supplementary_docx_parts_require_review")
            if any(
                node.tag in {W + "del", W + "ins", W + "txbxContent"} for node in document.iter()
            ):
                result.warnings.append("tracked_changes_or_textboxes_require_review")
    except ParseError:
        raise
    except (BadZipFile, KeyError, OSError, ET.ParseError, RuntimeError):
        raise ParseError("invalid_docx") from None
    return result


def read_pdf(path):
    try:
        import pymupdf
    except ImportError:
        raise ParseError("pdf_reader_not_installed") from None
    result = ParsedDocument(warnings=["pdf_reading_order_and_tables_require_review"])
    try:
        with pymupdf.open(path) as document:
            if document.needs_pass:
                raise ParseError("encrypted_pdf")
            if not 1 <= len(document) <= MAX_PAGES:
                raise ParseError("pdf_page_limit")
            for number, page in enumerate(document, 1):
                result.add("heading", f"第 {number} 页", {"format": "pdf", "page": number}, level=1)
                tables = page.find_tables().tables
                areas = [pymupdf.Rect(table.bbox) for table in tables]
                ordered = []
                for table_id, table in enumerate(tables, 1):
                    cells = table.extract()
                    text = "\n".join(
                        f"第 {i} 行："
                        + "；".join(
                            f"单元格 {j}："
                            + (value if value is not None else "[合并/空单元格，待核对]")
                            for j, value in enumerate(row, 1)
                        )
                        for i, row in enumerate(cells, 1)
                    )
                    ordered.append(
                        (
                            table.bbox[1],
                            table.bbox[0],
                            "table",
                            text,
                            {
                                "format": "pdf",
                                "page": number,
                                "table": table_id,
                                "bbox": list(table.bbox),
                            },
                            {"cells": cells},
                        )
                    )
                for block in page.get_text("dict")["blocks"]:
                    if block["type"] != 0:
                        continue
                    for line in block["lines"]:
                        rect = pymupdf.Rect(line["bbox"])
                        if any(area.contains((rect.tl + rect.br) / 2) for area in areas):
                            continue
                        text = "".join(span["text"] for span in line["spans"])
                        if text.strip():
                            ordered.append(
                                (
                                    rect.y0,
                                    rect.x0,
                                    "paragraph",
                                    text,
                                    {"format": "pdf", "page": number, "bbox": list(rect)},
                                    {},
                                )
                            )
                for _, _, kind, text, locator, extra in sorted(
                    ordered, key=lambda row: (row[0], row[1])
                ):
                    result.add(kind, text, locator, **extra)
                images = page.get_image_info()
                for image_id, image in enumerate(images, 1):
                    result.add(
                        "image",
                        "[图片内容未识别，不作为回答依据]",
                        {
                            "format": "pdf",
                            "page": number,
                            "image": image_id,
                            "bbox": list(image["bbox"]),
                        },
                    )
                if images:
                    result.warnings.append("images_require_ocr_or_manual_description")
                if len(page.get_text().strip()) < 20:
                    result.warnings.append(f"page_{number}_requires_ocr_review")
                if page.get_drawings():
                    result.warnings.append("vector_graphics_require_visual_review")
                # Bounded page previews for human/OCR review; no external model call.
                if page.rect.width * page.rect.height > 12_000_000:
                    raise ParseError("pdf_page_pixel_limit")
                result.assets[f"page-{number}.png"] = page.get_pixmap(alpha=False).tobytes("png")
                if sum(len(data) for data in result.assets.values()) > MAX_EXPANDED:
                    raise ParseError("asset_expansion_limit")
    except ParseError:
        raise
    except Exception:
        raise ParseError("pdf_parse_failed") from None
    return result


def parse_binary(path):
    if path.stat().st_size > MAX_BINARY:
        raise ParseError("binary_file_too_large")
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise ParseError("unsupported_binary_format")
    parsed = read_pdf(path) if suffix == ".pdf" else read_docx(path)
    parsed.warnings = sorted(set(parsed.warnings))
    return parsed


def export_document(source, output):
    """Export immutable original + review draft + exact canonical block offsets."""
    from debug_rag.ingestion.documents import Metadata, read_utf8, unique_json

    source, output = source.resolve(), output.resolve()
    if source.is_symlink() or not source.is_file():
        raise ParseError("invalid_binary_source")
    metadata = Metadata.model_validate(
        json.loads(
            read_utf8(source.with_suffix(".meta.json"), source.parent),
            object_pairs_hook=unique_json,
        )
    )
    if source.stat().st_size > MAX_BINARY:
        raise ParseError("binary_file_too_large")
    original = source.read_bytes()
    parsed = parse_binary(source)
    if sum(len(data) for data in parsed.assets.values()) > MAX_EXPANDED:
        raise ParseError("asset_expansion_limit")
    header = (
        "---\n"
        + "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in metadata.model_dump(mode="json").items()
        )
        + "\n---\n"
    )
    canonical, blocks = header + ORIGIN_MARKER + "\n", []
    for block in parsed.blocks:
        label = "#" * min(6, block.get("level", 1)) + " " if block["kind"] == "heading" else ""
        # Each original block is fenced by an explicit locator heading.
        locator = block["locator"]
        if block["kind"] != "heading":
            position = (
                f"PDF 第 {locator['page']} 页"
                if locator["format"] == "pdf"
                else f"DOCX 正文块 {locator.get('body_index', '图片')}"
            )
            canonical += f"\n<!-- {position} / {block['kind']} -->\n"
        text = label + block["text"] + "\n\n"
        start = len(canonical)
        canonical += text
        blocks.append({**block, "start_char": start, "end_char": len(canonical)})
    content = canonical.encode("utf-8")
    if len(content) > 2 * 1024 * 1024:
        raise ParseError("canonical_text_limit")
    destination = output / (
        metadata.source_key + "-" + digest(original)[:12] + "-" + digest(content)[:8]
    )
    destination.mkdir(parents=True, exist_ok=False)
    original_name = "original" + source.suffix.lower()
    (destination / original_name).write_bytes(original)
    (destination / "document.md").write_bytes(content)
    assets = destination / "assets"
    if parsed.assets:
        assets.mkdir()
        for name, data in parsed.assets.items():
            (assets / name).write_bytes(data)
    manifest = {
        "parser_version": VERSION,
        "original_file": original_name,
        "original_sha256": digest(original),
        "canonical_sha256": digest(content),
        "reviewed": False,
        "accepted_incomplete": False,
        "warnings": parsed.warnings,
        "blocks": blocks,
        "assets": [
            {"file": "assets/" + name, "sha256": digest(data)}
            for name, data in parsed.assets.items()
        ],
    }
    (destination / "document.origin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "document": str(destination / "document.md"),
        "manifest": str(destination / "document.origin.json"),
        "warnings": parsed.warnings,
        "blocks": len(blocks),
        "review_required": True,
        "external_calls_executed": 0,
    }


def load_origin(path, raw, *, require_review=True):
    """Validate the binding; never follow original paths outside the bundle."""
    manifest_path = path.with_suffix(".origin.json")
    if not manifest_path.is_file():
        if ORIGIN_MARKER in raw:
            raise ParseError("document_origin_missing")
        return None
    try:
        if manifest_path.is_symlink() or manifest_path.stat().st_size > MAX_EXPANDED:
            raise ValueError()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest.get("blocks"), list) or not manifest["blocks"]:
            raise ValueError()
        original_path = (path.parent / manifest["original_file"]).resolve()
        if (
            not original_path.is_relative_to(path.parent.resolve())
            or original_path.stat().st_size > MAX_BINARY
        ):
            raise ValueError()
        original = original_path.read_bytes()
        if (
            manifest["canonical_sha256"] != digest(raw.encode("utf-8"))
            or manifest["original_sha256"] != digest(original)
            or manifest["parser_version"] != VERSION
        ):
            raise ValueError()
        last = 0
        for block in manifest["blocks"]:
            a, b = block["start_char"], block["end_char"]
            if (
                type(a) is not int
                or type(b) is not int
                or not 0 <= last <= a < b <= len(raw)
                or not isinstance(block["locator"], dict)
            ):
                raise ValueError()
            expected = (
                ("#" * min(6, block.get("level", 1)) + " " if block["kind"] == "heading" else "")
                + block["text"]
                + "\n\n"
            )
            if raw[a:b] != expected:
                raise ValueError()
            last = b
        for asset in manifest.get("assets", []):
            asset_path = (path.parent / asset["file"]).resolve()
            if (
                not asset_path.is_relative_to(path.parent.resolve())
                or asset_path.stat().st_size > MAX_EXPANDED
                or digest(asset_path.read_bytes()) != asset["sha256"]
            ):
                raise ValueError()
        if require_review and (
            manifest.get("reviewed") is not True
            or (manifest["warnings"] and manifest.get("accepted_incomplete") is not True)
        ):
            raise ParseError("document_review_required")
        return {"manifest": manifest, "original": original}
    except ParseError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise ParseError("document_origin_integrity_failed") from None


def review_document(path, *, accept_incomplete=False):
    raw = path.read_bytes().decode("utf-8")
    origin = load_origin(path, raw, require_review=False)
    if origin is None:
        raise ParseError("document_origin_missing")
    manifest = origin["manifest"]
    if not any(has_source_text(block) for block in manifest["blocks"]):
        raise ParseError("no_extracted_text_requires_ocr")
    if manifest["warnings"] and not accept_incomplete:
        raise ParseError("unresolved_review_items")
    manifest.update(reviewed=True, accepted_incomplete=bool(accept_incomplete))
    path.with_suffix(".origin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "reviewed": True,
        "accepted_incomplete": bool(accept_incomplete),
        "warnings": manifest["warnings"],
        "external_calls_executed": 0,
    }
