"""Deterministic geometric reading order and nearby caption attachment."""

from __future__ import annotations

import re
from collections import defaultdict
from statistics import median

from rag_pre_ingest.models.document import Block, Page, Warning
from rag_pre_ingest.pipeline.structure import combine_provenance


def _gap(
    blocks: list[Block], axis: int, minimum: float = 0.5
) -> tuple[list[Block], list[Block]] | None:
    ordered = sorted(blocks, key=lambda block: (block.bbox[axis], block.bbox[axis + 2], block.id))
    edge = ordered[0].bbox[axis + 2]
    candidates: list[tuple[float, int]] = []
    for index, block in enumerate(ordered[1:], 1):
        start = block.bbox[axis]
        if start > edge + minimum:
            candidates.append((start - edge, index))
        edge = max(edge, block.bbox[axis + 2])
    if not candidates:
        return None
    _, index = max(candidates, key=lambda candidate: (candidate[0], -candidate[1]))
    return ordered[:index], ordered[index:]


def _same_row_order(blocks: list[Block]) -> list[Block]:
    """Treat small OCR baseline jitter as one row, then read that row left to right."""
    bands: list[list[Block]] = []
    for block in sorted(
        blocks, key=lambda item: ((item.bbox[1] + item.bbox[3]) / 2, item.bbox[0], item.id)
    ):
        center = (block.bbox[1] + block.bbox[3]) / 2
        height = block.bbox[3] - block.bbox[1]
        if bands:
            anchor = bands[-1][0]
            anchor_center = (anchor.bbox[1] + anchor.bbox[3]) / 2
            tolerance = max(2, min(height, anchor.bbox[3] - anchor.bbox[1]) * 0.5)
            if abs(center - anchor_center) <= tolerance:
                bands[-1].append(block)
                continue
        bands.append([block])
    return [
        block for band in bands for block in sorted(band, key=lambda item: (item.bbox[0], item.id))
    ]


def _paired_label_order(blocks: list[Block]) -> list[Block] | None:
    """Read repeated numbered short labels beside wider descriptions as pairs.

    Require three consecutive labels with the same prefix and a unique vertical
    match for every description. Ordinary prose columns and structured tables
    therefore retain their existing ordering.
    """
    if len(blocks) < 6 or any(block.type not in {"paragraph", "heading"} for block in blocks):
        return None
    cut = _gap(blocks, 0)
    if cut is None:
        return None
    labels, descriptions = cut
    if len(labels) < 3 or len(descriptions) < len(labels):
        return None
    labels = sorted(labels, key=lambda block: (block.bbox[1], block.id))
    matches = [
        re.fullmatch(r"([^\W\d_][\w -]{0,30}?)\s+(\d{1,3})[.:]?", block.text.strip())
        for block in labels
    ]
    if any(match is None for match in matches):
        return None
    parsed = [match for match in matches if match is not None]
    if len({match[1].casefold() for match in parsed}) != 1:
        return None
    numbers = [int(match[2]) for match in parsed]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return None
    height = median(block.bbox[3] - block.bbox[1] for block in labels)
    if (
        height <= 0
        or max(block.bbox[0] for block in labels) - min(block.bbox[0] for block in labels) > height
    ):
        return None
    centers = [(block.bbox[1] + block.bbox[3]) / 2 for block in labels]
    edges = [(left + right) / 2 for left, right in zip(centers, centers[1:], strict=False)]
    rows: dict[int, list[Block]] = defaultdict(list)
    for description in descriptions:
        center = (description.bbox[1] + description.bbox[3]) / 2
        row = sum(center > edge for edge in edges)
        if any(description.bbox[1] < edge < description.bbox[3] for edge in edges):
            return None
        rows[row].append(description)
    pairs: list[Block] = []
    for row, label in enumerate(labels):
        descriptions_in_row = sorted(rows[row], key=lambda block: (block.bbox[1], block.id))
        if not descriptions_in_row:
            return None
        top = min(block.bbox[1] for block in descriptions_in_row)
        bottom = max(block.bbox[3] for block in descriptions_in_row)
        if (
            min(label.bbox[3], bottom) - max(label.bbox[1], top)
            < (label.bbox[3] - label.bbox[1]) * 0.5
            or sum(len(block.text.split()) for block in descriptions_in_row) < 4
            or max(block.bbox[2] - block.bbox[0] for block in descriptions_in_row)
            < 2 * (label.bbox[2] - label.bbox[0])
            or any(
                next_block.bbox[1] - previous.bbox[3] > height
                for previous, next_block in zip(
                    descriptions_in_row, descriptions_in_row[1:], strict=False
                )
            )
        ):
            return None
        pairs.extend((label, *descriptions_in_row))
    return pairs


