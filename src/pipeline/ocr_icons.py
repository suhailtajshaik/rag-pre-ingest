"""Separate a large filled page-shaped icon from an overlapping OCR line."""

from PIL import Image

from rag_pre_ingest.pipeline.ocr_lists import BBox, _components


def leading_icon_edge(image: Image.Image, bbox: BBox) -> float | None:
    """Return a filled rectangular prefix's right edge, never infer it from script.

    A component must extend above the recognized line and have a solid outer
    silhouette. Ordinary letters, including ideographs, cannot satisfy that
    geometry. The caller can re-read only the remaining text crop.
    """
    x0, y0, x1, y1 = bbox
    h = y1 - y0
    if h < 8:
        return None
    left, top = max(0, int(x0 - h * 0.3)), max(0, int(y0 - h))
    right, bottom = min(image.width, int(x0 + h * 2)), min(image.height, int(y1))
    crop = image.crop((left, top, right, bottom)).convert("RGB")
    data = crop.tobytes()
    points = {
        (x, y)
        for y in range(crop.height)
        for x in range(crop.width)
        if min(data[(y * crop.width + x) * 3 : (y * crop.width + x) * 3 + 3]) > 200
    }
    for group in _components(points):
        a, b = min(x for x, y in group), min(y for x, y in group)
        c, d = max(x for x, y in group) + 1, max(y for x, y in group) + 1
        w, height = c - a, d - b
        if (
            0.6 * h < w < 1.8 * h
            and height > 1.15 * h
            and 0.45 < w / height < 0.85
            and len(group) / (w * height) > 0.6
            and top + b < y0 - 0.3 * h
        ):
            return float(left + c)
    return None
