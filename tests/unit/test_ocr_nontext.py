"""Non-text detections may be blank; uncertain letter-shaped graphics stay inspectable."""

import io
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from PIL import Image, ImageDraw

from rag_pre_ingest.pipeline import ocr
from rag_pre_ingest.pipeline.ocr_lists import is_symbol_only


@pytest.mark.parametrize("text", ["→", "□ ◇", "---", "|", "•", "£€", "×÷=", "?!", "★★★", "😀"])
def test_standalone_symbols_are_nontext(text: str) -> None:
    assert is_symbol_only(text)


@pytest.mark.parametrize(
    "text",
    [
        "O",
        "0",
        "A",
        "日",
        "α",
        "م",
        "Ⅳ",
        "½",
        "résumé",
        "Привет",
        "math 3×4=12 £€",
        "£12.50",
        "x ≤ y",
        "• An actual list item",
    ],
)
def test_unicode_letters_numbers_and_surrounding_symbols_are_kept(text: str) -> None:
    assert not is_symbol_only(text)


@pytest.mark.parametrize(
    "boxes,texts,scores", [(None, None, None), ([], [], None), ([], ["invented"], [0.9])]
)
def test_no_detected_text_boxes_produces_no_fallback_output(
    boxes: object,
    texts: object,
    scores: object,
) -> None:
    result = SimpleNamespace(boxes=boxes, txts=texts, scores=scores)
    with patch.object(ocr, "_get_engine", return_value=Mock(return_value=result)):
        assert ocr.recognize(b"not-needed", 1) == []


@pytest.mark.parametrize("text", ["→", "---", "•", "£€", "□□"])
def test_symbol_only_raw_detection_is_retained_but_excluded_from_markdown(text: str) -> None:
    result = SimpleNamespace(
        boxes=[[[0, 0], [40, 0], [40, 20], [0, 20]]], txts=[text], scores=[0.91]
    )
    with patch.object(ocr, "_get_engine", return_value=Mock(return_value=result)):
        blocks = ocr.recognize(b"not-needed", 1)
    assert len(blocks) == 1
    assert blocks[0].text == text
    assert blocks[0].type == "other"
    assert blocks[0].is_decorative
    assert blocks[0].markdown == ""
    assert blocks[0].confidence == 0.91


@pytest.mark.parametrize("text", ["O", "0", "A", "math 3×4=12 £€"])
def test_short_or_mixed_real_text_is_not_discarded_even_at_weak_confidence(text: str) -> None:
    result = SimpleNamespace(
        boxes=[[[0, 0], [40, 0], [40, 20], [0, 20]]], txts=[text], scores=[0.12]
    )
    with patch.object(ocr, "_get_engine", return_value=Mock(return_value=result)):
        block = ocr.recognize(b"not-needed", 1)[0]
    assert block.type == "paragraph"
    assert not block.is_decorative
    assert block.markdown == text
    assert block.confidence == 0.12


def test_real_shape_only_image_records_letter_shaped_arrow_ambiguity() -> None:
    image = Image.new("RGB", (900, 600), "white")
    draw = ImageDraw.Draw(image)
    # Empty rectangles and arrows, without text or letter-like O/0 circles.
    draw.rectangle((80, 80, 290, 210), outline="#164c84", width=5)
    draw.rectangle((590, 80, 800, 210), outline="#164c84", width=5)
    draw.line((320, 145, 550, 145), fill="black", width=6)
    draw.polygon(((550, 145), (520, 125), (520, 165)), fill="black")
    draw.polygon(((150, 360), (230, 300), (310, 360), (230, 420)), outline="#0b7074", width=5)
    draw.line((350, 360, 670, 360), fill="black", width=5)
    draw.polygon(((670, 360), (640, 340), (640, 380)), fill="black")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    with patch("socket.socket.connect", side_effect=AssertionError("OCR must remain offline")):
        blocks = ocr.recognize(encoded.getvalue(), 1)
    print(
        "Real shape-only OCR detections:", [(b.text, b.is_decorative, b.confidence) for b in blocks]
    )
    assert all(block.is_decorative or block.confidence is not None for block in blocks)
    # Known model limitation: this arrowhead looks like X. Keep its raw observation
    # instead of deleting every legitimate X using an arbitrary confidence gate.
    assert [(block.text, block.is_decorative) for block in blocks] == [("X", False)]
    assert blocks[0].source == "ocr"


def test_real_empty_rectangles_produce_blank_output() -> None:
    image = Image.new("RGB", (900, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 290, 210), outline="#164c84", width=5)
    draw.rectangle((590, 80, 800, 210), outline="#164c84", width=5)
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    with patch("socket.socket.connect", side_effect=AssertionError("OCR must remain offline")):
        blocks = ocr.recognize(encoded.getvalue(), 1)
    print("Real rectangle-only OCR detections:", blocks)
    assert blocks == []


def test_real_symbol_shaped_diamond_has_blank_clean_output() -> None:
    image = Image.new("RGB", (900, 600), "white")
    ImageDraw.Draw(image).polygon(
        ((150, 360), (230, 300), (310, 360), (230, 420)),
        outline="#0b7074",
        width=5,
    )
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    with patch("socket.socket.connect", side_effect=AssertionError("OCR must remain offline")):
        blocks = ocr.recognize(encoded.getvalue(), 1)
    print("Real diamond-only OCR detections:", [(b.text, b.markdown) for b in blocks])
    assert all(block.is_decorative and not block.markdown for block in blocks)
