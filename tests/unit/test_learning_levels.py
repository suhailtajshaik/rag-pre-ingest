"""Supplied paired-row image must retain label/description associations."""

import hashlib
from pathlib import Path

from rag_pre_ingest.config import Settings
from rag_pre_ingest.pipeline.engine import run_pipeline


def test_learning_level_labels_stay_with_their_descriptions(tmp_path: Path) -> None:
    path = Path("tests/fixtures/user_samples/learning-levels.png")
    data = path.read_bytes()
    result = run_pipeline(
        data,
        "png",
        path.name,
        hashlib.sha256(data).hexdigest(),
        "levels",
        Settings(),
        tmp_path,
    )
    phrases = [
        "Level 1",
        "Master advanced prompting",
        "Level 2",
        "Integrate connectors",
        "Level 3",
        "Learn about Diffusion Models",
        "Level 4",
        "Build complex automations",
        "Level 5",
        "Build a real world",
    ]
    positions = [result.markdown.index(phrase) for phrase in phrases]
    assert positions == sorted(positions)
    assert result.stats.pages.ocr == 1
    assert len([b for b in result.pages[0].blocks if b.text.startswith("Level ")]) == 5
