"""Examples for pure OCR signals and region selection."""

import pytest

from rag_pre_ingest.models.document import Block, Page
from rag_pre_ingest.pipeline.quality import (
    QualityConfig,
    evaluate_quality,
    garbage_share,
    select_regions,
    union_area,
)


def page(text: str = "", images: list[tuple[float, float, float, float]] | None = None) -> Page:
    blocks = [Block(id="text", type="paragraph", text=text, bbox=(0, 0, 100, 20))] if text else []
    blocks.extend(
        Block(id=f"image{i}", type="image", bbox=box) for i, box in enumerate(images or [])
    )
    return Page(page_number=1, width=100, height=100, blocks=blocks)


@pytest.mark.parametrize(
    "text", ["", "Title", "This is a normal paragraph with plenty of readable words."]
)
def test_short_or_empty_text_without_image_does_not_request_ocr(text: str) -> None:
    original = page(text)
    quality = evaluate_quality(original, QualityConfig())
    assert not quality.needs_ocr
    assert select_regions(original, quality) == []
    assert original.quality is None


def test_scan_requests_full_page_and_records_signals() -> None:
    original = page("Hi", [(0, 0, 100, 100)])
    quality = evaluate_quality(original, QualityConfig())
    assert quality.character_count == 2
    assert quality.image_coverage == 1
    assert quality.needs_ocr
    assert "near_empty_text" in quality.reasons
    assert select_regions(original, quality) == [(0, 0, 100, 100)]


def test_small_image_does_not_force_clean_text_to_whole_page_ocr() -> None:
    original = page("This readable paragraph stays on its direct read path.", [(20, 30, 50, 60)])
    quality = evaluate_quality(original, QualityConfig())
    assert quality.image_coverage == pytest.approx(0.09)
    assert "near_empty_text" not in quality.reasons
    assert select_regions(original, quality) == [(20, 30, 50, 60)]


def test_image_coverage_clips_bounds_and_does_not_double_count() -> None:
    original = page(images=[(-20, -20, 70, 100), (30, 0, 120, 100)])
    quality = evaluate_quality(original, QualityConfig())
    assert quality.image_coverage == 1
    assert union_area([(0, 0, 5, 5), (2, 2, 7, 7)]) == 41
    assert union_area([]) == 0
    assert union_area([(3, 3, 1, 1)]) == 0


@pytest.mark.parametrize("text", ["\ufffd", "\ue001", "\U000f0001", "\U00100001", "cafÃ©", "â€™"])
def test_broken_glyph_or_encoding_requests_only_damaged_block(text: str) -> None:
    original = page(text)
    quality = evaluate_quality(original, QualityConfig())
    assert quality.garbage_share > 0.01
    assert "garbage_characters" in quality.reasons
    assert select_regions(original, quality) == [(0, 0, 100, 20)]


def test_valid_multilingual_characters_are_not_garbage() -> None:
    assert garbage_share("São Paulo café 日本語 العربية") == 0
    assert garbage_share("") == 0


def test_garbage_threshold_is_strict_and_configurable() -> None:
    original = page("a" * 99 + "\ufffd")
    assert not evaluate_quality(original, QualityConfig()).needs_ocr
    assert evaluate_quality(original, QualityConfig(garbage_share_threshold=0.009)).needs_ocr


def test_image_coverage_threshold_is_inclusive_and_configurable() -> None:
    original = page(images=[(0, 0, 80, 100)])
    assert "image_coverage" in evaluate_quality(original, QualityConfig()).reasons
    quality = evaluate_quality(original, QualityConfig(image_coverage_threshold=0.9))
    assert "image_coverage" not in quality.reasons
    assert select_regions(original, quality) == [(0, 0, 80, 100)]


def test_sparse_signal_requires_images_and_uses_configured_density() -> None:
    original = page("Word", [(0, 0, 10, 10)])
    assert (
        "sparse_text" in evaluate_quality(original, QualityConfig(min_words_per_area=0.001)).reasons
    )
    assert (
        "sparse_text"
        not in evaluate_quality(page("Word"), QualityConfig(min_words_per_area=0.001)).reasons
    )


def test_decorative_images_and_invalid_page_bounds_do_not_escalate() -> None:
    original = page(images=[(0, 0, 100, 100)])
    original.blocks[0].is_decorative = True
    assert not evaluate_quality(original, QualityConfig()).needs_ocr
    original.width = 0
    assert select_regions(original, evaluate_quality(original, QualityConfig())) == []


def test_large_image_does_not_ocr_good_footer() -> None:
    original = page("Good direct footer", [(0, 0, 100, 85)])
    original.blocks[0].bbox = (0, 90, 100, 100)
    quality = evaluate_quality(original, QualityConfig())
    assert "image_coverage" in quality.reasons
    assert select_regions(original, quality) == [(0, 0, 100, 85)]
