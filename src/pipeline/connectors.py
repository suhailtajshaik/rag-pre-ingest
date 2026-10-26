"""Conservative pixel evidence for arrows between repeated boxed text labels."""

from __future__ import annotations

from collections import deque
from statistics import median
from typing import Literal, cast

from PIL import Image

from rag_pre_ingest.models.document import Block, Connector, Page

Point = tuple[int, int]
Direction = Literal["down", "up", "left", "right"]


def arrow_direction(points: set[Point]) -> Direction | None:
    """Recognize a filled shaft followed by a triangular head; abstain on ambiguity."""
    if not points:
        return None
    x0, x1 = min(x for x, _ in points), max(x for x, _ in points)
    y0, y1 = min(y for _, y in points), max(y for _, y in points)
    width, height = x1 - x0 + 1, y1 - y0 + 1
    if min(width, height) < 6 or not 0.35 <= width / height <= 2.85:
        return None
    candidates: list[Direction] = []
    for direction in ("down", "up", "right", "left"):
        rows: dict[int, list[int]] = {}
        for x, y in points:
            along, across = {
                "down": (y - y0, x - x0),
                "up": (y1 - y, x - x0),
                "right": (x - x0, y - y0),
                "left": (x1 - x, y - y0),
            }[direction]
            rows.setdefault(along, []).append(across)
        length = max(rows) + 1
        spans = [max(rows[i]) - min(rows[i]) + 1 if i in rows else 0 for i in range(length)]
        peak = max(spans)
        stem = spans[max(1, length // 10) : max(2, length * 3 // 10)]
        tail = spans[length * 7 // 10 : length * 9 // 10]
        # The shaft must be narrow and nearly parallel. The arrowhead must widen
        # away from it, then taper continuously toward the opposite endpoint.
        if not stem or not tail or not all(spans):
            continue
        peak_at = next(i for i, span in enumerate(spans) if span == peak)
        if (
            max(stem) - min(stem) <= max(1, peak * 0.1)
            and 0.12 * peak < median(stem) < 0.65 * peak
            and length * 0.3 <= peak_at <= length * 0.7
            and spans[-1] < peak * 0.4
            and tail[0] > tail[-1]
            and all(spans[i + 1] <= spans[i] + 2 for i in range(peak_at, length - 1))
        ):
            candidates.append(direction)
    return candidates[0] if len(candidates) == 1 else None


def _components(image: Image.Image) -> list[set[Point]]:
    rgb = image.convert("RGB")
    corners = [
        cast(tuple[int, int, int], rgb.getpixel(p))
        for p in ((0, 0), (rgb.width - 1, 0), (0, rgb.height - 1))
    ]
    background = tuple(median(pixel[c] for pixel in corners) for c in range(3))
    pixels = rgb.load()
    assert pixels is not None
    foreground = {
        (x, y)
        for y in range(rgb.height)
        for x in range(rgb.width)
        if sum(abs(cast(tuple[int, int, int], pixels[x, y])[c] - background[c]) for c in range(3))
        > 110
    }
    result = []
    while foreground:
        seed = foreground.pop()
        component = {seed}
        queue = deque([seed])
        while queue:
            x, y = queue.popleft()
            for p in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if p in foreground:
                    foreground.remove(p)
                    component.add(p)
                    queue.append(p)
        if len(component) >= 15:
            result.append(component)
    return result


def detect_connectors(image: Image.Image, page: Page) -> Page:
    """Preserve only visible, unambiguous arrows between repeated boxed labels.

    Nodes require one contained text block each. Unboxed logos, corner flourishes,
    text-only proximity and unclear shapes never create relationships.
    """
    result = page.model_copy(deep=True)
    if result.connectors:
        return result
    ratio = min(1.0, 800 / max(image.size))
    small = image.resize((round(image.width * ratio), round(image.height * ratio)))
    components = _components(small)
    sx, sy = page.width / small.width, page.height / small.height
    nodes: list[tuple[tuple[int, int, int, int], Block]] = []
    for points in components:
        x0, x1 = min(x for x, _ in points), max(x for x, _ in points) + 1
        y0, y1 = min(y for _, y in points), max(y for _, y in points) + 1
        w, h = x1 - x0, y1 - y0
        if not (w > small.width * 0.08 and 3 < w / h < 12 and len(points) / (w * h) > 0.65):
            continue
        members = [
            b
            for b in page.blocks
            if not b.is_decorative
            and b.text.strip()
            and x0 * sx <= (b.bbox[0] + b.bbox[2]) / 2 <= x1 * sx
            and y0 * sy <= (b.bbox[1] + b.bbox[3]) / 2 <= y1 * sy
        ]
        if len(members) == 1:
            nodes.append(((x0, y0, x1, y1), members[0]))
    if len(nodes) < 3:
        return result
    mw = median(n[0][2] - n[0][0] for n in nodes)
    mh = median(n[0][3] - n[0][1] for n in nodes)
    nodes = [
        n
        for n in nodes
        if abs((n[0][2] - n[0][0]) / mw - 1) < 0.2 and abs((n[0][3] - n[0][1]) / mh - 1) < 0.2
    ]
    edges: list[Connector] = []
    for points in components:
        direction = arrow_direction(points)
        if direction is None:
            continue
        ax0, ax1 = min(x for x, _ in points), max(x for x, _ in points) + 1
        ay0, ay1 = min(y for _, y in points), max(y for _, y in points) + 1
        cx, cy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
        if max(ax1 - ax0, ay1 - ay0) > mw * 0.4:
            continue
        vertical = direction in {"up", "down"}
        before = (
            [
                n
                for n in nodes
                if (n[0][3] < ay0 and abs((n[0][0] + n[0][2]) / 2 - cx) < mw * 0.12)
                if vertical
            ]
            if vertical
            else [
                n for n in nodes if n[0][2] < ax0 and abs((n[0][1] + n[0][3]) / 2 - cy) < mh * 0.3
            ]
        )
        after = (
            [
                n
                for n in nodes
                if (n[0][1] > ay1 and abs((n[0][0] + n[0][2]) / 2 - cx) < mw * 0.12)
                if vertical
            ]
            if vertical
            else [
                n for n in nodes if n[0][0] > ax1 and abs((n[0][1] + n[0][3]) / 2 - cy) < mh * 0.3
            ]
        )
        if not before or not after:
            continue
        first = max(before, key=lambda n: n[0][3] if vertical else n[0][2])
        second = min(after, key=lambda n: n[0][1] if vertical else n[0][0])
        gap = second[0][1] - first[0][3] if vertical else second[0][0] - first[0][2]
        if gap > mw * 0.7:
            continue
        source, target = (first, second) if direction in {"down", "right"} else (second, first)
        edges.append(
            Connector(
                source_block_id=source[1].id,
                target_block_id=target[1].id,
                bbox=(ax0 * sx, ay0 * sy, ax1 * sx, ay1 * sy),
                direction=direction,
            )
        )
    edges.sort(key=lambda edge: (edge.bbox[1], edge.bbox[0]))
    result.connectors = tuple(edges)
    if edges:
        labels = {b.id: b.text for _, b in nodes}
        outgoing = {e.source_block_id: e.target_block_id for e in edges}
        starts = set(outgoing) - {e.target_block_id for e in edges}
        # Render only a single unbranched chain. Ambiguous/branched relations stay
        # inspectable as evidence rather than inventing a linear reading order.
        if len(starts) == 1 and len(outgoing) == len(edges):
            chain = [starts.pop()]
            while chain[-1] in outgoing and outgoing[chain[-1]] not in chain:
                chain.append(outgoing[chain[-1]])
            if len(chain) == len(edges) + 1:
                text = " → ".join(labels[key] for key in chain)
                members = [block for _, block in nodes if block.id in chain]
                observations = {o.id: o for block in members for o in block.observations}
                result.blocks.append(
                    Block(
                        id=f"p{page.page_number}_flow_sequence",
                        type="other",
                        text=text,
                        markdown=text,
                        bbox=(
                            min(block.bbox[0] for block in members),
                            min(block.bbox[1] for block in members),
                            max(block.bbox[2] for block in members),
                            max(block.bbox[3] for block in members),
                        ),
                        source="read" if all(b.source == "read" for b in members) else "ocr",
                        merge_locked=True,
                        observation_ids=tuple(
                            dict.fromkeys(key for block in members for key in block.observation_ids)
                        ),
                        observations=tuple(observations.values()),
                    )
                )
    return result