def _category_rows(blocks: list[Block], width: float) -> list[Block] | None:
    """Pair a repeated right-aligned short OCR label column with its value bands.

    Five aligned labels and large inter-row gaps provide evidence beyond ordinary
    prose columns. Close stacked label fragments are retained together.
    """
    candidates = [
        b
        for b in blocks
        if b.source == "ocr"
        and b.type == "paragraph"
        and 0 < len(b.text.split()) <= 3
        and b.bbox[2] < width * 0.35
        and b.bbox[0] > width * 0.04
    ]
    if len(candidates) < 5:
        return None
    height = median(b.bbox[3] - b.bbox[1] for b in candidates)
    edge = median(b.bbox[2] for b in candidates)
    labels = sorted(
        [b for b in candidates if abs(b.bbox[2] - edge) < height], key=lambda b: b.bbox[1]
    )
    groups: list[list[Block]] = []
    for label in labels:
        if groups and label.bbox[1] - groups[-1][-1].bbox[3] < height * 0.25:
            groups[-1].append(label)
        else:
            groups.append([label])
    if (
        groups
        and max(b.bbox[2] for b in groups[0]) - min(b.bbox[2] for b in groups[0]) > height * 0.8
    ):
        groups = groups[1:]
    names = [" ".join(b.text.casefold() for b in g) for g in groups]
    if len(set(names)) != len(names):
        return None
    if len(groups) < 5 or any(len(g) > 2 for g in groups):
        return None
    centers = [(g[0].bbox[1] + g[-1].bbox[3]) / 2 for g in groups]
    if any(b - a < height * 1.8 for a, b in zip(centers, centers[1:], strict=False)):
        return None
    edges = [
        centers[0] - (centers[1] - centers[0]) / 2,
        *[(a + b) / 2 for a, b in zip(centers, centers[1:], strict=False)],
        centers[-1] + (centers[-1] - centers[-2]) / 2,
    ]
    ids = {b.id for g in groups for b in g}
    values: list[list[Block]] = [[] for _ in groups]
    prefix: list[Block] = []
    suffix: list[Block] = []
    for block in blocks:
        if block.id in ids:
            continue
        center = (block.bbox[1] + block.bbox[3]) / 2
        if center < edges[0]:
            prefix.append(block)
        elif center > edges[-1]:
            suffix.append(block)
        else:
            row = sum(center > e for e in edges[1:])
            if (
                block.source != "ocr"
                or block.type != "paragraph"
                or block.bbox[0] < edge + height
                or block.bbox[1] < edges[row] - height * 0.25
                or block.bbox[3] > edges[row + 1] + height * 0.25
            ):
                return None
            values[row].append(block)
    if any(not row for row in values):
        return None
    # Prefix can contain independent stacked logo/title columns.
    prefix_cut = _gap(prefix, 0, height * 0.5) if prefix else None
    ordered_prefix = (
        _same_row_order(prefix_cut[0]) + _same_row_order(prefix_cut[1])
        if prefix_cut
        else _same_row_order(prefix)
    )
    if prefix_cut and all(len(column) > 1 for column in prefix_cut):
        ordered_prefix = []
        for column in prefix_cut:
            lines = sorted(column, key=lambda b: b.bbox[1])
            combined = lines[0].model_copy(deep=True)
            for line in lines[1:]:
                combine_provenance(combined, line)
            combined.text = "\n".join(b.text for b in lines)
            combined.markdown = combined.text
            combined.bbox = (
                min(b.bbox[0] for b in lines),
                min(b.bbox[1] for b in lines),
                max(b.bbox[2] for b in lines),
                max(b.bbox[3] for b in lines),
            )
            ordered_prefix.append(combined)
    for group in groups:
        if len(group) == 2:
            a, b = group
            combined = a.model_copy(deep=True)
            combine_provenance(combined, b)
            combined.text = a.text + " " + b.text
            combined.markdown = combined.text
            combined.bbox = (
                min(a.bbox[0], b.bbox[0]),
                a.bbox[1],
                max(a.bbox[2], b.bbox[2]),
                b.bbox[3],
            )
            group[:] = [combined]
    return (
        ordered_prefix
        + [
            b
            for label, value in zip(groups, values, strict=True)
            for b in [*label, *_same_row_order(value)]
        ]
        + _same_row_order(suffix)
    )


