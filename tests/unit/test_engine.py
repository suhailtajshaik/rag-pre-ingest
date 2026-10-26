from pathlib import Path

from rag_pre_ingest.config import Settings
from rag_pre_ingest.pipeline.engine import run_pipeline

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_clean_page_never_runs_ocr(tmp_path: Path, monkeypatch: object) -> None:
    from unittest.mock import patch

    with patch(
        "rag_pre_ingest.pipeline.engine.recognize", side_effect=AssertionError("No OCR")
    ) as ocr:
        result = run_pipeline(
            (FIXTURES / "synthetic/01-clean.pdf").read_bytes(),
            "pdf",
            "clean.pdf",
            "hash",
            "id",
            Settings(),
            tmp_path,
        )
    ocr.assert_not_called()
    assert "Ordinary readable paragraph." in result.markdown
    assert not result.pages[0].quality.needs_ocr


def test_actual_scan_and_crop(tmp_path: Path) -> None:
    result = run_pipeline(
        (FIXTURES / "synthetic/07-scan.pdf").read_bytes(),
        "pdf",
        "scan.pdf",
        "hash",
        "id",
        Settings(),
        tmp_path,
    )
    assert "SCANNED DOCUMENT" in result.markdown.upper()
    assert result.pages[0].method == "ocr"
    assert result.stats.images.with_ocr_text == 1
    assert not any(w.code == "empty_document" for w in result.warnings)
    assert not any("![" in line for line in result.markdown.splitlines())


def test_user_poster_ocr(tmp_path: Path) -> None:
    result = run_pipeline(
        (FIXTURES / "user_samples/hackathon-guidelines.png").read_bytes(),
        "png",
        "hackathon-guidelines.png",
        "hash",
        "poster",
        Settings(),
        tmp_path,
    )
    text = result.markdown.casefold()
    assert "agent" in text and "stacking" in text
    assert "rules" in text and "data usage" in text
    assert "guardrails" in text and "code of conduct" in text
    assert "provided datasets" in text
    assert sum(block.type == "list" for page in result.pages for block in page.blocks) == 23
    assert not any(line.strip() == "O" for line in result.markdown.splitlines())
    assert result.pages[0].quality.needs_ocr
    assert result.stats.pages.ocr == 1


def test_user_mind_map_labels(tmp_path: Path) -> None:
    result = run_pipeline(
        (FIXTURES / "user_samples/notebooklm-mind-map.png").read_bytes(),
        "png",
        "notebooklm-mind-map.png",
        "hash",
        "mindmap",
        Settings(),
        tmp_path,
    )
    text = result.markdown.casefold()
    for label in ("world modeling", "context encoder", "momentum encoders", "handling uncertainty"):
        assert label in text
    assert result.stats.pages.ocr == 1


def test_good_direct_text_survives_ocr_even_when_other_region_is_garbage() -> None:
    from rag_pre_ingest.models.document import Block, Page, Quality
    from rag_pre_ingest.pipeline.engine import reconcile

    direct = Block(
        id="direct",
        type="paragraph",
        text="Correct source text",
        markdown="Correct source text",
        bbox=(0, 0, 100, 20),
        source="read",
    )
    damaged = Block(
        id="bad", type="paragraph", text="\ufffd\ufffd", bbox=(0, 50, 100, 70), source="read"
    )
    page = Page(
        page_number=1,
        width=100,
        height=100,
        blocks=[direct, damaged],
        quality=Quality(needs_ocr=True, reasons=["garbage_characters"]),
    )
    guessed = Block(
        id="ocr", type="paragraph", text="Incorrect OCR guess", bbox=(0, 0, 100, 20), source="ocr"
    )
    warnings = reconcile(page, [guessed])
    assert page.blocks[0] == direct
    assert guessed not in page.blocks
    assert warnings[0].code == "source_disagreement"
    repaired = Block(
        id="repaired",
        type="paragraph",
        text="Recovered region",
        markdown="Recovered region",
        bbox=(0, 50, 100, 70),
        source="ocr",
    )
    reconcile(page, [repaired])
    assert repaired in page.blocks and damaged not in page.blocks
    assert direct in page.blocks


def test_user_palette_preserves_every_code_and_footer(tmp_path: Path) -> None:
    result = run_pipeline(
        (FIXTURES / "user_samples/theme-palette.png").read_bytes(),
        "png",
        "theme-palette.png",
        "hash",
        "palette",
        Settings(),
        tmp_path,
    )
    for value in (
        "#F5F7F2",
        "#FFFFFF",
        "#D4DDD5",
        "#1A2E1C",
        "#16A34A",
        "#15803D",
        "#22C55E",
        "#0C120D",
        "#151E16",
        "#253026",
        "#E2EDE3",
        "#4ADE80",
        "#86EFAC",
    ):
        assert value in result.markdown, (value, result.markdown)
    for phrase in ("Vibe: Calm, trustworthy, organic", "Like: Loom, Notion, Cal.com"):
        assert phrase in result.markdown
    tables = [block for page in result.pages for block in page.blocks if block.type == "table"]
    assert len(tables) == 2
    assert tables[0].cells[0].text == "LIGHT"
    assert tables[1].cells[0].text == "DARK"
    assert all(block.columns == 2 for block in tables)
