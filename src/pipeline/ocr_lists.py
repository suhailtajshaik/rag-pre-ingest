"""Recover OCR list structure only from explicit glyphs or visible bullet components."""

import math
import unicodedata
from statistics import median

from PIL import Image

BBox = tuple[float, float, float, float]
_BULLETS = frozenset("•▪◦●∙‣⁃■○·\uf0a7")


def is_symbol_only(text: str) -> bool:
    """Standalone non-text marks stay inspectable but do not become prose.

    Unicode letters and numbers are retained in every script, including single
    characters, and surrounding punctuation, currency and math symbols are kept.
    This does not decide whether a letter-shaped graphic is actually a letter.
    """
    return not any(unicodedata.category(character)[0] in {"L", "N"} for character in text)


def normalize_list_prefix(text: str, visual_bullet: bool = False) -> tuple[bool, str]:
    """Example: ``• Item`` -> ``(True, 'Item')``; ordinary text stays ordinary."""
    content = text.strip()
    if content and content[0] in _BULLETS:
        return True, content[1:].lstrip()
    if len(content) > 1 and content[0] in "-*+" and content[1].isspace():
        return True, content[2:].lstrip()
    if visual_bullet and len(content) > 1 and content[0] in ".oO0°" and content[1].isspace():
        return True, content[2:].lstrip()
    return visual_bullet, content


def has_left_text_fragment(bbox: BBox, lines: list[tuple[BBox, str]]) -> bool:
    """A neighboring text fragment's comma/colon is not an independent bullet.

    Only nearby text on the same baseline blocks visual inference. Explicit
    recognized bullet prefixes are still normalized independently.
    """
    x0, y0, _, y1 = bbox
    height = y1 - y0
    if height <= 0:
        return False
    for previous, text in lines:
        if is_symbol_only(text):
            continue
        px0, py0, px1, py1 = previous
        previous_height = py1 - py0
        gap = x0 - px1
        # OCR line boxes can overlap where one fragment repeats the next initial.
        if previous_height <= 0 or px0 >= x0 or not -0.75 * height <= gap <= 2 * height:
            continue
        overlap = min(y1, py1) - max(y0, py0)
        center_difference = abs((y0 + y1 - py0 - py1) / 2)
        if overlap >= 0.5 * min(height, previous_height) and center_difference <= 0.35 * max(
            height, previous_height
        ):
            return True
    return False