def _repeated_card_order(blocks: list[Block], width: float) -> list[Block] | None:
    """Use repeated local headers/actions as evidence for independent card groups.

    Ordinary columns retain XY-cut order. Two recurring short labels must agree on
    both column positions and row baselines before choosing row-major card order.
    """
    labels: dict[str, list[Block]] = defaultdict(list)
    for block in blocks:
        if block.type in {"paragraph", "heading"} and 0 < len(block.text.strip()) <= 80:
            labels[" ".join(block.text.casefold().split())].append(block)
    grids: list[tuple[list[float], list[float], float]] = []
    for occurrences in labels.values():
        if len(occurrences) < 4:
            continue
        height = median(block.bbox[3] - block.bbox[1] for block in occurrences)
        if height <= 0:
            continue
        columns: list[list[Block]] = []
        for block in sorted(occurrences, key=lambda item: item.bbox[0]):
            if columns and abs(block.bbox[0] - columns[-1][0].bbox[0]) <= height:
                columns[-1].append(block)
            else:
                columns.append([block])
        if not 2 <= len(columns) <= 4 or min(map(len, columns)) < 2:
            continue
        anchors = [median(block.bbox[0] for block in column) for column in columns]
        if (
            min(anchors[index + 1] - anchors[index] for index in range(len(anchors) - 1))
            < width * 0.2
        ):
            continue
        baselines = sorted((block.bbox[1] + block.bbox[3]) / 2 for block in columns[0])
        if any(len(column) != len(baselines) for column in columns):
            continue
        if any(
            abs(first - other) > height * 0.75
            for column in columns[1:]
            for first, other in zip(
                baselines,
                sorted((block.bbox[1] + block.bbox[3]) / 2 for block in column),
                strict=True,
            )
        ):
            continue
        if (
            min(baselines[index + 1] - baselines[index] for index in range(len(baselines) - 1))
            < height * 3
        ):
            continue
        grids.append((anchors, baselines, height))
    grids.sort(key=lambda grid: grid[0][0])
    for anchors, baselines, height in grids:
        corroborated = any(
            other is not anchors
            and len(other) == len(anchors)
            and len(rows) == len(baselines)
            and all(
                abs((other[i] - other[0]) - (anchors[i] - anchors[0])) <= height
                for i in range(len(anchors))
            )
            and all(abs(a - b) <= height for a, b in zip(rows, baselines, strict=True))
            for other, rows, _ in grids
        )
        if not corroborated:
            continue
        prefix = [block for block in blocks if block.bbox[3] < baselines[0] - height]
        prefix_ids = {block.id for block in prefix}
        body = [block for block in blocks if block.id not in prefix_ids]
        left = min(block.bbox[0] for block in body)
        inset = max(0, anchors[0] - left)
        x_edges = [anchor - inset for anchor in anchors[1:]]
        y_edges = [(baselines[i] + baselines[i + 1]) / 2 for i in range(len(baselines) - 1)]
        groups: dict[tuple[int, int], list[Block]] = defaultdict(list)
        for block in body:
            x = (block.bbox[0] + block.bbox[2]) / 2
            y = (block.bbox[1] + block.bbox[3]) / 2
            groups[(sum(y > edge for edge in y_edges), sum(x > edge for edge in x_edges))].append(
                block
            )
        return _same_row_order(prefix) + [
            block for key in sorted(groups) for block in _same_row_order(groups[key])
        ]
    return None


