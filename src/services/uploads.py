"""Validate first, then hash and persist an upload."""

import hashlib
import logging

from rag_pre_ingest.config import Settings
from rag_pre_ingest.models.api import UploadResponse
from rag_pre_ingest.pipeline.validation import ValidationConfig, ValidationError, validate_upload
from rag_pre_ingest.storage.jobs import JobRepository

logger = logging.getLogger(__name__)


class UploadService:
    def __init__(self, settings: Settings, repository: JobRepository) -> None:
        self.settings = settings
        self.repository = repository

    def reject(self, filename: str, code: str, message: str) -> None:
        self.repository.record_rejection(filename, code, message)

    def submit(self, data: bytes, filename: str) -> UploadResponse:
        settings = self.settings
        try:
            validated = validate_upload(
                data,
                filename,
                ValidationConfig(
                    max_bytes=settings.max_upload_bytes,
                    max_pages=settings.max_pages,
                    max_image_pixels=settings.max_image_pixels,
                    max_zip_ratio=settings.max_zip_ratio,
                    max_zip_uncompressed_bytes=settings.max_zip_uncompressed_bytes,
                ),
            )
        except ValidationError as exc:
            self.reject(filename, exc.code, exc.message)
            raise
        warnings: list[dict[str, object]] = []
        if validated.extension_mismatch:
            logger.warning("Upload extension differs from detected type")
            warnings.append(
                {
                    "code": "extension_mismatch",
                    "page_number": None,
                    "message": "Filename extension differs from detected file type.",
                }
            )
        job, existing = self.repository.create_job(
            hashlib.sha256(data).hexdigest(),
            filename,
            validated.file_type,
            data,
            settings.data_dir / "uploads",
            warnings=warnings,
        )
        return UploadResponse.model_validate(
            {"job_id": job["id"], "status": job["status"], "already_exists": existing}
        )
