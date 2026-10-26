"""Typed environment configuration without an extra settings dependency."""

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    data_dir: Path = Path("data")
    viewer_dir: Path = Path("viewer/dist")
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=500, gt=0)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
    max_zip_ratio: float = Field(default=100, gt=0)
    max_zip_uncompressed_bytes: int = Field(default=200 * 1024 * 1024, gt=0)
    worker_enabled: bool = True
    per_page_timeout_seconds: float = Field(default=30, gt=0)
    per_job_timeout_seconds: float = Field(default=300, gt=0)
    ocr_enabled: bool = True
    ocr_workers: int = Field(default=2, ge=1, le=8)
    ocr_min_region_width: int = Field(default=1260, ge=1)
    ocr_table_max_cells: int = Field(default=1024, ge=0, le=10000)
    ocr_table_timeout_seconds: float = Field(default=10, gt=0)
    ocr_model_dir: Path | None = None
    near_empty_characters: int = Field(default=5, ge=0)
    garbage_share_threshold: float = Field(default=0.01, ge=0, le=1)
    image_coverage_threshold: float = Field(default=0.8, ge=0, le=1)
    min_words_per_area: float = Field(default=0.00002, ge=0)
    low_ocr_confidence: float = Field(default=0.7, ge=0, le=1)
    decorative_max_area_fraction: float = Field(default=0.02, ge=0, le=1)

    @classmethod
    def from_env(cls) -> "Settings":
        values = {
            name: os.environ[f"RAG_{name.upper()}"]
            for name in cls.model_fields
            if f"RAG_{name.upper()}" in os.environ
        }
        return cls.model_validate(values)
