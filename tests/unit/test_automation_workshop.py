"""Real poster transcription preserves labels and lists without icon hallucinations."""

from pathlib import Path

from PIL import Image, ImageDraw

from rag_pre_ingest.config import Settings
from rag_pre_ingest.pipeline.engine import run_pipeline
from rag_pre_ingest.pipeline.ocr_icons import leading_icon_edge


def test_printed_ideograph_is_not_removed_by_script() -> None:
    image = Image.new("RGB", (200, 120), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 50, 60, 80), outline="white", width=3)
    draw.line((30, 65, 60, 65), fill="white", width=3)
    assert leading_icon_edge(image, (28, 48, 64, 84)) is None


def test_workshop_google_sheets_and_outcome_lists(tmp_path: Path) -> None:
    path = Path("tests/fixtures/user_samples/automation-workshop.png")
    result = run_pipeline(
        path.read_bytes(), "png", path.name, "hash", "workshop", Settings(), tmp_path
    )
    expected = [
        "Day 4: 2nd April / 30th April",
        "Timings : 7.30PM IST To 11.00PM IST / 10.00AM EST To 1.30PM EST",
        "AI Automations - Introduction To Automation With N8n",
        "Outcome:",
        "Basics Of Automations Using N8n",
        "Understanding Trigger & Actions In Automations",
        "Learn To Connect Sheet, Slack, ChatGPT Using N8n",
        "Duration: 3 Hours | LIVE",
        "n8n",
        "slack",
        "Google Sheets",
    ]
    for text in expected:
        assert text in result.markdown
    blocks = result.pages[0].blocks
    assert len([b for b in blocks if b.type == "list"]) == 3
    assert next(b for b in blocks if b.text == "slack").type == "paragraph"
    assert "里" not in result.markdown
    assert any("里" in o.text for o in result.pages[0].observations)
    assert len(next(b for b in blocks if b.text == "Google Sheets").observation_ids) >= 2
