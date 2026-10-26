"""Diagram linework must never replace recognized prose with invented table cells."""

from pathlib import Path
from unittest.mock import patch

from rag_pre_ingest.config import Settings
from rag_pre_ingest.pipeline.engine import run_pipeline


def test_flowchart_preserves_every_step_description_without_false_tables(tmp_path: Path) -> None:
    path = Path("tests/fixtures/user_samples/llm-flowchart.png")
    with patch("socket.socket.connect", side_effect=AssertionError("Local OCR only")):
        result = run_pipeline(
            path.read_bytes(), "png", path.name, "hash", "flowchart", Settings(), tmp_path
        )
    assert not [block for page in result.pages for block in page.blocks if block.type == "table"]
    text = " ".join(result.markdown.split())
    phrases = [
        "Tokenization",
        "Text is broken into tokens for the model to process",
        "Embedding",
        "Tokens are converted into numerical vectors that represent meaning",
        "Transformer Mechanism",
        "The model uses attention to focus on the most relevant parts of input text.",
        "Prediction",
        "It predicts the next word based on prior context",
        "Response Generation",
        "The model generates sentences by iteratively predicting words, "
        "maintaining relevance and coherence",
    ]
    positions = [text.index(phrase) for phrase in phrases]
    assert positions == sorted(positions)
