"""Render bounded page evidence from the same reviewed PDF revision as a citation."""

from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy.orm import Session

from debug_rag.errors import RagError
from debug_rag.ingestion.readers import MAX_BINARY, MAX_PAGES
from debug_rag.storage.sqlite import DocumentOrigin

MAX_IMAGES = 2
MAX_SIDE = 1280
MAX_IMAGE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class PageImage:
    png: bytes
    width: int
    height: int


def page_locations(row):
    return [
        loc
        for loc in row.get("source_locations", [])
        if loc["format"] == "pdf" and type(loc.get("page")) is int and 1 <= loc["page"] <= MAX_PAGES
    ]


def render_page(engine, row, page_number):
    if page_number not in {loc["page"] for loc in page_locations(row)}:
        raise RagError("visual_page_not_found", "该引用没有关联此 PDF 页。", 404)
    with Session(engine) as session:
        origin = session.get(DocumentOrigin, row["revision_id"])
        if (
            origin is None
            or not origin.manifest.get("reviewed")
            or origin.manifest.get("original_file") != "original.pdf"
            or len(origin.original_bytes) > MAX_BINARY
            or origin.manifest.get("original_sha256") != row.get("original_sha256")
            or sha256(origin.original_bytes).hexdigest() != row.get("original_sha256")
        ):
            raise RagError("visual_source_integrity_failed", "PDF 原件无法通过版本校验。", 409)
        raw = origin.original_bytes
    try:
        import pymupdf
    except ImportError:
        raise RagError("pdf_reader_not_installed", "需要本机 PDF 渲染依赖。", 503) from None
    try:
        with pymupdf.open(stream=raw, filetype="pdf") as pdf:
            if pdf.needs_pass or not page_number <= len(pdf) <= MAX_PAGES:
                raise ValueError("unavailable page")
            page = pdf[page_number - 1]
            factor = (MAX_SIDE - 1) / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(factor, factor), alpha=False)
            png = pix.tobytes("png")
            if not png or len(png) > MAX_IMAGE_BYTES:
                raise RagError("visual_image_budget_exceeded", "单页图像超过视觉预算。", 422)
            return PageImage(png, pix.width, pix.height)
    except RagError:
        raise
    except Exception:
        raise RagError("visual_page_render_failed", "关联的 PDF 页无法渲染。", 422) from None


def select_images(engine, text_evidence, top_candidates):
    ranked = {}
    for origin, rows in (("text_context", text_evidence), ("fusion_top5", top_candidates)):
        from_candidates = origin == "fusion_top5"
        # Use structured candidates to supplement a PDF context without replacing its text.
        if from_candidates and not ranked:
            break
        for index, row in enumerate(rows):
            for loc in page_locations(row):
                structured = any(key in loc for key in ("from_bbox", "table", "image"))
                if from_candidates and not structured:
                    continue
                page = loc["page"]
                key = row["revision_id"], page
                priority = (not structured, from_candidates, index, page)
                if key not in ranked or priority < ranked[key][0]:
                    ranked[key] = (priority, row, origin)
    selected = []
    pages = sorted(ranked.items(), key=lambda entry: entry[1][0])
    for (_, page), (priority, row, origin) in pages[:MAX_IMAGES]:
        image = render_page(engine, row, page)
        identity = f"E{len(text_evidence) + len(selected) + 1}"
        info = {
            "evidence_id": identity,
            "chunk_id": row["chunk_id"],
            "revision_id": row["revision_id"],
            "metadata": row["metadata"],
            "original_sha256": row["original_sha256"],
            "source_locations": [{"format": "pdf", "page": page}],
            "visual_page": page,
            "selection_origin": origin,
            "image_sha256": sha256(image.png).hexdigest(),
            "width": image.width,
            "height": image.height,
            "bytes": len(image.png),
        }
        if origin == "fusion_top5":
            info["fusion_rank"] = priority[2] + 1
        selected.append((info, image))
    return selected