def _components(points: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    """Eight-connected components; input is copied so callers retain their pixels."""
    remaining = points.copy()
    output: list[set[tuple[int, int]]] = []
    while remaining:
        start = remaining.pop()
        group = {start}
        pending = [start]
        while pending:
            x, y = pending.pop()
            for dx, dy in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
                neighbor = (x + dx, y + dy)
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    group.add(neighbor)
                    pending.append(neighbor)
        output.append(group)
    return output


def has_visual_bullet(image: Image.Image, bbox: BBox, allow_stars: bool = False) -> bool:
    """Find a small filled dot/square beside a line, using either contrast polarity.

    The compact search includes the OCR box's left edge because detectors sometimes
    include the bullet in their box while recognition omits the glyph. Components
    clipped by the search boundary, letters, long rules, and hollow boxes are rejected.
    Coordinates are pixels in the encoded OCR input, before page-scale conversion.
    """
    x0, y0, _, y1 = bbox
    height = y1 - y0
    if height < 4 or not all(math.isfinite(value) for value in bbox):
        return False
    left = max(0, math.floor(x0 - 2 * height))
    right = min(image.width, math.ceil(x0 + 0.65 * height))
    top = max(0, math.floor(y0 - 0.1 * height))
    bottom = min(image.height, math.ceil(y1 + 0.1 * height))
    if right - left < 3 or bottom - top < 3:
        return False
    rgb = image.crop((left, top, right, bottom)).convert("RGB")
    colors = rgb.tobytes()
    crop = rgb.convert("L")
    width, rows = crop.size
    data = crop.tobytes()
    border = [data[y * width + x] for x in range(width) for y in (0, rows - 1)]
    border.extend(data[y * width + x] for y in range(1, rows - 1) for x in (0, width - 1))
    background = float(median(border))
    pixels = {
        (x, y)
        for y in range(rows)
        for x in range(width)
        if abs(data[y * width + x] - background) >= 55
        and max(colors[(y * width + x) * 3 : (y * width + x) * 3 + 3])
        - min(colors[(y * width + x) * 3 : (y * width + x) * 3 + 3])
        < 45
    }
    # A multicolor emblem beside a word is not a monochrome list marker.
    colorful = sum(
        abs(data[y * width + x] - background) >= 55
        and max(colors[(y * width + x) * 3 : (y * width + x) * 3 + 3])
        - min(colors[(y * width + x) * 3 : (y * width + x) * 3 + 3])
        >= 45
        for y in range(rows)
        for x in range(width)
    )
    if colorful > width * rows * 0.025:
        return False
    for group in _components(pixels):
        xs = [point[0] for point in group]
        ys = [point[1] for point in group]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        if min_x == 0 or min_y == 0 or max_x == width - 1 or max_y == rows - 1:
            continue
        component_width, component_height = max_x - min_x + 1, max_y - min_y + 1
        if not (
            max(2, height * 0.1) <= component_width <= height * 0.85
            and max(2, height * 0.1) <= component_height <= height * 0.85
        ):
            continue
        if not 0.6 <= component_width / component_height <= 1.65:
            continue
        if len(group) / (component_width * component_height) < (0.35 if allow_stars else 0.6):
            continue
        if max(component_width, component_height) > height * 0.45:
            if not allow_stars:
                continue
            # Larger four-point stars have empty corners and a filled center.
            corners = sum((x, y) in group for x in (min_x, max_x) for y in (min_y, max_y))
            center = (round((min_x + max_x) / 2), round((min_y + max_y) / 2))
            tips_centered = all(
                abs(y - center[1]) < component_height * 0.22
                for x, y in group
                if x in (min_x, max_x)
            ) and all(
                abs(x - center[0]) < component_width * 0.22 for x, y in group if y in (min_y, max_y)
            )
            if corners or center not in group or not tips_centered:
                continue
        center_y = top + (min_y + max_y) / 2
        center_x = left + (min_x + max_x) / 2
        if y0 + height * 0.25 <= center_y <= y0 + height * 0.8 and center_x <= x0 + height * 0.4:
            return True
    return False


def is_decorative_circle(image: Image.Image, bbox: BBox, text: str) -> bool:
    """Detect tiny colored circles physically attached to a longer graphic stroke.

    Printed O, zero, isolated circles and separate diagram-node labels are kept.
    The original OCR text is retained in the structured block.
    """
    x0, y0, x1, y1 = bbox
    width, height = x1 - x0, y1 - y0
    if (
        text != "O"
        or not all(math.isfinite(value) for value in bbox)
        or not 4 <= width <= image.width * 0.025
        or not 4 <= height <= image.height * 0.025
        or not 0.65 <= width / height <= 1.5
    ):
        return False
    left = max(0, math.floor(x0 - 5 * width))
    right = min(image.width, math.ceil(x1 + 5 * width))
    top = max(0, math.floor(y0 - height))
    bottom = min(image.height, math.ceil(y1 + height))
    crop = image.crop((left, top, right, bottom)).convert("RGB")
    columns, rows = crop.size
    data = crop.tobytes()
    border = [(x, y) for x in range(columns) for y in (0, rows - 1)]
    border.extend((x, y) for y in range(1, rows - 1) for x in (0, columns - 1))
    background = [
        median(data[(y * columns + x) * 3 + channel] for x, y in border) for channel in range(3)
    ]
    colored: set[tuple[int, int]] = set()
    for y in range(rows):
        for x in range(columns):
            offset = (y * columns + x) * 3
            color = data[offset : offset + 3]
            if (
                max(color) - min(color) >= 45
                and max(abs(color[c] - background[c]) for c in range(3)) >= 35
            ):
                colored.add((x, y))
    for group in _components(colored):
        inside = [(x, y) for x, y in group if x0 <= x + left <= x1 and y0 <= y + top <= y1]
        if len(inside) < 4:
            continue
        xs = [x + left for x, y in group]
        extends = max(x0 - min(xs), max(xs) - x1)
        if extends < 2 * width:
            continue
        # A flourish may branch farther away; test the connecting stroke beside
        # the circle itself rather than averaging the entire nearby diagram.
        for start, end in (
            (math.floor(x0 - 2 * width), math.floor(x0)),
            (math.ceil(x1), math.ceil(x1 + 2 * width)),
        ):
            counts = [sum(px + left == column for px, _ in group) for column in range(start, end)]
            if counts and sum(count > 0 for count in counts) >= len(counts) * 0.9:
                if median(counts) <= height * 0.45:
                    return True
    return False


def is_decorative_arrow(image: Image.Image, bbox: BBox, text: str) -> bool:
    """Identify an isolated colored north-east arrow, never by its OCR character.

    Require a connected horizontal head, right vertical head and diagonal shaft.
    Neutral printed letters and multi-character words are deliberately retained.
    """
    if len(text.strip()) != 1 or not all(math.isfinite(value) for value in bbox):
        return False
    left, top = max(0, math.floor(bbox[0])), max(0, math.floor(bbox[1]))
    right, bottom = min(image.width, math.ceil(bbox[2])), min(image.height, math.ceil(bbox[3]))
    if right <= left or bottom <= top or (right - left) * (bottom - top) > 100_000:
        return False
    crop = image.crop((left, top, right, bottom)).convert("RGB")
    data = crop.tobytes()
    pixels = {
        (x, y)
        for y in range(crop.height)
        for x in range(crop.width)
        if max(data[(y * crop.width + x) * 3 : (y * crop.width + x) * 3 + 3])
        - min(data[(y * crop.width + x) * 3 : (y * crop.width + x) * 3 + 3])
        >= 45
    }
    for group in _components(pixels):
        x0, x1 = min(x for x, _ in group), max(x for x, _ in group)
        y0, y1 = min(y for _, y in group), max(y for _, y in group)
        width, height = x1 - x0 + 1, y1 - y0 + 1
        if min(width, height) < 12 or not 0.8 <= width / height <= 1.25:
            continue
        # Compare shape at normalized coordinates, independent of image position.
        points = {((x - x0) / width, (y - y0) / height) for x, y in group}
        top_head = sum(y < 0.3 and x > 0.15 for x, y in points)
        right_head = sum(x > 0.7 and y < 0.85 for x, y in points)
        shaft = sum(0.12 < x < 0.7 and 0.3 < y < 0.95 and abs(x + y - 1) < 0.23 for x, y in points)
        forbidden = sum((x < 0.15 and y < 0.55) or (x > 0.55 and y > 0.85) for x, y in points)
        area = width * height
        if (
            top_head / area > 0.14
            and right_head / area > 0.14
            and shaft / area > 0.12
            and forbidden / area < 0.065
        ):
            return True
    return False
