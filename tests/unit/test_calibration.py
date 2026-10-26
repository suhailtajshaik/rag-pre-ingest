"""Routing expectations are tested against held-out scenario families."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from rag_pre_ingest.pipeline.quality import QualityConfig, evaluate_quality, select_regions


def calibration() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts/calibrate_thresholds.py"
    spec = importlib.util.spec_from_file_location("synthetic_calibration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_candidates_and_default_tiebreak() -> None:
    module = calibration()
    assert len(module.candidates()) == 144
    selected, development, held_out = module.calibrate(module.labels())
    assert selected == QualityConfig()
    for counts in [development, held_out]:
        assert counts["false_positive"] == 0
        assert counts["false_negative"] == 0
        assert counts["region_failures"] == 0


def test_scenario_families_are_disjoint() -> None:
    module = calibration()
    examples = module.labels()
    development = {label.family for label in examples if label.split == "development"}
    held_out = {label.family for label in examples if label.split == "held_out"}
    assert not development & held_out
    assert len(held_out) >= 8


@pytest.mark.parametrize("name", ["01-clean.pdf", "12-blank.pdf", "short title", "short divider"])
def test_clean_and_short_pages_never_ocr(name: str) -> None:
    module = calibration()
    label = next(label for label in module.labels() if label.name.startswith(name))
    quality = evaluate_quality(label.page, QualityConfig())
    assert not quality.needs_ocr
    assert select_regions(label.page, quality) == []


@pytest.mark.parametrize("name", ["08-mixed.pdf", "09-caption.pdf"])
def test_mixed_pages_only_ocr_image_regions(name: str) -> None:
    module = calibration()
    label = next(label for label in module.labels() if label.name.startswith(name))
    quality = evaluate_quality(label.page, QualityConfig())
    assert quality.needs_ocr
    regions = select_regions(label.page, quality)
    assert regions
    assert (0.0, 0.0, label.page.width, label.page.height) not in regions
