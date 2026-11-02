"""Strict UTF-8 Markdown/frontmatter and TXT/sidecar loading with exact source text."""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator

MAX_BYTES = 2 * 1024 * 1024


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$")
    title: str = Field(min_length=1, max_length=200)
    app_snapshot: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")
    data_kind: Literal["simulated", "business"]
    feature_status: Literal["delivered", "developing", "planned"]
    updated_at: date
    external_processing_allowed: StrictBool

    @field_validator("updated_at", mode="before")
    @classmethod
    def iso_date_only(cls, value):
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use an ISO calendar date")
        return date.fromisoformat(value)


@dataclass(frozen=True)
class Issue:
    file: str
    code: str
    location: str = ""


class IngestError(Exception):
    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("Document preparation failed")


@dataclass(frozen=True)
class LoadedDocument:
    source_path: str
    source_format: str
    metadata: Metadata
    raw_text: str
    body_start: int


class UniqueSafeLoader(yaml.SafeLoader):
    """Reject duplicate keys, YAML aliases and merges instead of silent overwrites."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise yaml.YAMLError("Aliases are unsupported")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in mapping:
                raise yaml.YAMLError("Invalid or duplicate key")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_utf8(path: Path, root: Path) -> str:
    # Never follow symlinks/junctions outside the user-selected input directory.
    if not path.resolve().is_relative_to(root):
        raise IngestError([Issue(path.name, "source_outside_root")])
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise IngestError([Issue(path.name, "file_too_large")])
        result = content.decode("utf-8")
        if "\x00" in result:
            raise IngestError([Issue(path.name, "nul_in_text")])
        return result
    except (OSError, UnicodeError) as exc:
        code = "invalid_utf8" if isinstance(exc, UnicodeError) else "file_unreadable"
        raise IngestError([Issue(path.name, code)]) from None


def load_document(path: Path, root: Path) -> LoadedDocument:
    raw = read_utf8(path, root)
    body_start = 1 if raw.startswith("\ufeff") else 0
    suffix = path.suffix.lower()
    metadata_file = path
    try:
        if suffix == ".md":
            lines = raw[body_start:].splitlines(keepends=True)
            if not lines or lines[0].strip() != "---":
                raise IngestError([Issue(path.name, "missing_frontmatter")])
            closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
            if closing is None:
                raise IngestError([Issue(path.name, "unclosed_frontmatter")])
            payload = yaml.load("".join(lines[1:closing]), Loader=UniqueSafeLoader)
            body_start += sum(map(len, lines[: closing + 1]))
        elif suffix == ".txt":
            metadata_file = path.with_suffix(".meta.json")
            payload = json.loads(
                read_utf8(metadata_file, root).lstrip("\ufeff"), object_pairs_hook=unique_json
            )
        else:
            raise IngestError([Issue(path.name, "unsupported_format")])
        metadata = Metadata.model_validate(payload)
    except ValidationError as exc:
        raise IngestError(
            [
                Issue(metadata_file.name, "invalid_metadata", ".".join(map(str, item["loc"])))
                for item in exc.errors()
            ]
        ) from None
    except (yaml.YAMLError, ValueError, RecursionError):
        raise IngestError([Issue(metadata_file.name, "invalid_metadata_syntax")]) from None
    body = raw[body_start:]
    if not body.strip():
        raise IngestError([Issue(path.name, "empty_body")])
    # Keep a simple, unambiguous line-coordinate contract for LF and CRLF.
    if "\r" in raw.replace("\r\n", ""):
        raise IngestError([Issue(path.name, "unsupported_bare_cr")])
    return LoadedDocument(path.relative_to(root).as_posix(), suffix[1:], metadata, raw, body_start)


def load_source(source: Path) -> list[LoadedDocument]:
    source = source.resolve()
    if not source.exists():
        raise IngestError([Issue(source.name, "source_not_found")])
    root = source if source.is_dir() else source.parent
    paths = (
        sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"})
        if source.is_dir()
        else [source]
    )
    if not paths:
        raise IngestError([Issue(source.name, "no_supported_documents")])
    documents, issues, keys = [], [], set()
    for path in paths:
        try:
            doc = load_document(path, root)
            if doc.metadata.source_key in keys:
                issues.append(Issue(doc.source_path, "duplicate_source_key"))
            keys.add(doc.metadata.source_key)
            documents.append(doc)
        except IngestError as exc:
            relative_parent = path.relative_to(root).parent
            issues.extend(
                Issue((relative_parent / i.file).as_posix(), i.code, i.location) for i in exc.issues
            )
    if len({(d.metadata.app_snapshot, d.metadata.data_kind) for d in documents}) > 1:
        issues.append(Issue(source.name, "mixed_snapshot_or_data_kind"))
    if issues:
        raise IngestError(issues)
    return documents
