"""Portable document result schema shared by readers, API and viewer."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Warning(BaseModel):
    page_number: int | None = None
    code: str
    message: str


class Confidence(BaseModel):
    average: float | None = None
    lowest_block: float | None = None


class Document(BaseModel):
    id: str
    file_name: str
    file_type: str
    file_hash: str
    page_count: int
    processed_at: datetime
    confidence: Confidence = Field(default_factory=Confidence)


class PageCounts(BaseModel):
    total: int = 0
    read: int = 0
    ocr: int = 0
    mixed: int = 0


class ImageCounts(BaseModel):
    total: int = 0
    decorative: int = 0
    with_ocr_text: int = 0


class TableCounts(BaseModel):
    total: int = 0
    with_merged_cells: int = 0


class WarningCounts(BaseModel):
    total: int = 0
    by_code: dict[str, int] = Field(default_factory=dict)


class Stats(BaseModel):
    pages: PageCounts = Field(default_factory=PageCounts)
    images: ImageCounts = Field(default_factory=ImageCounts)
    tables: TableCounts = Field(default_factory=TableCounts)
    headings: int = 0
    paragraphs: int = 0
    lists: int = 0
    warnings: WarningCounts = Field(default_factory=WarningCounts)
    duration_seconds: float = 0


class Cell(BaseModel):
    row: int
    col: int
    text: str
    is_header: bool = False
    row_span: int = 1
    col_span: int = 1


class Observation(BaseModel):
    """Immutable extraction evidence, never rewritten by layout or cleanup."""

    model_config = ConfigDict(frozen=True)
    id: str
    text: str
    bbox: tuple[float, float, float, float]
    source: Literal["read", "ocr", "caption"]
    confidence: float | None = None


class Region(BaseModel):
    """Accepted layout boundary with explicit ownership and provenance."""

    model_config = ConfigDict(frozen=True)
    id: str
    kind: Literal["card", "table", "text", "image"]
    bbox: tuple[float, float, float, float]
    observation_ids: tuple[str, ...] = ()
    confidence: float | None = None


class Block(BaseModel):
    id: str
    type: Literal["heading", "paragraph", "list", "table", "image", "header", "footer", "other"]
    level: int | None = None
    text: str = ""
    markdown: str = ""
    bbox: tuple[float, float, float, float]
    heading_path: list[str] = Field(default_factory=list)
    confidence: float | None = None
    source: Literal["read", "ocr", "caption"] = "read"
    layout_confidence: float | None = None
    region_id: str | None = None
    region_kind: Literal["card", "table", "text", "image"] | None = None
    region_bbox: tuple[float, float, float, float] | None = None
    merge_locked: bool = False
    observation_ids: tuple[str, ...] = ()
    observations: tuple[Observation, ...] = ()
    rows: int | None = None
    columns: int | None = None
    cells: list[Cell] = Field(default_factory=list)
    image_ref: str | None = None
    ocr_text: str | None = None
    caption: str | None = None
    description: str | None = None
    is_decorative: bool = False
    font_size: float | None = None
    font_weight: int | None = None


class Quality(BaseModel):
    character_count: int = 0
    garbage_share: float = 0
    image_coverage: float = 0
    words_per_area: float = 0
    needs_ocr: bool = False
    reasons: list[str] = Field(default_factory=list)


class Connector(BaseModel):
    """Visible directional evidence between identified source text blocks."""

    model_config = ConfigDict(frozen=True)
    source_block_id: str
    target_block_id: str
    bbox: tuple[float, float, float, float]
    direction: Literal["up", "down", "left", "right"]
    evidence: Literal["pixels"] = "pixels"


class Page(BaseModel):
    page_number: int
    width: float
    height: float
    method: Literal["read", "ocr", "mixed"] = "read"
    blocks: list[Block] = Field(default_factory=list)
    observations: tuple[Observation, ...] = ()
    regions: tuple[Region, ...] = ()
    connectors: tuple[Connector, ...] = ()
    quality: Quality | None = None
    words: list[Block] = Field(default_factory=list)
    ruling_lines: list[tuple[float, float, float, float]] = Field(default_factory=list)


class DocumentResult(BaseModel):
    document: Document
    stats: Stats
    markdown: str
    pages: list[Page]
    warnings: list[Warning] = Field(default_factory=list)
