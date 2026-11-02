"""Markdown token line maps select boundaries; chunks always slice original text."""

from bisect import bisect_right
from dataclasses import dataclass
from importlib.metadata import version

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from debug_rag.ingestion.documents import LoadedDocument


class ChunkConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    parser_version: str = "markdown-lines-v1"
    parser_engine_version: str = Field(default_factory=lambda: version("markdown-it-py"))
    parent_chars: int = Field(default=1600, ge=200, le=10000)
    child_chars: int = Field(default=600, ge=100, le=2000)

    @model_validator(mode="after")
    def limits(self):
        if self.child_chars > self.parent_chars:
            raise ValueError("Child limit must not exceed parent limit")
        return self


@dataclass(frozen=True)
class Chunk:
    kind: str
    ordinal: int
    parent_ordinal: int | None
    section_path: list[str]
    text: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    continuation: bool


def line_starts(text: str) -> list[int]:
    return [0] + [i + 1 for i, char in enumerate(text) if char == "\n"]


def partition(text: str, start: int, end: int, boundaries: list[int], limit: int):
    """Prefer complete blocks; for an oversized block prefer a line/sentence boundary."""
    cursor = start
    while cursor < end:
        cap = min(cursor + limit, end)
        candidates = [point for point in boundaries if cursor < point <= cap]
        stop = cap if cap == end else max(candidates, default=cursor)
        if stop == cursor:
            # Don't split CRLF or fabricate closing fences in the preserved source.
            fragment = text[cursor:cap]
            offset = fragment.rfind("\n") + 1
            if offset < limit // 2:
                offsets = [fragment.rfind(mark) + 1 for mark in "。！？；"]
                offset = max(offsets)
            stop = cursor + offset if offset >= limit // 2 else cap
            if stop < end and text[stop - 1 : stop + 1] == "\r\n":
                stop -= 1
        yield cursor, stop
        cursor = stop


def chunk_document(doc: LoadedDocument, config: ChunkConfig) -> list[Chunk]:
    raw, base = doc.raw_text, doc.body_start
    body = raw[base:]
    offsets = line_starts(body)

    def position(line):
        return base + (offsets[line] if line < len(offsets) else len(body))

    headings, blocks = [], []
    if doc.source_format == "md":
        tokens = MarkdownIt("commonmark", {"html": False}).enable("table").parse(body)
        for i, token in enumerate(tokens):
            if token.level == 0 and token.map:
                blocks.append((position(token.map[0]), position(token.map[1])))
                if token.type == "heading_open":
                    headings.append(
                        (position(token.map[0]), int(token.tag[1:]), tokens[i + 1].content)
                    )
    else:
        # TXT has no Markdown semantics. Blank lines delimit ordinary paragraphs.
        starts = [base]
        starts.extend(base + i + 1 for i in range(len(body) - 1) if body[i : i + 2] == "\n\n")
        # CRLF paragraph boundaries remain exact too.
        starts.extend(base + i + 4 for i in range(len(body)) if body[i : i + 4] == "\r\n\r\n")
        starts = sorted(set(starts + [len(raw)]))
        blocks = list(zip(starts, starts[1:]))
    sections, stack, cursor = [], [], base
    path = [doc.metadata.title]
    for point, level, title in headings:
        if point > cursor:
            sections.append((cursor, point, path))
        stack = [(depth, name) for depth, name in stack if depth < level]
        stack.append((level, title))
        path = [name for _, name in stack]
        cursor = point
    if cursor < len(raw):
        sections.append((cursor, len(raw), path))
    boundaries = sorted({point for pair in blocks for point in pair})
    raw_lines = line_starts(raw)
    chunks = []

    def add(kind, start, end, section_path, parent=None):
        ordinal = len(chunks)
        split_block = any(a < start < b or a < end < b for a, b in blocks)
        chunks.append(
            Chunk(
                kind,
                ordinal,
                parent,
                section_path,
                raw[start:end],
                start,
                end,
                bisect_right(raw_lines, start),
                bisect_right(raw_lines, end - 1),
                split_block,
            )
        )
        return ordinal

    for start, end, section_path in sections:
        if not raw[start:end].strip():
            continue
        for p_start, p_end in partition(raw, start, end, boundaries, config.parent_chars):
            parent = add("parent", p_start, p_end, section_path)
            for c_start, c_end in partition(raw, p_start, p_end, boundaries, config.child_chars):
                add("child", c_start, c_end, section_path, parent)
    return chunks
