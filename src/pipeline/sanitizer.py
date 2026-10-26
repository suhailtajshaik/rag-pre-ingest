"""Ordered, pure markdown cleanup; clean output contains content only."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict

from rag_pre_ingest.models.document import Block, Cell, DocumentResult, Page, Warning
from rag_pre_ingest.pipeline.layout_preparation import (  # compatibility exports
    _merge_wrapped as _merge_wrapped,
)
from rag_pre_ingest.pipeline.layout_preparation import (
    merge_list_continuations as merge_list_continuations,
)

_LIST = re.compile(r"^\s*(?:[-+*•◦▪‣–—]\s+|\d+[.)]\s+)")
_PREFIXES = {
    "well",
    "self",
    "state",
    "non",
    "pre",
    "post",
    "re",
    "co",
    "ex",
    "half",
    "full",
    "part",
}


def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        character
        for character in text
        if not unicodedata.category(character) == "Cc" or character in "\n\t"
    )
    return "\n".join(re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")).strip()


def join_lines(text: str) -> str:
    """Join wrapped prose while keeping paragraph, heading, list and hyphen boundaries."""
    lines = text.split("\n")
    output: list[str] = []
    for line in lines:
        if (
            output
            and output[-1]
            and line
            and not line.startswith("#")
            and not output[-1].startswith("#")
            and not _LIST.match(line)
            and not _LIST.match(output[-1])
        ):
            separator = "\n" if output[-1].endswith(("-", "\u00ad")) else " "
            output[-1] += separator + line
        else:
            output.append(line)
    return "\n".join(output)


def repair_hyphens(text: str) -> str:
    """Soft hyphens are discretionary; preserve common semantic hyphen prefixes."""
    text = re.sub(r"\u00ad\s*\n\s*", "", text).replace("\u00ad", "")

    def repair(match: re.Match[str]) -> str:
        left, right = match.group(1), match.group(2)
        keep = left.casefold() in _PREFIXES or "-" in left or len(left) < 3
        return left + ("-" if keep else "") + right

    return re.sub(r"([\w-]+)-\s*\n\s*([a-z][\w]*)", repair, text)


def normalize_lists(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"^\s*[-+*•◦▪‣–—]\s+", "- ", line)
        line = re.sub(r"^\s*(\d+)\)\s+", r"\1. ", line)
        lines.append(line)
    return "\n".join(lines)


def render_table(cells: list[Cell], rows: int, columns: int, *, header: bool = True) -> str:
    if rows <= 0 or columns <= 0:
        return ""
    grid = [[""] * columns for _ in range(rows)]
    for cell in cells:
        if 0 <= cell.row < rows and 0 <= cell.col < columns:
            grid[cell.row][cell.col] = (
                normalize_unicode(cell.text).replace("|", "\\|").replace("\n", " ")
            )
    lines = ["| " + " | ".join(row) + " |" for row in grid]
    if not header:
        lines.insert(0, "| " + " | ".join([""] * columns) + " |")
    lines.insert(1, "| " + " | ".join(["---"] * columns) + " |")
    return "\n".join(lines)


def collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text).strip()


def rank_headings(pages: list[Page]) -> list[Page]:
    result = [page.model_copy(deep=True) for page in pages]
    text_blocks = [
        block
        for page in result
        for block in page.blocks
        if block.type in {"paragraph", "heading"} and block.source != "caption"
    ]
    weights: Counter[float] = Counter()
    for block in text_blocks:
        if block.font_size is not None:
            weights[round(block.font_size, 1)] += max(len(block.text), 1)
    if not weights:
        return result
    body = max(weights, key=lambda size: (weights[size], -size))
    sizes = sorted(
        {
            round(block.font_size, 1)
            for block in text_blocks
            if block.font_size is not None and block.font_size > body * 1.15
        },
        reverse=True,
    )
    for block in text_blocks:
        if block.type == "heading" and block.level:
            continue
        if len(block.text) > 160 or "\n" in block.text:
            continue
        size = round(block.font_size or body, 1)
        if size in sizes:
            block.type, block.level = "heading", min(sizes.index(size) + 1, 6)
        elif (block.font_weight or 0) >= 600 and size >= body:
            block.type, block.level = "heading", min(len(sizes) + 1, 6)
    return result


def _margin(block: Block, page: Page, fraction: float) -> str | None:
    if page.height <= 0:
        return None
    if block.bbox[3] <= page.height * fraction:
        return "header"
    if block.bbox[1] >= page.height * (1 - fraction):
        return "footer"
    return None


def strip_repeating(
    pages: list[Page],
    min_pages: int = 2,
    margin_fraction: float = 0.12,
    repeat_fraction: float = 0.6,
) -> list[Page]:
    """Retain marginal blocks in JSON while excluding repeated boilerplate from markdown."""
    result = [page.model_copy(deep=True) for page in pages]
    occurrences: dict[tuple[str, str, int, int], set[int]] = defaultdict(set)

    def key(block: Block, page: Page, region: str) -> tuple[str, str, int, int]:
        text = normalize_unicode(block.text).casefold()
        if re.fullmatch(r"(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?", text):
            text = "<page-number>"
        return (
            region,
            text,
            round(block.bbox[0] / max(page.width, 1) * 20),
            round(block.bbox[1] / max(page.height, 1) * 50),
        )

    for page in result:
        for block in page.blocks:
            region = _margin(block, page, margin_fraction)
            if region and block.type not in {"image", "table"} and block.text.strip():
                occurrences[key(block, page, region)].add(page.page_number)
    required = max(min_pages, math.ceil(len(result) * repeat_fraction))
    for page in result:
        for block in page.blocks:
            region = _margin(block, page, margin_fraction)
            if region and len(occurrences.get(key(block, page, region), set())) >= required:
                block.type = "header" if region == "header" else "footer"
                block.markdown = ""
    return result


def sanitize_document(document: DocumentResult) -> DocumentResult:
    result = document.model_copy(deep=True)
    # Normalize first, then join wrapped geometry before the text-only steps.
    for page in result.pages:
        for block in page.blocks:
            if block.markdown.startswith("```"):
                continue
            block.text = normalize_unicode(block.text)
    result.pages = rank_headings(result.pages)
    for page in result.pages:
        for block in page.blocks:
            if block.markdown.startswith("```"):
                continue
            if block.type == "image" or block.is_decorative:
                block.markdown = ""
                continue
            joined = join_lines(block.text)
            if re.search(r"[\w-]+-\s*\n\s*[a-z]", joined):
                result.warnings.append(
                    Warning(
                        page_number=page.page_number,
                        code="hyphenation_uncertain",
                        message="Line-end hyphen repair used a provisional spelling heuristic.",
                    )
                )
            block.text = normalize_lists(repair_hyphens(joined))
            if block.type == "table":
                block.markdown = render_table(
                    block.cells,
                    block.rows or 0,
                    block.columns or 0,
                    header=any(cell.is_header for cell in block.cells),
                )
            elif block.type == "heading":
                block.markdown = "#" * (block.level or 1) + " " + block.text
            elif block.type == "list":
                indent = len(block.markdown) - len(block.markdown.lstrip(" "))
                marker = re.match(r"^\s*((?:[-+*]|\d+\.)\s+)", block.markdown)
                content = block.text
                if not _LIST.match(content) and marker:
                    content = marker.group(1) + content
                block.markdown = " " * indent + content
            else:
                if _LIST.match(block.text):
                    block.type = "list"
                block.markdown = block.text
    result.pages = strip_repeating(result.pages)
    path: list[str] = []
    for page in result.pages:
        for block in page.blocks:
            if block.type == "heading":
                level = block.level or 1
                path = path[: level - 1] + [block.text]
            block.heading_path = list(path)
    result.markdown = collapse_blank_lines(
        "\n\n".join(
            block.markdown
            for page in result.pages
            for block in page.blocks
            if block.type not in {"image", "header", "footer"} and block.markdown
        )
    )
    return result
