"""Job queries and result access, independent of HTTP route handlers."""

from pathlib import Path

from rag_pre_ingest.models.api import JobResponse
from rag_pre_ingest.storage.jobs import JobRepository


class ResultUnavailable(Exception):
    def __init__(self, code: str, message: str, status: int) -> None:
        self.code, self.message, self.status = code, message, status


class ResultService:
    def __init__(self, repository: JobRepository) -> None:
        self.repository = repository

    def job(self, job_id: str) -> JobResponse:
        job = self.repository.get_job(job_id)
        if job is None:
            raise ResultUnavailable("job_not_found", "Job not found.", 404)
        return JobResponse.model_validate({**job, "job_id": job["id"]})

    def recent(self) -> list[JobResponse]:
        return [
            JobResponse.model_validate({**job, "job_id": job["id"]})
            for job in self.repository.list_jobs()
        ]

    def path(self, job_id: str, markdown: bool = False) -> Path:
        self.job(job_id)
        paths = self.repository.result_paths(job_id)
        if paths is None:
            raise ResultUnavailable("result_not_ready", "The result is not ready.", 409)
        path = paths[1 if markdown else 0]
        if not path.is_file():
            raise ResultUnavailable("result_missing", "The saved result is unavailable.", 503)
        return path

    def page_image(self, job_id: str, page_number: int) -> bytes:
        from rag_pre_ingest.models.document import DocumentResult

        result = DocumentResult.model_validate_json(self.path(job_id).read_text())
        if page_number < 1 or page_number > len(result.pages):
            raise ResultUnavailable("page_not_found", "Page not found.", 404)
        preview = self.path(job_id).parent / f"page-{page_number}.png"
        if not preview.is_file():
            raise ResultUnavailable("preview_unavailable", "This page preview is unavailable.", 503)
        return preview.read_bytes()

    def image_crop(self, job_id: str, image_id: str) -> bytes:
        from rag_pre_ingest.models.document import DocumentResult

        result_path = self.path(job_id)
        result = DocumentResult.model_validate_json(result_path.read_text())
        if not any(
            block.id == image_id and block.type == "image"
            for page in result.pages
            for block in page.blocks
        ):
            raise ResultUnavailable("image_not_found", "Image not found.", 404)
        path = result_path.parent / f"{image_id}.png"
        if not path.is_file():
            raise ResultUnavailable("image_not_found", "Image crop is unavailable.", 404)
        return path.read_bytes()
