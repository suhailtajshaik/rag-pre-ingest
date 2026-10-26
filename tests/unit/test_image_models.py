import hashlib
from pathlib import Path

from PIL import Image, ImageDraw

from rag_pre_ingest.config import Settings
from rag_pre_ingest.pipeline.engine import run_pipeline
from rag_pre_ingest.pipeline.ocr_cards import card_regions


def test_rectangles_need_repeated_panels() -> None:
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, 200, 100), fill="black")
    assert card_regions(image) == []
    draw.rectangle((250, 30, 420, 100), fill="black")
    draw.rectangle((470, 30, 640, 100), fill="black")
    assert len(card_regions(image)) == 3
    assert card_regions(Image.new("RGB", (800, 600), "black")) == []


def test_real_card_names_stay_separate(tmp_path: Path) -> None:
    path = Path("tests/fixtures/user_samples/image-models.png")
    data = path.read_bytes()
    result = run_pipeline(
        data, "png", path.name, hashlib.sha256(data).hexdigest(), "cards", Settings(), tmp_path
    )
    cards = [b for b in result.pages[0].blocks if "_ocr_card" in b.id]
    assert result.markdown.index("Image Models") < result.markdown.index("Midjourney")
    assert len(cards) == 9
    labels = [
        "Midjourney",
        "Google",
        "ByteDance",
        "OpenAI",
        "Qwen",
        "Black Forest Labs",
        "Leonardo",
        "Ideogram",
        "Reve",
    ]
    for label, card in zip(labels, cards, strict=True):
        assert label in card.text
    assert "[by Alibaba]" in cards[4].text
    assert all(b.text not in ("K", "フ") or b.is_decorative for b in result.pages[0].blocks)
