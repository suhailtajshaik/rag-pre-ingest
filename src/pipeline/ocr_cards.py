"""Repeated flat rectangular panels provide conservative OCR grouping boundaries."""

from __future__ import annotations

from collections import deque
from statistics import median
from typing import cast

from PIL import Image


def card_regions(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Detect at least three similarly sized, mostly solid dark panels.

    Small logos, text components and full-page backgrounds are excluded by area,
    rectangular occupancy and repeated size, without relying on brand or hue.
    """
    scale = min(1.0, 400 / max(image.size))
    small = image.convert("RGB").resize((round(image.width * scale), round(image.height * scale)))
    width, height = small.size
    dark = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if max(cast(tuple[int, int, int], small.getpixel((x, y)))) < 150
    }
    regions = []
    while dark:
        seed = dark.pop()
        queue = deque([seed])
        points = [seed]
        while queue:
            x, y = queue.popleft()
            for p in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if p in dark:
                    dark.remove(p)
                    queue.append(p)
                    points.append(p)
        x0 = min(p[0] for p in points)
        x1 = max(p[0] for p in points) + 1
        y0 = min(p[1] for p in points)
        y1 = max(p[1] for p in points) + 1
        area = (x1 - x0) * (y1 - y0)
        if (
            width * height * 0.008 < area < width * height * 0.15
            and 1.5 < (x1 - x0) / (y1 - y0) < 6
            and len(points) / area > 0.72
        ):
            regions.append((x0, y0, x1, y1))
    if len(regions) < 3:
        return []
    mw = median(r[2] - r[0] for r in regions)
    mh = median(r[3] - r[1] for r in regions)
    regions = [
        r
        for r in regions
        if abs((r[2] - r[0]) / mw - 1) < 0.12 and abs((r[3] - r[1]) / mh - 1) < 0.12
    ]
    if len(regions) < 3:
        return []
    return [
        (round(r[0] / scale), round(r[1] / scale), round(r[2] / scale), round(r[3] / scale))
        for r in sorted(regions, key=lambda r: (round(r[1] / mh * 0.5), r[0]))
    ]
