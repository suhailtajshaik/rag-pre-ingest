"""Transport only; document decisions belong to services."""

from typing import Annotated, cast

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from rag_pre_ingest.models.api import ErrorResponse, JobResponse, UploadResponse
from rag_pre_ingest.models.document import DocumentResult
from rag_pre_ingest.services.uploads import UploadService
from rag_pre_ingest.storage.jobs import JobRepository

router = APIRouter(prefix="/v1")


@router.post(
    "/documents",
    response_model=UploadResponse,
    status_code=202,
    responses={
        200: {"model": UploadResponse},
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def upload_document(
    request: Request, response: Response, file: Annotated[UploadFile, File()]
) -> UploadResponse:
    service = cast(UploadService, request.app.state.upload_service)
    try:
        data = await file.read(service.settings.max_upload_bytes + 1)
        result = await run_in_threadpool(service.submit, data, file.filename or "")
    finally:
        await file.close()
    if result.already_exists:
        response.status_code = 200
    return result


@router.get("/jobs/{job_id}", response_model=JobResponse, responses={404: {"model": ErrorResponse}})
async def get_job(job_id: str, request: Request) -> JobResponse:
    repository = cast(JobRepository, request.app.state.repository)
    job = await run_in_threadpool(repository.get_job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobResponse.model_validate({**job, "job_id": job["id"]})


@router.get("/jobs", response_model=list[JobResponse])
async def recent_jobs(request: Request) -> list[JobResponse]:
    return await run_in_threadpool(request.app.state.result_service.recent)


@router.get("/jobs/{job_id}/result", response_model=DocumentResult)
async def job_result(job_id: str, request: Request) -> Response:
    from fastapi.responses import FileResponse

    path = await run_in_threadpool(request.app.state.result_service.path, job_id)
    return FileResponse(path, media_type="application/json")


@router.get("/jobs/{job_id}/markdown")
async def job_markdown(job_id: str, request: Request) -> Response:
    from fastapi.responses import FileResponse

    path = await run_in_threadpool(request.app.state.result_service.path, job_id, True)
    return FileResponse(path, media_type="text/markdown; charset=utf-8")


@router.get("/jobs/{job_id}/pages/{page_number}/image")
async def page_image(job_id: str, page_number: int, request: Request) -> Response:
    data = await run_in_threadpool(request.app.state.result_service.page_image, job_id, page_number)
    return Response(data, media_type="image/png")


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> Response:
    import asyncio
    from collections.abc import AsyncIterator

    from fastapi.responses import StreamingResponse

    service = request.app.state.result_service
    await run_in_threadpool(service.job, job_id)

    async def events() -> AsyncIterator[str]:
        previous = ""
        while not await request.is_disconnected():
            job = await run_in_threadpool(service.job, job_id)
            payload = job.model_dump_json()
            if payload != previous:
                yield f"event: progress\ndata: {payload}\n\n"
                previous = payload
            else:
                yield ": heartbeat\n\n"
            if job.status in {"done", "failed"}:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}/images/{image_id}")
async def image_crop(job_id: str, image_id: str, request: Request) -> Response:
    data = await run_in_threadpool(request.app.state.result_service.image_crop, job_id, image_id)
    return Response(data, media_type="image/png")


@router.delete("/jobs/{job_id}", status_code=204, responses={404: {"model": ErrorResponse}})
async def delete_job(job_id: str, request: Request) -> Response:
    await run_in_threadpool(request.app.state.deletion_service.delete, job_id)
    return Response(status_code=204)
