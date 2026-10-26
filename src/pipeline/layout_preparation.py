"""Pure geometric text grouping, run before final reading order."""

from __future__ import annotations

import re

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.structure import can_merge, combine_provenance

_LIST = re.compile(r"^\s*(?:[-+*•◦▪‣–—]\s+|\d+[.)]\s+)")


def merge_list_continuations(page: Page) -> Page:
    """Attach close, aligned OCR continuation lines to their existing list item."""
    result = page.model_copy(deep=True)
    merged: list[Block] = []
    for block in result.blocks:
        if (
            block.type == "paragraph"
            and _LIST.match(block.text)
            and not block.markdown.startswith("```")
        ):
            block.type = "list"
        previous = merged[-1] if merged else None
        if previous is not None and not can_merge(previous, block):
            merged.append(block)
            continue
        if (
            previous is not None
            and previous.type == "list"
            and block.type == "paragraph"
            and previous.source == block.source == "ocr"
        ):
            a, b = previous.bbox, block.bbox
            height = min(a[3] - a[1], b[3] - b[1])
            gap = b[1] - a[3]
            aligned = (
                abs((a[0] + a[2] - b[0] - b[2]) / 2) <= height * 0.75
                or abs(a[0] - b[0]) <= height * 0.5
            )
            if (
                height > 0
                and -height * 0.5 <= gap <= height * 0.65
                and aligned
                and not _LIST.match(block.text)
                and not re.search(r"[.!?:;]$", previous.text.strip())
            ):
                combine_provenance(previous, block)
                previous.text += " " + block.text
                previous.bbox = (min(a[0], b[0]), a[1], max(a[2], b[2]), max(a[3], b[3]))
                continue
        merged.append(block)
    result.blocks = merged
    return result


def _merge_wrapped(page: Page) -> Page:
    result = page.model_copy(deep=True)
    merged: list[Block] = []
    for block in result.blocks:
        previous = merged[-1] if merged else None
        if previous is not None and not can_merge(previous, block):
            merged.append(block)
            continue
        if block.markdown.startswith("```") or (
            previous is not None and previous.markdown.startswith("```")
        ):
            merged.append(block)
            continue
        if previous is not None:
            line_height = max(previous.bbox[3] - previous.bbox[1], 8)
            gap = block.bbox[1] - previous.bbox[3]
            same_style = (
                previous.font_size is None
                or block.font_size is None
                or abs(previous.font_size - block.font_size) <= 1
            )
            horizontal_gap = block.bbox[0] - previous.bbox[2]
            current_height = max(block.bbox[3] - block.bbox[1], 8)
            baseline_distance = abs(
                (block.bbox[1] + block.bbox[3]) / 2 - (previous.bbox[1] + previous.bbox[3]) / 2
            )
            if (
                previous.type == block.type == "paragraph"
                and previous.source == block.source
                and block.source != "caption"
                and same_style
                and "\n" not in previous.text
                and "\n" not in block.text
                and baseline_distance <= min(line_height, current_height) * 0.5
                and -min(line_height, current_height) * 0.75
                <= horizontal_gap
                <= min(line_height, current_height) * 2
                and not _LIST.match(previous.text)
                and not _LIST.match(block.text)
            ):
                combine_provenance(previous, block)
                tail = previous.text.rsplit(" ", 1)[-1]
                if (
                    block.source == "ocr"
                    and horizontal_gap < 0
                    and len(tail) == 1
                    and tail.isalpha()
                    and block.text.startswith(tail)
                ):
                    previous.text = previous.text[:-1] + block.text
                else:
                    previous.text += " " + block.text
                previous.bbox = (
                    previous.bbox[0],
                    min(previous.bbox[1], block.bbox[1]),
                    block.bbox[2],
                    max(previous.bbox[3], block.bbox[3]),
                )
                continue
            if (
                previous.type == block.type == "paragraph"
                and previous.source == block.source
                and block.source != "caption"
                and same_style
                and abs(previous.bbox[0] - block.bbox[0]) <= 12
                and -1 <= gap <= min(line_height * 0.9, 16)
                and not re.search(r"[.!?:;]$", previous.text)
                and not re.match(r"^[\w][\w /-]{0,30}:\s", block.text)
                and not _LIST.match(previous.text)
                and not _LIST.match(block.text)
            ):
                combine_provenance(previous, block)
                previous.text += "\n" + block.text
                previous.bbox = (
                    min(previous.bbox[0], block.bbox[0]),
                    previous.bbox[1],
                    max(previous.bbox[2], block.bbox[2]),
                    block.bbox[3],
                )
                continue
        merged.append(block)
    result.blocks = merged
    return result


def merge_stacked_labels(page: Page) -> Page:
    """Join close aligned OCR label lines even when an omitted icon intervenes.

    Require comparable widths, matching left edges and a very small vertical
    gap; region ownership still prevents crossing card or table boundaries.
    """
    result = page.model_copy(deep=True)
    removed: set[str] = set()
    for upper in result.blocks:
        if upper.id in removed or upper.type != "paragraph" or upper.source != "ocr":
            continue
        a = upper.bbox
        for lower in result.blocks:
            if (
                lower.id in removed
                or lower is upper
                or lower.type != "paragraph"
                or lower.source != "ocr"
                or not can_merge(upper, lower)
            ):
                continue
            b = lower.bbox
            h = min(a[3] - a[1], b[3] - b[1])
            icon_neighbor = any(
                mark.is_decorative
                and mark.bbox[2] <= min(a[0], b[0])
                and min(a[0], b[0]) - mark.bbox[2] < h
                and mark.bbox[1] < b[3]
                and mark.bbox[3] > b[1]
                for mark in result.blocks
            )
            if (
                icon_neighbor
                and h > 0
                and -0.25 * h <= b[1] - a[3] <= 0.2 * h
                and abs(a[0] - b[0]) <= 0.2 * h
                and 0.7 <= (b[2] - b[0]) / max(1, a[2] - a[0]) <= 1.4
                and len(upper.text.split()) <= 3
                and len(lower.text.split()) <= 3
                and not _LIST.match(upper.text)
                and not _LIST.match(lower.text)
            ):
                combine_provenance(upper, lower)
                upper.text = upper.markdown = upper.text + " " + lower.text
                upper.bbox = (min(a[0], b[0]), a[1], max(a[2], b[2]), b[3])
                removed.add(lower.id)
                break
    result.blocks = [b for b in result.blocks if b.id not in removed]
    return result