def reading_order(
    blocks: list[Block], page_width: float, page_height: float
) -> tuple[list[Block], list[Warning]]:
    """Recursively cut whitespace: columns first, then horizontal divider bands.

    Full-width content closes vertical gaps, forcing horizontal cuts around it.
    Inputs are never mutated. Ambiguous overlapping groups retain geometric order.
    """
    warnings: list[Warning] = []

    def visit(group: list[Block]) -> list[Block]:
        if len(group) < 2:
            return group
        pairs = _paired_label_order(group)
        if pairs is not None:
            return pairs
        for axis in (0, 1):
            heights = [block.bbox[3] - block.bbox[1] for block in group if block.type != "image"]
            minimum = max(4, median(heights) * 2) if axis == 0 and heights else 0.5
            cut = _gap(group, axis, minimum)
            if cut is not None:
                return visit(cut[0]) + visit(cut[1])
        # An image and its contained OCR text intentionally overlap.
        ambiguous: set[str] = set()
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                a, b = left.bbox, right.bbox
                intersects = min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])
                contained = (
                    left.type == "image"
                    and a[0] <= b[0] <= b[2] <= a[2]
                    and a[1] <= b[1] <= b[3] <= a[3]
                ) or (
                    right.type == "image"
                    and b[0] <= a[0] <= a[2] <= b[2]
                    and b[1] <= a[1] <= a[3] <= b[3]
                )
                if intersects and not contained:
                    ambiguous.update((left.id, right.id))
        for block in group:
            if block.id in ambiguous:
                block.layout_confidence = 0.4
        if ambiguous:
            warnings.append(
                Warning(
                    code="reading_order_uncertain",
                    message="Overlapping blocks have no clean gap; order is provisional.",
                )
            )
        return _same_row_order(group)

    if page_width <= 0 or page_height <= 0 or not blocks:
        return [block.model_copy(deep=True) for block in blocks], []
    copied = [block.model_copy(deep=True) for block in blocks]
    containers = [
        block
        for block in copied
        if block.type == "image"
        and any(
            other.type != "image"
            and block.bbox[0] <= other.bbox[0] <= other.bbox[2] <= block.bbox[2]
            and block.bbox[1] <= other.bbox[1] <= other.bbox[3] <= block.bbox[3]
            for other in copied
        )
    ]
    container_ids = {block.id for block in containers}
    content = [block for block in copied if block.id not in container_ids]
    cards: list[Block] | None
    panels = [b for b in content if b.region_kind == "card"]
    if len(panels) >= 3:
        height = median(b.bbox[3] - b.bbox[1] for b in panels)
        row_tops: list[float] = []
        for panel in sorted(panels, key=lambda b: b.bbox[1]):
            if not row_tops or panel.bbox[1] - row_tops[-1] > height * 0.25:
                row_tops.append(panel.bbox[1])
        cards = sorted(
            content,
            key=lambda b: (
                min(row_tops, key=lambda y: abs(y - b.bbox[1])) if b in panels else b.bbox[1],
                b.bbox[0],
            ),
        )
    else:
        cards = _category_rows(content, page_width)
    if cards is None:
        cards = _repeated_card_order(content, page_width)
    ordered = cards if cards is not None else visit(content)
    for container in sorted(containers, key=lambda block: (block.bbox[1], block.bbox[0], block.id)):
        index = next(
            (
                index
                for index, block in enumerate(ordered)
                if container.bbox[0] <= block.bbox[0] <= block.bbox[2] <= container.bbox[2]
                and container.bbox[1] <= block.bbox[1] <= block.bbox[3] <= container.bbox[3]
            ),
            len(ordered),
        )
        ordered.insert(index, container)
    return ordered, warnings


def sort_page(page: Page) -> tuple[Page, list[Warning]]:
    result = page.model_copy(deep=True)
    result.blocks, warnings = reading_order(result.blocks, result.width, result.height)
    for warning in warnings:
        warning.page_number = page.page_number
    return result, warnings


def attach_captions(page: Page) -> Page:
    """Attach short nearby direct-read text, keeping it as a plain text block."""
    result = page.model_copy(deep=True)
    images = [block for block in result.blocks if block.type == "image"]
    maximum_gap = max(16.0, min(result.width, result.height) * 0.035)
    assigned: set[str] = set()
    for image in images:
        x0, y0, x1, y1 = image.bbox
        candidates: list[tuple[float, str, Block]] = []
        for block in result.blocks:
            if (
                block.type != "paragraph"
                or block.source != "read"
                or block.id in assigned
                or not block.text.strip()
                or len(block.text) > 240
            ):
                continue
            left, top, right, bottom = block.bbox
            if bottom - top > max(40, result.height * 0.08):
                continue
            horizontal_overlap = min(right, x1) - max(left, x0)
            vertical_overlap = min(bottom, y1) - max(top, y0)
            below = 0 <= top - y1 <= maximum_gap and horizontal_overlap > 0
            beside_gap = max(left - x1, x0 - right)
            beside = 0 <= beside_gap <= maximum_gap and vertical_overlap > 0
            if below or beside:
                distance = top - y1 if below else beside_gap + maximum_gap / 2
                candidates.append((distance, block.id, block))
        if candidates:
            _, _, caption = min(candidates, key=lambda candidate: (candidate[0], candidate[1]))
            image.caption = caption.text
            caption.source = "caption"
            assigned.add(caption.id)
    return result
