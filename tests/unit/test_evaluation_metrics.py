"""Counterexamples for complete text and source-addressed structure scores."""

from __future__ import annotations

import importlib.util
import json
import sys
from itertools import permutations
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "evaluation_metrics.py"
SPEC = importlib.util.spec_from_file_location("evaluation_metrics", MODULE_PATH)
assert SPEC and SPEC.loader
metrics = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = metrics
SPEC.loader.exec_module(metrics)


@pytest.mark.parametrize(
    ("reference", "actual", "distance"),
    [("kitten", "sitting", 3), ("", "logo", 4), ("abc", "", 3), ("same", "same", 0)],
)
def test_edit_distance_examples(reference: str, actual: str, distance: int) -> None:
    assert metrics.edit_distance(reference, actual) == distance
    assert metrics.edit_distance(actual, reference) == distance


def test_complete_text_counts_inventions_and_missing_words() -> None:
    result = metrics.text_metrics("one two three", "one invented three extra")
    assert result.word_errors == 2
    assert result.wer == pytest.approx(2 / 3)
    assert not result.exact
    assert metrics.text_metrics("", "logo").wer == 1
    assert metrics.text_metrics("", "").exact
    assert metrics.text_metrics("a", "a b c").wer == 2


def test_normalization_keeps_meaningful_symbols_and_case() -> None:
    assert metrics.text_metrics("café\n €10", "cafe\u0301  €10").exact
    assert not metrics.text_metrics("2. €10", "1. $10").exact
    assert not metrics.text_metrics("CLAUDE", "claude").exact
    assert not metrics.text_metrics("I’M", "I'M").exact


def test_order_missing_extra_and_reversed() -> None:
    result = metrics.order_metrics(["a", "b", "c"], ["a", "c", "b", "logo"])
    assert result.matched == 1
    assert result.precision == 0.25
    assert result.recall == pytest.approx(1 / 3)
    assert not result.exact
    with pytest.raises(ValueError, match="unique"):
        metrics.order_metrics(["a"], ["a", "a"])


def test_all_synthetic_order_permutations_only_identity_passes() -> None:
    # Deterministic adversarial metric inputs, not an unseen OCR/layout benchmark.
    reference = ["title", "left", "right", "footer"]
    for candidate in permutations(reference):
        assert metrics.order_metrics(reference, candidate).exact == (list(candidate) == reference)


def test_grouping_rejects_cross_card_merge_and_accepts_reordering() -> None:
    expected = [["light", "light-value"], ["dark", "dark-value"]]
    assert metrics.grouping_metrics(expected, [expected[1][::-1], expected[0]]).exact
    result = metrics.grouping_metrics(expected, [["light", "dark"], ["light-value", "dark-value"]])
    assert result.matched == 0
    assert not result.exact
    with pytest.raises(ValueError):
        metrics.grouping_metrics(expected, [["light"], ["light"]])
    with pytest.raises(ValueError):
        metrics.grouping_metrics([], [[]])


def test_cells_count_blanks_positions_and_extra_cells() -> None:
    expected = {(0, 0, 0): "Name", (0, 1, 0): "", (0, 1, 1): "€20"}
    actual = {(0, 0, 0): "Name", (0, 1, 0): "€20", (0, 1, 1): "", (0, 2, 0): "extra"}
    result = metrics.cell_metrics(expected, actual)
    assert result.matched == 1
    assert result.precision == 0.25
    assert result.recall == pytest.approx(1 / 3)
    assert not metrics.cell_metrics({(0, 0): ""}, {}).exact
    assert metrics.cell_metrics({}, {}).exact
    assert metrics.cell_metrics({(0, 0, 2, 1): "Header"}, {(0, 0, 2, 1): "Header"}).exact


def test_ground_truth_is_explicitly_seen_and_catches_repeated_numbering() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "ground_truth"
    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["held_out_real_documents"] == []
    case = manifest["cases"][0]
    assert case["split"] == "regression"
    expected = (root / case["transcription"]).read_text()
    assert metrics.text_metrics(expected, expected).exact
    assert not metrics.text_metrics(
        expected, expected.replace("2.", "1.").replace("3.", "1.")
    ).exact
    assert not metrics.text_metrics(expected, expected + " random logo").exact
