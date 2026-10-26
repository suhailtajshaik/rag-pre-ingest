"""Milestone one API contracts."""

from typing import Literal

from pydantic import BaseModel

from rag_pre_ingest.models.document import Stats, Warning


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class UploadResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"] = "queued"
    already_exists: bool = False


class JobResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "failed"]
    current_stage: str
    progress: float
    error: str | None
    file_name: str
    file_type: str
    file_hash: str
    created_at: str
    warnings: list[Warning]
    stats: Stats | None = None
    error_code: str | None = None
