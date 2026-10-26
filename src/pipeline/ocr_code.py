"""Pure code-context and pixel-line geometry helpers; no execution of source text."""

from __future__ import annotations

import re
from statistics import median
from typing import cast

from PIL import Image, ImageChops, ImageOps

BBox = tuple[float, float, float, float]


def looks_like_code(texts: list[str]) -> bool:
    patterns = (
        r"^(?:from\s+\w[\w.]*\s+import\s|import\s+\w)",
        r"^\w+\s*=\s*[\w.]+\(",
        r"^\w+\s*=\s*[\"']",
        r"^[\"']\w+[\"']\s*:\s*[\"']",
    )
    return sum(any(re.search(pattern, text.strip()) for text in texts) for pattern in patterns) >= 3


def preserves_code_content(original: list[str], reconstructed: list[str]) -> bool:
    """Decline line reconstruction if any existing substantial text disappears."""

    def letters(text: str) -> str:
        return "".join(char.casefold() for char in text if char.isalnum())

    combined = letters("".join(reconstructed))
    return bool(reconstructed) and all(
        letters(text) in combined for text in original if len(text.strip()) >= 5
    )


def code_line_crops(
    image: Image.Image, observations: list[tuple[BBox, str]]
) -> list[tuple[BBox, Image.Image]]:
    """Find ink rows on a uniform editor background, including isolated delimiters.

    Starts must align with an observed code indentation column. This excludes
    editor controls and cursors outside the source. A textured background declines
    this path; the original OCR observations remain available to the caller.
    """
    anchors = [(box, text) for box, text in observations if len(text.strip()) >= 5]
    if len(anchors) < 4:
        return []
    rgb = image.convert("RGB")
    corners = [
        cast(tuple[int, int, int], rgb.getpixel(point))
        for point in [
            (0, 0),
            (image.width - 1, 0),
            (0, image.height - 1),
            (image.width - 1, image.height - 1),
        ]
    ]
    background = tuple(int(median(c[i] for c in corners)) for i in range(3))
    if any(max(abs(c[i] - background[i]) for i in range(3)) > 25 for c in corners):
        return []
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, background))
    red, green, blue = difference.split()
    mask = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(
        lambda value: 255 if value > 45 else 0
    )
    height = median(box[3] - box[1] for box, _ in anchors)
    starts = sorted(box[0] for box, _ in anchors)
    steps = [b - a for a, b in zip(starts, starts[1:], strict=False) if b - a > height]
    indent_step = min(steps) if steps else height
    left = max(0, int(min(box[0] for box, _ in anchors) - height * 0.2))
    right = min(image.width, int(max(box[2] for box, _ in anchors) + height))
    top = max(0, int(min(box[1] for box, _ in anchors)))
    bottom = min(image.height, int(max(box[3] for box, _ in anchors) + height * 0.2))
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for y in range(top, bottom + 1):
        active = y < bottom and mask.crop((left, y, right, y + 1)).getbbox() is not None
        if active and start is None:
            start = y
        elif not active and start is not None:
            if y - start >= height * 0.35:
                bands.append((start, y))
            start = None
    output: list[tuple[BBox, Image.Image]] = []
    for y0, y1 in bands:
        bounds = mask.crop((left, y0, right, y1)).getbbox()
        if bounds is None:
            continue
        x0, x1 = left + bounds[0], left + bounds[2]
        aligned = any(abs(x0 - box[0]) <= height * 0.5 for box, _ in anchors)
        grid_aligned = (
            x0 <= starts[-1] + height * 0.5
            and abs((x0 - starts[0]) - round((x0 - starts[0]) / indent_step) * indent_step)
            <= height * 0.5
        )
        if not aligned and not grid_aligned:
            continue
        box = (float(x0), float(y0), float(x1), float(y1))
        # Monochrome contrast preserves low-contrast syntax colors and spaces.
        crop = ImageOps.expand(ImageOps.invert(mask.crop((x0, y0, x1, y1))), border=8, fill="white")
        output.append((box, crop.convert("RGB")))
    return output


def code_text(lines: list[tuple[BBox, str]]) -> str:
    """Rebuild indentation and blank lines from monospaced source coordinates."""
    if not lines:
        return ""
    lines = sorted(lines, key=lambda item: (item[0][1], item[0][0]))
    widths = [(box[2] - box[0]) / len(text) for box, text in lines if len(text) >= 8]
    character_width = median(widths) if widths else 1
    baseline = min(box[0] for box, _ in lines)
    gaps = [b[0][1] - a[0][1] for a, b in zip(lines, lines[1:], strict=False) if b[0][1] > a[0][1]]
    pitch = median(gaps) if gaps else 1
    output: list[str] = []
    previous: BBox | None = None
    for box, text in lines:
        if previous is not None and box[1] - previous[1] > pitch * 1.5:
            output.append("")
        indent = max(0, round((box[0] - baseline) / max(character_width, 1)))
        output.append(" " * indent + text.strip())
        previous = box
    return "\n".join(output)


def recover_bracket(crop: Image.Image, text: str) -> str:
    """Distinguish an isolated square bracket from a digit using its visible caps.

    Limited to a punctuation-sized observation in code context: a straight stem
    and matching top/bottom caps are required. Never repair from syntax alone.
    """
    if text not in {"1", "1,", "I", "I,"}:
        return text
    ink = ImageOps.invert(crop.convert("L")).point(lambda value: 255 if value > 100 else 0)
    columns = [x for x in range(ink.width) if ink.crop((x, 0, x + 1, ink.height)).getbbox()]
    if not columns:
        return text
    end = next((b for a, b in zip(columns, columns[1:], strict=False) if b - a > 1), ink.width)
    bounds = ink.crop((0, 0, end, ink.height)).getbbox()
    if bounds is None:
        return text
    glyph = ink.crop(bounds)
    if glyph.height < 12 or glyph.width > glyph.height * 0.8:
        return text
    cap = max(2, round(glyph.height * 0.16))
    top = glyph.crop((0, 0, glyph.width, cap)).getbbox()
    middle = glyph.crop((0, cap, glyph.width, glyph.height - cap)).getbbox()
    bottom = glyph.crop((0, glyph.height - cap, glyph.width, glyph.height)).getbbox()
    if top is None or middle is None or bottom is None:
        return text
    stem = middle[2] - middle[0]
    matching = abs(top[0] - bottom[0]) <= 2 and abs(top[2] - bottom[2]) <= 2
    if matching and min(top[2] - top[0], bottom[2] - bottom[0]) >= stem * 1.4:
        if min(middle[0] - top[0], middle[0] - bottom[0]) >= glyph.width * 0.15:
            return "]" + text[1:]
        if min(top[2] - middle[2], bottom[2] - middle[2]) >= glyph.width * 0.15:
            return "[" + text[1:]
    return text
