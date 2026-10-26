"""Application factory and consistent error handling."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from rag_pre_ingest.api.limits import UploadBodyLimit
from rag_pre_ingest.api.routes import router
from rag_pre_ingest.config import Settings
from rag_pre_ingest.pipeline.validation import ValidationError
from rag_pre_ingest.services.deletion import DeletionService
from rag_pre_ingest.services.results import ResultService, ResultUnavailable
from rag_pre_ingest.services.uploads import UploadService
from rag_pre_ingest.services.worker import Worker
from rag_pre_ingest.storage.jobs import JobRepository


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()
    repository = JobRepository(config.data_dir / "jobs.sqlite3")
    worker = Worker(config, repository)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repository.initialize()
        task = asyncio.create_task(worker.run()) if config.worker_enabled else None
        try:
            yield
        finally:
            worker.stop()
            if task is not None:
                await task

    app = FastAPI(title="rag-pre-ingest", lifespan=lifespan)
    app.add_middleware(
        UploadBodyLimit,
        max_bytes=config.max_upload_bytes + 65536,
        record_rejection=repository.record_rejection,
    )
    app.state.settings = config
    app.state.repository = repository
    app.state.upload_service = UploadService(config, repository)
    app.state.result_service = ResultService(repository)
    app.state.deletion_service = DeletionService(repository, worker, config)
    app.include_router(router)
    if config.viewer_dir.is_dir():
        app.mount("/", StaticFiles(directory=config.viewer_dir, html=True), name="viewer")

    @app.exception_handler(ResultUnavailable)
    async def result_error(request: Request, exc: ResultUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}}
        )

    @app.exception_handler(ValidationError)
    async def upload_error(request: Request, exc: ValidationError) -> JSONResponse:
        status = 413 if exc.code in {"file_too_large", "oversized_file"} else 400
        return JSONResponse(
            status_code=status, content={"error": {"code": exc.code, "message": exc.message}}
        )

    @app.exception_handler(RequestValidationError)
    async def request_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        message = (
            "A valid multipart file field is required."
            if request.url.path == "/v1/documents"
            else "Request parameters failed validation."
        )
        if request.url.path == "/v1/documents":
            await asyncio.to_thread(
                repository.record_rejection,
                "",
                "invalid_request",
                "A valid multipart file field is required.",
            )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": message,
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "job_not_found" if exc.status_code == 404 else "http_error",
                    "message": str(exc.detail),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).error("Request failed", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "The request could not be completed.",
                }
            },
        )

    return app


app = create_app()
