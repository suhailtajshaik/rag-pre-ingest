"""Delete generated document assets under the worker's publication lock."""

import re
import shutil

from rag_pre_ingest.config import Settings
from rag_pre_ingest.services.results import ResultUnavailable
from rag_pre_ingest.services.worker import Worker
from rag_pre_ingest.storage.jobs import JobRepository


class DeletionService:
    def __init__(self, repository: JobRepository, worker: Worker, settings: Settings) -> None:
        self.repository = repository
        self.worker = worker
        self.settings = settings

    def delete(self, job_id: str) -> None:
        with self.worker.lock:
            if self.repository.get_job(job_id) is None:
                raise ResultUnavailable("job_not_found", "Job not found.", 404)
            if re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
                raise ResultUnavailable(
                    "unsafe_storage_path", "Document storage path is unsafe.", 503
                )
            upload_root = (self.settings.data_dir / "uploads").resolve()
            result_root = (self.settings.data_dir / "results").resolve()
            upload = upload_root / job_id
            results = result_root / job_id
            saved_upload = self.repository.upload_path(job_id)
            if (
                saved_upload is None
                or saved_upload.resolve() != upload
                or upload.resolve() != upload
                or results.resolve() != results
            ):
                raise ResultUnavailable(
                    "unsafe_storage_path", "Document storage path is unsafe.", 503
                )
            process = self.worker.active_process
            if self.worker.active_job_id == job_id and process is not None and process.is_alive():
                process.terminate()
            upload.unlink(missing_ok=True)
            if results.exists():
                shutil.rmtree(results)
            self.repository.delete_job(job_id)
